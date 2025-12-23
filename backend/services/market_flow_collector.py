"""
Market Flow Data Collector Service

Collects real-time market flow data from Hyperliquid using native SDK WebSocket:
- Trades (for CVD, Taker Volume)
- L2 Orderbook (for Depth Ratio, Liquidity)
- Asset Context (for OI, Funding Rate, Premium)

Data is aggregated in 15-second windows and persisted to database.
"""

import json
import time
import logging
import threading
from decimal import Decimal
from typing import Dict, List, Optional, Any
from collections import defaultdict
from dataclasses import dataclass, field

from hyperliquid.info import Info

logger = logging.getLogger(__name__)

# Aggregation window in seconds
AGGREGATION_WINDOW_SECONDS = 15

# Connection health check settings
HEALTH_CHECK_INTERVAL_SECONDS = 30
DATA_STALE_THRESHOLD_SECONDS = 30  # Consider data stale if no update for 30s
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_BASE_DELAY_SECONDS = 5


@dataclass
class TradeBuffer:
    """Buffer for aggregating trades within a time window"""
    taker_buy_volume: Decimal = Decimal("0")
    taker_sell_volume: Decimal = Decimal("0")
    taker_buy_count: int = 0
    taker_sell_count: int = 0
    taker_buy_notional: Decimal = Decimal("0")
    taker_sell_notional: Decimal = Decimal("0")
    high_price: Optional[Decimal] = None
    low_price: Optional[Decimal] = None
    total_volume: Decimal = Decimal("0")
    total_notional: Decimal = Decimal("0")

    def reset(self):
        """Reset buffer for next window"""
        self.taker_buy_volume = Decimal("0")
        self.taker_sell_volume = Decimal("0")
        self.taker_buy_count = 0
        self.taker_sell_count = 0
        self.taker_buy_notional = Decimal("0")
        self.taker_sell_notional = Decimal("0")
        self.high_price = None
        self.low_price = None
        self.total_volume = Decimal("0")
        self.total_notional = Decimal("0")


class MarketFlowCollector:
    """
    Singleton service for collecting market flow data via WebSocket.
    Aggregates data in 15-second windows and persists to database.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self.info: Optional[Info] = None
        self.running = False
        self.subscribed_symbols: List[str] = []
        self.subscription_ids: Dict[str, Dict[str, int]] = defaultdict(dict)

        # Data buffers
        self.trade_buffers: Dict[str, TradeBuffer] = {}
        self.latest_orderbook: Dict[str, Any] = {}
        self.latest_asset_ctx: Dict[str, Any] = {}

        # Data freshness tracking (timestamp of last update for each data source)
        self.last_update_time: Dict[str, float] = {
            "l2book": 0.0,
            "asset_ctx": 0.0,
            "trades": 0.0,
        }

        # Timing
        self.last_flush_time = time.time()
        self.flush_timer: Optional[threading.Timer] = None
        self.health_check_timer: Optional[threading.Timer] = None

        # Reconnection state
        self.reconnect_attempts = 0
        self.is_reconnecting = False
        self.reconnect_lock = threading.Lock()

        # Thread safety
        self.buffer_lock = threading.Lock()

        logger.info("MarketFlowCollector initialized")

    def start(self, symbols: Optional[List[str]] = None):
        """Start the collector with given symbols or from watchlist"""
        if self.running:
            logger.warning("MarketFlowCollector already running")
            return

        # Get symbols from watchlist if not provided
        if symbols is None:
            from services.hyperliquid_symbol_service import get_selected_symbols
            symbols = get_selected_symbols()

        if not symbols:
            logger.warning("No symbols to monitor, collector not started")
            return

        # Store symbols for retry
        self._pending_symbols = symbols
        self.reconnect_attempts = 0

        # Try to start with retry logic
        self._start_with_retry()

    def _start_with_retry(self):
        """Internal method to start collector with retry on failure"""
        symbols = getattr(self, '_pending_symbols', None)
        if not symbols:
            logger.warning("No pending symbols for retry")
            return

        try:
            base_url = "https://api.hyperliquid.xyz"
            logger.info(f"[Start] Connecting to Hyperliquid API: {base_url}")
            self.info = Info(base_url=base_url, skip_ws=False)

            self.running = True
            self.subscribed_symbols = []
            self.reconnect_attempts = 0

            for symbol in symbols:
                self._subscribe_symbol(symbol)

            self._schedule_flush()
            self._schedule_health_check()

            logger.info(f"MarketFlowCollector started with symbols: {symbols}")

        except Exception as e:
            logger.error(f"Failed to start MarketFlowCollector: {e}", exc_info=True)
            self.running = False

            self.reconnect_attempts += 1
            if self.reconnect_attempts <= MAX_RECONNECT_ATTEMPTS:
                delay = RECONNECT_BASE_DELAY_SECONDS * (2 ** (self.reconnect_attempts - 1))
                logger.warning(
                    f"[Start] Will retry in {delay}s "
                    f"(attempt {self.reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS})"
                )
                retry_timer = threading.Timer(delay, self._start_with_retry)
                retry_timer.daemon = True
                retry_timer.start()
            else:
                logger.error(
                    f"[Start] FAILED after {MAX_RECONNECT_ATTEMPTS} attempts. "
                    f"Manual restart required!"
                )

    def stop(self):
        """Stop the collector and cleanup"""
        if not self.running:
            return

        self.running = False

        # Cancel flush timer
        if self.flush_timer:
            self.flush_timer.cancel()
            self.flush_timer = None

        # Cancel health check timer
        if self.health_check_timer:
            self.health_check_timer.cancel()
            self.health_check_timer = None

        # Flush remaining data
        self._flush_to_database()

        # Unsubscribe all
        for symbol in list(self.subscribed_symbols):
            self._unsubscribe_symbol(symbol)

        # Disconnect WebSocket
        if self.info and self.info.ws_manager:
            try:
                self.info.disconnect_websocket()
            except Exception as e:
                logger.warning(f"Error disconnecting websocket: {e}")

        self.info = None
        logger.info("MarketFlowCollector stopped")

    def refresh_subscriptions(self, new_symbols: List[str]):
        """Update subscriptions when watchlist changes"""
        if not self.running:
            return

        current = set(self.subscribed_symbols)
        new = set(new_symbols)

        # Unsubscribe removed symbols
        for symbol in current - new:
            self._unsubscribe_symbol(symbol)

        # Subscribe new symbols
        for symbol in new - current:
            self._subscribe_symbol(symbol)

    def _subscribe_symbol(self, symbol: str):
        """Subscribe to all data streams for a symbol"""
        if not self.info:
            return

        try:
            # Initialize buffer
            self.trade_buffers[symbol] = TradeBuffer()

            # Subscribe to trades
            trades_id = self.info.subscribe(
                {"type": "trades", "coin": symbol},
                lambda msg, s=symbol: self._on_trades(s, msg)
            )
            self.subscription_ids[symbol]["trades"] = trades_id

            # Subscribe to L2 orderbook
            l2_id = self.info.subscribe(
                {"type": "l2Book", "coin": symbol},
                lambda msg, s=symbol: self._on_l2book(s, msg)
            )
            self.subscription_ids[symbol]["l2Book"] = l2_id

            # Subscribe to asset context (OI, funding, etc.)
            ctx_id = self.info.subscribe(
                {"type": "activeAssetCtx", "coin": symbol},
                lambda msg, s=symbol: self._on_asset_ctx(s, msg)
            )
            self.subscription_ids[symbol]["activeAssetCtx"] = ctx_id

            self.subscribed_symbols.append(symbol)
            logger.info(f"Subscribed to market flow data for {symbol}")

        except Exception as e:
            logger.error(f"Failed to subscribe {symbol}: {e}")

    def _unsubscribe_symbol(self, symbol: str):
        """Unsubscribe from all data streams for a symbol"""
        if not self.info or symbol not in self.subscription_ids:
            return

        try:
            ids = self.subscription_ids[symbol]

            if "trades" in ids:
                self.info.unsubscribe({"type": "trades", "coin": symbol}, ids["trades"])
            if "l2Book" in ids:
                self.info.unsubscribe({"type": "l2Book", "coin": symbol}, ids["l2Book"])
            if "activeAssetCtx" in ids:
                self.info.unsubscribe({"type": "activeAssetCtx", "coin": symbol}, ids["activeAssetCtx"])

            del self.subscription_ids[symbol]
            if symbol in self.subscribed_symbols:
                self.subscribed_symbols.remove(symbol)
            if symbol in self.trade_buffers:
                del self.trade_buffers[symbol]

            logger.info(f"Unsubscribed from {symbol}")

        except Exception as e:
            logger.error(f"Failed to unsubscribe {symbol}: {e}")

    def _on_trades(self, symbol: str, msg: dict):
        """Handle incoming trade messages"""
        try:
            if msg.get("channel") != "trades":
                return

            trades = msg.get("data", [])
            if not trades:
                return

            # Update freshness timestamp
            self.last_update_time["trades"] = time.time()

            with self.buffer_lock:
                buffer = self.trade_buffers.get(symbol)
                if not buffer:
                    return

                for trade in trades:
                    # SDK returns: coin, side (A=ask/sell, B=bid/buy), px, sz, hash, time
                    price = Decimal(str(trade["px"]))
                    size = Decimal(str(trade["sz"]))
                    side = trade["side"]  # "A" = taker sell, "B" = taker buy
                    notional = price * size

                    # Update buffer
                    if side == "B":  # Taker buy
                        buffer.taker_buy_volume += size
                        buffer.taker_buy_count += 1
                        buffer.taker_buy_notional += notional
                    else:  # Taker sell (side == "A")
                        buffer.taker_sell_volume += size
                        buffer.taker_sell_count += 1
                        buffer.taker_sell_notional += notional

                    buffer.total_volume += size
                    buffer.total_notional += notional

                    # Track high/low
                    if buffer.high_price is None or price > buffer.high_price:
                        buffer.high_price = price
                    if buffer.low_price is None or price < buffer.low_price:
                        buffer.low_price = price

        except Exception as e:
            logger.error(f"Error processing trades for {symbol}: {e}")

    def _on_l2book(self, symbol: str, msg: dict):
        """Handle incoming L2 orderbook messages"""
        try:
            if msg.get("channel") != "l2Book":
                return

            data = msg.get("data", {})
            if data:
                self.latest_orderbook[symbol] = data
                # Update freshness timestamp
                self.last_update_time["l2book"] = time.time()

        except Exception as e:
            logger.error(f"Error processing l2book for {symbol}: {e}")

    def _on_asset_ctx(self, symbol: str, msg: dict):
        """Handle incoming asset context messages"""
        try:
            channel = msg.get("channel")
            if channel not in ("activeAssetCtx", "activeSpotAssetCtx"):
                return

            data = msg.get("data", {})
            if data:
                self.latest_asset_ctx[symbol] = data
                # Update freshness timestamp
                self.last_update_time["asset_ctx"] = time.time()

        except Exception as e:
            logger.error(f"Error processing asset ctx for {symbol}: {e}")

    def _schedule_health_check(self):
        """Schedule next health check"""
        if not self.running:
            return
        self.health_check_timer = threading.Timer(
            HEALTH_CHECK_INTERVAL_SECONDS, self._health_check_and_reschedule
        )
        self.health_check_timer.daemon = True
        self.health_check_timer.start()

    def _health_check_and_reschedule(self):
        """Check connection health and schedule next check"""
        if not self.running:
            return
        self._check_connection_health()
        self._schedule_health_check()

    def _check_connection_health(self):
        """Check if WebSocket data is stale and trigger reconnect if needed"""
        if self.is_reconnecting:
            logger.debug("Health check skipped - reconnection in progress")
            return

        now = time.time()
        # Check l2book and asset_ctx freshness (these should update frequently)
        l2book_age = now - self.last_update_time["l2book"] if self.last_update_time["l2book"] > 0 else -1
        asset_ctx_age = now - self.last_update_time["asset_ctx"] if self.last_update_time["asset_ctx"] > 0 else -1
        trades_age = now - self.last_update_time["trades"] if self.last_update_time["trades"] > 0 else -1

        # Log current health status
        logger.info(
            f"[HealthCheck] Data freshness - l2book: {l2book_age:.0f}s, "
            f"asset_ctx: {asset_ctx_age:.0f}s, trades: {trades_age:.0f}s "
            f"(threshold: {DATA_STALE_THRESHOLD_SECONDS}s)"
        )

        # If both are stale, connection is likely dead
        if (self.last_update_time["l2book"] > 0 and l2book_age > DATA_STALE_THRESHOLD_SECONDS and
            self.last_update_time["asset_ctx"] > 0 and asset_ctx_age > DATA_STALE_THRESHOLD_SECONDS):
            logger.warning(
                f"[HealthCheck] STALE DATA DETECTED! WebSocket likely disconnected. "
                f"l2book: {l2book_age:.0f}s ago, asset_ctx: {asset_ctx_age:.0f}s ago. "
                f"Initiating reconnect..."
            )
            self._reconnect()

    def _reconnect(self):
        """Reconnect WebSocket with exponential backoff"""
        with self.reconnect_lock:
            if self.is_reconnecting:
                logger.debug("[Reconnect] Already reconnecting, skipping")
                return
            self.is_reconnecting = True

        try:
            if self.reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                logger.error(
                    f"[Reconnect] FAILED - Max attempts ({MAX_RECONNECT_ATTEMPTS}) reached. "
                    f"Stopping collector. Manual restart required!"
                )
                self.stop()
                return

            self.reconnect_attempts += 1
            delay = RECONNECT_BASE_DELAY_SECONDS * (2 ** (self.reconnect_attempts - 1))
            logger.warning(
                f"[Reconnect] Attempt {self.reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS} "
                f"starting after {delay}s delay..."
            )
            time.sleep(delay)

            # Save current symbols
            symbols_to_restore = list(self.subscribed_symbols)
            logger.info(f"[Reconnect] Will restore {len(symbols_to_restore)} symbols: {symbols_to_restore}")

            # Disconnect old WebSocket
            logger.info("[Reconnect] Disconnecting old WebSocket...")
            if self.info and self.info.ws_manager:
                try:
                    self.info.disconnect_websocket()
                    logger.info("[Reconnect] Old WebSocket disconnected")
                except Exception as e:
                    logger.warning(f"[Reconnect] Error disconnecting old websocket: {e}")

            # Clear subscription state
            self.subscribed_symbols = []
            self.subscription_ids.clear()

            # Create new Info client
            logger.info("[Reconnect] Creating new Hyperliquid Info client...")
            base_url = "https://api.hyperliquid.xyz"
            self.info = Info(base_url=base_url, skip_ws=False)
            logger.info("[Reconnect] New Info client created")

            # Resubscribe to all symbols
            logger.info(f"[Reconnect] Resubscribing to {len(symbols_to_restore)} symbols...")
            for symbol in symbols_to_restore:
                self._subscribe_symbol(symbol)

            # Reset reconnect counter and update timestamps on success
            self.reconnect_attempts = 0
            now = time.time()
            self.last_update_time["l2book"] = now
            self.last_update_time["asset_ctx"] = now
            self.last_update_time["trades"] = now
            logger.warning(
                f"[Reconnect] SUCCESS! Resubscribed to {len(symbols_to_restore)} symbols. "
                f"Data collection resumed."
            )

        except Exception as e:
            logger.error(f"Reconnect failed: {e}", exc_info=True)
        finally:
            self.is_reconnecting = False

    def _schedule_flush(self):
        """Schedule next flush"""
        if not self.running:
            return
        self.flush_timer = threading.Timer(AGGREGATION_WINDOW_SECONDS, self._flush_and_reschedule)
        self.flush_timer.daemon = True
        self.flush_timer.start()

    def _flush_and_reschedule(self):
        """Flush data and schedule next flush"""
        if not self.running:
            return
        self._flush_to_database()
        self._schedule_flush()

    def _flush_to_database(self):
        """Flush all buffered data to database"""
        if not self.subscribed_symbols:
            return

        timestamp_ms = int(time.time() * 1000)
        # Align to 15-second boundary
        timestamp_ms = (timestamp_ms // (AGGREGATION_WINDOW_SECONDS * 1000)) * (AGGREGATION_WINDOW_SECONDS * 1000)

        try:
            from database.connection import SessionLocal
            from database.models import MarketTradesAggregated, MarketOrderbookSnapshots, MarketAssetMetrics

            db = SessionLocal()
            try:
                for symbol in self.subscribed_symbols:
                    self._flush_trades(db, symbol, timestamp_ms)
                    self._flush_orderbook(db, symbol, timestamp_ms)
                    self._flush_asset_metrics(db, symbol, timestamp_ms)

                db.commit()
                logger.debug(f"Flushed market flow data for {len(self.subscribed_symbols)} symbols")

                # Run signal detection after data flush
                self._run_signal_detection()

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to flush market flow data: {e}")
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Database error in flush: {e}")

    def _run_signal_detection(self):
        """Run signal detection for all subscribed symbols"""
        try:
            from services.signal_detection_service import signal_detection_service

            for symbol in self.subscribed_symbols:
                # Build market data context for signal detection
                market_data = {
                    "asset_ctx": self.latest_asset_ctx.get(symbol, {}),
                    "orderbook": self.latest_orderbook.get(symbol, {}),
                }

                # Detect signals (returns pool triggers now)
                triggered = signal_detection_service.detect_signals(symbol, market_data)
                if triggered:
                    logger.info(f"Pools triggered for {symbol}: {[p['pool_name'] for p in triggered]}")

        except Exception as e:
            logger.error(f"Error in signal detection: {e}", exc_info=True)

    def _flush_trades(self, db, symbol: str, timestamp_ms: int):
        """Flush trade buffer for a symbol"""
        from database.models import MarketTradesAggregated

        with self.buffer_lock:
            buffer = self.trade_buffers.get(symbol)
            if not buffer or buffer.total_volume == 0:
                return

            # Calculate VWAP
            vwap = None
            if buffer.total_volume > 0:
                vwap = buffer.total_notional / buffer.total_volume

            # Upsert: check if record exists, update or insert
            existing = db.query(MarketTradesAggregated).filter(
                MarketTradesAggregated.exchange == "hyperliquid",
                MarketTradesAggregated.symbol == symbol,
                MarketTradesAggregated.timestamp == timestamp_ms
            ).first()

            if existing:
                existing.taker_buy_volume = buffer.taker_buy_volume
                existing.taker_sell_volume = buffer.taker_sell_volume
                existing.taker_buy_count = buffer.taker_buy_count
                existing.taker_sell_count = buffer.taker_sell_count
                existing.taker_buy_notional = buffer.taker_buy_notional
                existing.taker_sell_notional = buffer.taker_sell_notional
                existing.vwap = vwap
                existing.high_price = buffer.high_price
                existing.low_price = buffer.low_price
            else:
                record = MarketTradesAggregated(
                    exchange="hyperliquid",
                    symbol=symbol,
                    timestamp=timestamp_ms,
                    taker_buy_volume=buffer.taker_buy_volume,
                    taker_sell_volume=buffer.taker_sell_volume,
                    taker_buy_count=buffer.taker_buy_count,
                    taker_sell_count=buffer.taker_sell_count,
                    taker_buy_notional=buffer.taker_buy_notional,
                    taker_sell_notional=buffer.taker_sell_notional,
                    vwap=vwap,
                    high_price=buffer.high_price,
                    low_price=buffer.low_price,
                )
                db.add(record)

            buffer.reset()

    def _flush_orderbook(self, db, symbol: str, timestamp_ms: int):
        """Flush orderbook snapshot for a symbol"""
        from database.models import MarketOrderbookSnapshots

        # Skip if data is stale (WebSocket disconnected)
        l2book_age = time.time() - self.last_update_time["l2book"]
        if self.last_update_time["l2book"] > 0 and l2book_age > DATA_STALE_THRESHOLD_SECONDS:
            logger.warning(f"[StaleData] Skipping orderbook flush for {symbol} - data is {l2book_age:.0f}s old")
            return

        data = self.latest_orderbook.get(symbol)
        if not data:
            return

        try:
            levels = data.get("levels", [[], []])
            bids = levels[0] if len(levels) > 0 else []
            asks = levels[1] if len(levels) > 1 else []

            best_bid = Decimal(bids[0]["px"]) if bids else None
            best_ask = Decimal(asks[0]["px"]) if asks else None
            spread = (best_ask - best_bid) if (best_bid and best_ask) else None

            # Calculate depth for top 5 and 10 levels
            bid_depth_5 = sum(Decimal(b["sz"]) for b in bids[:5])
            ask_depth_5 = sum(Decimal(a["sz"]) for a in asks[:5])
            bid_depth_10 = sum(Decimal(b["sz"]) for b in bids[:10])
            ask_depth_10 = sum(Decimal(a["sz"]) for a in asks[:10])

            # Count orders
            bid_orders = sum(b.get("n", 1) for b in bids)
            ask_orders = sum(a.get("n", 1) for a in asks)

            # Upsert: check if record exists, update or insert
            existing = db.query(MarketOrderbookSnapshots).filter(
                MarketOrderbookSnapshots.exchange == "hyperliquid",
                MarketOrderbookSnapshots.symbol == symbol,
                MarketOrderbookSnapshots.timestamp == timestamp_ms
            ).first()

            if existing:
                existing.best_bid = best_bid
                existing.best_ask = best_ask
                existing.spread = spread
                existing.bid_depth_5 = bid_depth_5
                existing.ask_depth_5 = ask_depth_5
                existing.bid_depth_10 = bid_depth_10
                existing.ask_depth_10 = ask_depth_10
                existing.bid_orders_count = bid_orders
                existing.ask_orders_count = ask_orders
                existing.raw_levels = json.dumps(levels)
            else:
                record = MarketOrderbookSnapshots(
                    exchange="hyperliquid",
                    symbol=symbol,
                    timestamp=timestamp_ms,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    spread=spread,
                    bid_depth_5=bid_depth_5,
                    ask_depth_5=ask_depth_5,
                    bid_depth_10=bid_depth_10,
                    ask_depth_10=ask_depth_10,
                    bid_orders_count=bid_orders,
                    ask_orders_count=ask_orders,
                    raw_levels=json.dumps(levels),
                )
                db.add(record)

        except Exception as e:
            logger.error(f"Error flushing orderbook for {symbol}: {e}")

    def _flush_asset_metrics(self, db, symbol: str, timestamp_ms: int):
        """Flush asset metrics for a symbol"""
        from database.models import MarketAssetMetrics

        # Skip if data is stale (WebSocket disconnected)
        asset_ctx_age = time.time() - self.last_update_time["asset_ctx"]
        if self.last_update_time["asset_ctx"] > 0 and asset_ctx_age > DATA_STALE_THRESHOLD_SECONDS:
            logger.warning(f"[StaleData] Skipping asset metrics flush for {symbol} - data is {asset_ctx_age:.0f}s old")
            return

        data = self.latest_asset_ctx.get(symbol)
        if not data:
            return

        try:
            ctx = data.get("ctx", {})

            # Upsert: check if record exists, update or insert
            existing = db.query(MarketAssetMetrics).filter(
                MarketAssetMetrics.exchange == "hyperliquid",
                MarketAssetMetrics.symbol == symbol,
                MarketAssetMetrics.timestamp == timestamp_ms
            ).first()

            if existing:
                existing.open_interest = Decimal(ctx["openInterest"]) if ctx.get("openInterest") else None
                existing.funding_rate = Decimal(ctx["funding"]) if ctx.get("funding") else None
                existing.mark_price = Decimal(ctx["markPx"]) if ctx.get("markPx") else None
                existing.oracle_price = Decimal(ctx["oraclePx"]) if ctx.get("oraclePx") else None
                existing.mid_price = Decimal(ctx["midPx"]) if ctx.get("midPx") else None
                existing.premium = Decimal(ctx["premium"]) if ctx.get("premium") else None
                existing.day_notional_volume = Decimal(ctx["dayNtlVlm"]) if ctx.get("dayNtlVlm") else None
            else:
                record = MarketAssetMetrics(
                    exchange="hyperliquid",
                    symbol=symbol,
                    timestamp=timestamp_ms,
                    open_interest=Decimal(ctx["openInterest"]) if ctx.get("openInterest") else None,
                    funding_rate=Decimal(ctx["funding"]) if ctx.get("funding") else None,
                    mark_price=Decimal(ctx["markPx"]) if ctx.get("markPx") else None,
                    oracle_price=Decimal(ctx["oraclePx"]) if ctx.get("oraclePx") else None,
                    mid_price=Decimal(ctx["midPx"]) if ctx.get("midPx") else None,
                    premium=Decimal(ctx["premium"]) if ctx.get("premium") else None,
                    day_notional_volume=Decimal(ctx["dayNtlVlm"]) if ctx.get("dayNtlVlm") else None,
                )
                db.add(record)

        except Exception as e:
            logger.error(f"Error flushing asset metrics for {symbol}: {e}")


# Singleton instance
market_flow_collector = MarketFlowCollector()


# Data retention settings
DATA_RETENTION_DAYS = 30


def cleanup_old_market_flow_data():
    """
    Delete market flow data older than DATA_RETENTION_DAYS.
    This function is designed to be called by a scheduled task.
    """
    import time
    from database.connection import SessionLocal
    from database.models import (
        MarketTradesAggregated,
        MarketOrderbookSnapshots,
        MarketAssetMetrics,
    )

    cutoff_ms = int((time.time() - DATA_RETENTION_DAYS * 86400) * 1000)

    db = SessionLocal()
    try:
        # Delete old trades
        trades_deleted = (
            db.query(MarketTradesAggregated)
            .filter(MarketTradesAggregated.timestamp < cutoff_ms)
            .delete(synchronize_session=False)
        )

        # Delete old orderbook snapshots
        orderbook_deleted = (
            db.query(MarketOrderbookSnapshots)
            .filter(MarketOrderbookSnapshots.timestamp < cutoff_ms)
            .delete(synchronize_session=False)
        )

        # Delete old asset metrics
        metrics_deleted = (
            db.query(MarketAssetMetrics)
            .filter(MarketAssetMetrics.timestamp < cutoff_ms)
            .delete(synchronize_session=False)
        )

        db.commit()

        total_deleted = trades_deleted + orderbook_deleted + metrics_deleted
        if total_deleted > 0:
            logger.info(
                f"Market flow data cleanup: deleted {trades_deleted} trades, "
                f"{orderbook_deleted} orderbook snapshots, {metrics_deleted} asset metrics "
                f"(older than {DATA_RETENTION_DAYS} days)"
            )
        else:
            logger.debug("Market flow data cleanup: no old records to delete")

    except Exception as e:
        db.rollback()
        logger.error(f"Market flow data cleanup failed: {e}")
    finally:
        db.close()
