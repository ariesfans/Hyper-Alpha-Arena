from sqlalchemy import Column, Integer, BigInteger, String, DECIMAL, TIMESTAMP, ForeignKey, UniqueConstraint, Float, Date, DateTime, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import datetime

from .connection import Base


class User(Base):
    """
    User for authentication and account management
    In this project, use the default user, no user login
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), nullable=True)
    password_hash = Column(String(255), nullable=True)  # For future password authentication
    is_active = Column(String(10), nullable=False, default="true")
    
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    # Relationships
    accounts = relationship("Account", back_populates="user")
    auth_sessions = relationship("UserAuthSession", back_populates="user")
    subscription = relationship("UserSubscription", back_populates="user", uselist=False)


class Account(Base):
    """Trading Account with AI model configuration"""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    version = Column(String(100), nullable=False, default="v1")
    
    # Account Identity
    name = Column(String(100), nullable=False)  # Display name (e.g., "GPT Trader", "Claude Analyst")
    account_type = Column(String(20), nullable=False, default="AI")  # "AI" or "MANUAL"
    is_active = Column(String(10), nullable=False, default="true")
    auto_trading_enabled = Column(String(10), nullable=False, default="true")
    
    # AI Model Configuration (for AI accounts)
    model = Column(String(100), nullable=True, default="gpt-4")  # AI model name
    base_url = Column(String(500), nullable=True, default="https://api.openai.com/v1")  # API endpoint
    api_key = Column(String(500), nullable=True)  # API key for authentication
    
    # Trading Account Balances (USD for CRYPTO market)
    initial_capital = Column(DECIMAL(18, 2), nullable=False, default=10000.00)
    current_cash = Column(DECIMAL(18, 2), nullable=False, default=10000.00)
    frozen_cash = Column(DECIMAL(18, 2), nullable=False, default=0.00)

    # Hyperliquid Trading Configuration
    hyperliquid_enabled = Column(String(10), nullable=False, default="false")
    hyperliquid_environment = Column(String(20), nullable=True)  # "testnet" | "mainnet" | null
    hyperliquid_testnet_private_key = Column(String(500), nullable=True)  # Encrypted storage
    hyperliquid_mainnet_private_key = Column(String(500), nullable=True)  # Encrypted storage
    max_leverage = Column(Integer, nullable=True, default=3)  # Maximum allowed leverage
    default_leverage = Column(Integer, nullable=True, default=1)  # Default leverage for orders

    # Dashboard visibility
    show_on_dashboard = Column(Boolean, nullable=False, default=True)  # Show/hide on Dashboard views

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    # Relationships
    user = relationship("User", back_populates="accounts")
    positions = relationship("Position", back_populates="account")
    orders = relationship("Order", back_populates="account")
    prompt_binding = relationship(
        "AccountPromptBinding",
        back_populates="account",
        uselist=False,
        cascade="all, delete-orphan",
    )


class UserAuthSession(Base):
    __tablename__ = "user_auth_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_token = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    
    user = relationship("User", back_populates="auth_sessions")


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(String(100), nullable=False, default="v1")
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    symbol = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    market = Column(String(10), nullable=False)
    quantity = Column(DECIMAL(18, 8), nullable=False, default=0)  # Support fractional crypto amounts
    available_quantity = Column(DECIMAL(18, 8), nullable=False, default=0)
    avg_cost = Column(DECIMAL(18, 6), nullable=False, default=0)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    account = relationship("Account", back_populates="positions")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(String(100), nullable=False, default="v1")
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    order_no = Column(String(32), unique=True, nullable=False)
    symbol = Column(String(20), nullable=False)  # e.g., 'BTC/USD'
    name = Column(String(100), nullable=False)   # e.g., 'Bitcoin'
    market = Column(String(10), nullable=False, default="CRYPTO")
    side = Column(String(10), nullable=False)
    order_type = Column(String(20), nullable=False)
    price = Column(DECIMAL(18, 6))
    quantity = Column(DECIMAL(18, 8), nullable=False)  # Support fractional crypto amounts
    filled_quantity = Column(DECIMAL(18, 8), nullable=False, default=0)
    status = Column(String(20), nullable=False)

    # Hyperliquid specific fields
    hyperliquid_environment = Column(String(20), nullable=True)  # "testnet" | "mainnet" | null
    leverage = Column(Integer, nullable=True, default=1)  # Position leverage (1-50)
    margin_mode = Column(String(20), nullable=True, default="cross")  # "cross" or "isolated"
    reduce_only = Column(String(10), nullable=True, default="false")  # Only close positions
    hyperliquid_order_id = Column(String(50), nullable=True)  # OID from Hyperliquid API
    liquidation_price = Column(DECIMAL(18, 6), nullable=True)  # Liquidation price for position

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    account = relationship("Account", back_populates="orders")
    trades = relationship("Trade", back_populates="order")


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    symbol = Column(String(20), nullable=False)  # e.g., 'BTC/USD'
    name = Column(String(100), nullable=False)   # e.g., 'Bitcoin'
    market = Column(String(10), nullable=False, default="CRYPTO")
    side = Column(String(10), nullable=False)
    price = Column(DECIMAL(18, 6), nullable=False)
    quantity = Column(DECIMAL(18, 8), nullable=False)  # Support fractional crypto amounts
    commission = Column(DECIMAL(18, 6), nullable=False, default=0)
    trade_time = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Hyperliquid environment tracking
    hyperliquid_environment = Column(String(20), nullable=True)  # "testnet" | "mainnet" | null (paper)

    order = relationship("Order", back_populates="trades")


class TradingConfig(Base):
    __tablename__ = "trading_configs"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(String(100), nullable=False, default="v1")
    market = Column(String(10), nullable=False)
    min_commission = Column(Float, nullable=False)
    commission_rate = Column(Float, nullable=False)
    exchange_rate = Column(Float, nullable=False, default=1.0)
    min_order_quantity = Column(Integer, nullable=False, default=1)
    lot_size = Column(Integer, nullable=False, default=1)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    __table_args__ = (UniqueConstraint('market', 'version'),)


class SystemConfig(Base):
    __tablename__ = "system_configs"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    description = Column(String(500), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )


class CryptoPrice(Base):
    __tablename__ = "crypto_prices"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    market = Column(String(10), nullable=False, default="CRYPTO")
    price = Column(DECIMAL(18, 6), nullable=False)
    price_date = Column(Date, nullable=False, index=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    __table_args__ = (UniqueConstraint('symbol', 'market', 'price_date'),)


class CryptoKline(Base):
    __tablename__ = "crypto_klines"

    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String(20), nullable=False, default="hyperliquid", index=True)
    symbol = Column(String(20), nullable=False, index=True)
    market = Column(String(10), nullable=False, default="CRYPTO")
    period = Column(String(10), nullable=False)  # 1m, 5m, 15m, 30m, 1h, 1d
    timestamp = Column(Integer, nullable=False, index=True)
    datetime_str = Column(String(50), nullable=False)
    environment = Column(String(20), nullable=False, default="mainnet", index=True)  # testnet or mainnet
    open_price = Column(DECIMAL(18, 6), nullable=True)
    high_price = Column(DECIMAL(18, 6), nullable=True)
    low_price = Column(DECIMAL(18, 6), nullable=True)
    close_price = Column(DECIMAL(18, 6), nullable=True)
    volume = Column(DECIMAL(18, 2), nullable=True)
    amount = Column(DECIMAL(18, 2), nullable=True)
    change = Column(DECIMAL(18, 6), nullable=True)
    percent = Column(DECIMAL(10, 4), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    __table_args__ = (UniqueConstraint('exchange', 'symbol', 'market', 'period', 'timestamp', 'environment'),)


class CryptoPriceTick(Base):
    __tablename__ = "crypto_price_ticks"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    market = Column(String(10), nullable=False, default="CRYPTO")
    price = Column(DECIMAL(18, 8), nullable=False)
    event_time = Column(TIMESTAMP, nullable=False, index=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())


class AccountAssetSnapshot(Base):
    __tablename__ = "account_asset_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    total_assets = Column(DECIMAL(18, 6), nullable=False)
    cash = Column(DECIMAL(18, 6), nullable=False)
    positions_value = Column(DECIMAL(18, 6), nullable=False)
    trigger_symbol = Column(String(20), nullable=True)
    trigger_market = Column(String(10), nullable=True, default="CRYPTO")
    event_time = Column(TIMESTAMP, nullable=False, index=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)

    account = relationship("Account")


class AccountStrategyConfig(Base):
    __tablename__ = "account_strategy_configs"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, unique=True)
    price_threshold = Column(Float, nullable=False, default=1.0)  # Deprecated, kept for compatibility
    trigger_interval = Column(Integer, nullable=False, default=150)  # Trigger interval (seconds)
    # Note: Foreign key constraint exists at DB level (via migration), but not in ORM
    # because signal_pools table is managed via raw SQL, not SQLAlchemy models
    signal_pool_id = Column(Integer, nullable=True)  # Deprecated: use signal_pool_ids instead
    signal_pool_ids = Column(Text, nullable=True)  # JSON array of signal pool IDs, e.g. "[1, 2, 3]"
    enabled = Column(String(10), nullable=False, default="true")
    scheduled_trigger_enabled = Column(Boolean, nullable=False, default=True)  # Enable/disable scheduled trigger
    last_trigger_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    account = relationship("Account")


class GlobalSamplingConfig(Base):
    __tablename__ = "global_sampling_configs"

    id = Column(Integer, primary_key=True, index=True)
    sampling_interval = Column(Integer, nullable=False, default=18)  # Sampling interval (seconds)
    sampling_depth = Column(Integer, nullable=False, default=10)  # Sampling pool depth (10-60)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )


class UserSubscription(Base):
    """User subscription for premium features"""
    __tablename__ = "user_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    subscription_type = Column(String(20), nullable=False, default="free")  # "free" | "premium"
    expires_at = Column(TIMESTAMP, nullable=True)  # NULL for free tier or lifetime premium
    max_sampling_depth = Column(Integer, nullable=False, default=10)  # Free: 10, Premium: up to 60
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    # Relationship
    user = relationship("User", back_populates="subscription")


class AIDecisionLog(Base):
    __tablename__ = "ai_decision_logs"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    decision_time = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)
    reason = Column(String(1000), nullable=False)  # AI reasoning for the decision
    operation = Column(String(10), nullable=False)  # buy/sell/hold
    symbol = Column(String(20), nullable=True)  # symbol for buy/sell operations
    prev_portion = Column(DECIMAL(10, 6), nullable=False, default=0)  # previous balance portion
    target_portion = Column(DECIMAL(10, 6), nullable=False)  # target balance portion
    total_balance = Column(DECIMAL(18, 2), nullable=False)  # total balance at decision time
    executed = Column(String(10), nullable=False, default="false")  # whether the decision was executed
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)  # linked order if executed
    prompt_snapshot = Column(Text, nullable=True)
    reasoning_snapshot = Column(Text, nullable=True)
    decision_snapshot = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Hyperliquid environment tracking
    hyperliquid_environment = Column(String(20), nullable=True)  # "testnet" | "mainnet" | null (paper)
    wallet_address = Column(String(100), nullable=True, index=True)

    # Decision tracking fields for analysis
    prompt_template_id = Column(Integer, nullable=True, index=True)  # Link to strategy/prompt template
    signal_trigger_id = Column(Integer, nullable=True, index=True)  # Link to signal trigger
    hyperliquid_order_id = Column(String(100), nullable=True, index=True)  # Main order ID from Hyperliquid
    tp_order_id = Column(String(100), nullable=True)  # Take profit order ID
    sl_order_id = Column(String(100), nullable=True)  # Stop loss order ID
    realized_pnl = Column(DECIMAL(18, 6), nullable=True)  # Realized PnL (filled on user refresh)
    pnl_updated_at = Column(TIMESTAMP, nullable=True)  # When PnL was last updated

    # Relationships
    account = relationship("Account")
    order = relationship("Order")


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), nullable=False, index=True)  # Removed unique constraint to allow copies
    name = Column(String(200), nullable=False)
    description = Column(String(500), nullable=True)
    template_text = Column(Text, nullable=False)
    system_template_text = Column(Text, nullable=False)

    # User-level template support
    is_system = Column(String(10), nullable=False, default="false")  # System templates cannot be deleted
    is_deleted = Column(String(10), nullable=False, default="false")  # Soft delete
    created_by = Column(String(100), nullable=False, default="system")  # Creator identifier

    updated_by = Column(String(100), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    account_bindings = relationship(
        "AccountPromptBinding",
        back_populates="prompt_template",
        cascade="all, delete-orphan",
    )


class AccountPromptBinding(Base):
    __tablename__ = "account_prompt_bindings"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, unique=True)
    prompt_template_id = Column(Integer, ForeignKey("prompt_templates.id"), nullable=False)
    updated_by = Column(String(100), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    account = relationship("Account", back_populates="prompt_binding")
    prompt_template = relationship("PromptTemplate", back_populates="account_bindings")


class HyperliquidWallet(Base):
    """Store Hyperliquid wallet configurations per AI Trader per environment

    One-to-many relationship with Account. Each AI Trader can have multiple wallets
    (one for testnet, one for mainnet).
    """
    __tablename__ = "hyperliquid_wallets"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)

    # Environment (testnet or mainnet)
    environment = Column(String(20), nullable=False)  # 'testnet' or 'mainnet'

    # Wallet credentials (encrypted)
    private_key_encrypted = Column(String(500), nullable=False)
    wallet_address = Column(String(100), nullable=False, index=True)  # Parsed from private key

    # Trading configuration
    max_leverage = Column(Integer, nullable=False, default=3)  # Maximum allowed leverage (1-50)
    default_leverage = Column(Integer, nullable=False, default=1)  # Default leverage for new orders

    # Status
    is_active = Column(String(10), nullable=False, default="true")

    # Metadata
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    # Unique constraint: one wallet per account per environment
    __table_args__ = (
        UniqueConstraint('account_id', 'environment', name='uq_hyperliquid_wallets_account_environment'),
    )

    # Relationships
    account = relationship("Account")


class HyperliquidAccountSnapshot(Base):
    """Store Hyperliquid account state snapshots for audit and analysis"""
    __tablename__ = "hyperliquid_account_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    environment = Column(String(20), nullable=False, index=True)  # "testnet" | "mainnet"
    wallet_address = Column(String(100), nullable=True, index=True)
    snapshot_time = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)

    # Account state
    total_equity = Column(DECIMAL(18, 6), nullable=False)
    available_balance = Column(DECIMAL(18, 6), nullable=False)
    used_margin = Column(DECIMAL(18, 6), nullable=False)
    maintenance_margin = Column(DECIMAL(18, 6), nullable=False)

    # Snapshot metadata
    trigger_event = Column(String(50), nullable=True)  # "pre_decision", "post_order", etc.
    snapshot_data = Column(Text, nullable=True)  # JSON of full API response

    account = relationship("Account")


class HyperliquidPosition(Base):
    """Store Hyperliquid position snapshots"""
    __tablename__ = "hyperliquid_positions"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    environment = Column(String(20), nullable=False, index=True)  # "testnet" | "mainnet"
    wallet_address = Column(String(100), nullable=True, index=True)
    snapshot_time = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)

    symbol = Column(String(20), nullable=False)
    position_size = Column(DECIMAL(18, 8), nullable=False)  # Signed: positive=long, negative=short
    entry_price = Column(DECIMAL(18, 6), nullable=False)
    current_price = Column(DECIMAL(18, 6), nullable=False)
    position_value = Column(DECIMAL(18, 6), nullable=False)
    unrealized_pnl = Column(DECIMAL(18, 6), nullable=False)
    margin_used = Column(DECIMAL(18, 6), nullable=False)
    liquidation_price = Column(DECIMAL(18, 6), nullable=True)
    leverage = Column(Integer, nullable=False)

    # Link to order that created/modified this position
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)

    account = relationship("Account")
    order = relationship("Order")


class HyperliquidExchangeAction(Base):
    """Track every POST /exchange action for Hyperliquid accounts"""
    __tablename__ = "hyperliquid_exchange_actions"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    environment = Column(String(20), nullable=False, index=True)
    wallet_address = Column(String(100), nullable=False, index=True)
    action_type = Column(String(50), nullable=False)  # e.g., create_order, set_leverage
    status = Column(String(20), nullable=False, default="success")  # success | error
    symbol = Column(String(20), nullable=True)
    side = Column(String(10), nullable=True)
    leverage = Column(Integer, nullable=True)
    size = Column(DECIMAL(24, 12), nullable=True)
    price = Column(DECIMAL(18, 6), nullable=True)
    notional = Column(DECIMAL(26, 10), nullable=True)
    request_weight = Column(Integer, nullable=False, default=1)
    request_payload = Column(Text, nullable=True)
    response_payload = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)

    account = relationship("Account")


class PerpFunding(Base):
    """Store perpetual contract funding rate data from multiple exchanges"""
    __tablename__ = "perp_funding"

    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timestamp = Column(Integer, nullable=False, index=True)
    funding_rate = Column(DECIMAL(18, 8), nullable=False)
    mark_price = Column(DECIMAL(18, 6), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    __table_args__ = (UniqueConstraint('exchange', 'symbol', 'timestamp'),)


class PriceSample(Base):
    """Store price sampling data for persistent sampling pools"""
    __tablename__ = "price_samples"

    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    price = Column(DECIMAL(18, 8), nullable=False)
    sample_time = Column(TIMESTAMP, nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    account = relationship("Account")


class UserExchangeConfig(Base):
    """Store user exchange selection preferences"""
    __tablename__ = "user_exchange_config"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    selected_exchange = Column(String(20), nullable=False, default="hyperliquid")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    # Relationships
    user = relationship("User")


class KlineCollectionTask(Base):
    """Store K-line data collection task status"""
    __tablename__ = "kline_collection_tasks"

    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String(20), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    start_time = Column(TIMESTAMP, nullable=False)
    end_time = Column(TIMESTAMP, nullable=False)
    period = Column(String(10), nullable=False, default="1m")
    status = Column(String(20), nullable=False, default="pending", index=True)
    progress = Column(Integer, nullable=False, default=0)
    total_records = Column(Integer, default=0)
    collected_records = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )


class KlineAIAnalysisLog(Base):
    """Store K-line AI analysis logs for chart insights"""
    __tablename__ = "kline_ai_analysis_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)

    # Analysis context
    symbol = Column(String(20), nullable=False, index=True)
    period = Column(String(10), nullable=False)  # K-line period (1m, 5m, 1h, etc.)
    user_message = Column(Text, nullable=True)  # User's custom question

    # AI model info
    model_used = Column(String(100), nullable=False)

    # Snapshots
    prompt_snapshot = Column(Text, nullable=True)  # Full prompt sent to AI
    analysis_result = Column(Text, nullable=True)  # AI's analysis response (Markdown)

    # Metadata
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)

    # Relationships
    user = relationship("User")
    account = relationship("Account")


class AiPromptConversation(Base):
    """AI Prompt Generation Conversation Sessions"""
    __tablename__ = "ai_prompt_conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False, default="New Strategy Prompt")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    # Relationships
    user = relationship("User")
    messages = relationship(
        "AiPromptMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AiPromptMessage.created_at"
    )


class AiPromptMessage(Base):
    """Messages in AI Prompt Generation Conversations"""
    __tablename__ = "ai_prompt_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("ai_prompt_conversations.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)  # Message content (markdown)

    # For assistant messages: extracted prompt from ```prompt``` code block
    prompt_result = Column(Text, nullable=True)

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)

    # Relationships
    conversation = relationship("AiPromptConversation", back_populates="messages")


class AiSignalConversation(Base):
    """AI Signal Creation Conversation Sessions"""
    __tablename__ = "ai_signal_conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False, default="New Signal")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    # Relationships
    user = relationship("User")
    messages = relationship(
        "AiSignalMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AiSignalMessage.created_at"
    )


class AiSignalMessage(Base):
    """Messages in AI Signal Creation Conversations"""
    __tablename__ = "ai_signal_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("ai_signal_conversations.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)  # Message content (markdown)

    # For assistant messages: extracted signal configs from ```signal-config``` code blocks
    signal_configs = Column(Text, nullable=True)  # JSON array of signal configurations

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)

    # Relationships
    conversation = relationship("AiSignalConversation", back_populates="messages")


class AiAttributionConversation(Base):
    """AI Attribution Analysis Conversation Sessions"""
    __tablename__ = "ai_attribution_conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False, default="New Analysis")
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)
    updated_at = Column(
        TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )

    # Relationships
    user = relationship("User")
    messages = relationship(
        "AiAttributionMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AiAttributionMessage.created_at"
    )


class AiAttributionMessage(Base):
    """Messages in AI Attribution Analysis Conversations"""
    __tablename__ = "ai_attribution_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("ai_attribution_conversations.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)  # Message content (markdown)

    # For assistant messages: extracted diagnosis results from AI analysis
    diagnosis_result = Column(Text, nullable=True)  # JSON: diagnosis cards and prompt suggestions

    # Reasoning and analysis process storage (like AIDecisionLog.reasoning_snapshot)
    reasoning_snapshot = Column(Text, nullable=True)  # AI reasoning process
    analysis_log = Column(Text, nullable=True)  # JSON: tool calls and results log

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)

    # Relationships
    conversation = relationship("AiAttributionConversation", back_populates="messages")


# ============================================================================
# Market Flow Data Tables (for fund flow analysis)
# ============================================================================

class MarketTradesAggregated(Base):
    """15-second aggregated trade data for CVD and Taker Volume analysis"""
    __tablename__ = "market_trades_aggregated"

    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String(20), nullable=False, default="hyperliquid", index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timestamp = Column(BigInteger, nullable=False, index=True)  # milliseconds
    taker_buy_volume = Column(DECIMAL(24, 8), nullable=False, default=0)
    taker_sell_volume = Column(DECIMAL(24, 8), nullable=False, default=0)
    taker_buy_count = Column(Integer, nullable=False, default=0)
    taker_sell_count = Column(Integer, nullable=False, default=0)
    taker_buy_notional = Column(DECIMAL(24, 6), nullable=False, default=0)
    taker_sell_notional = Column(DECIMAL(24, 6), nullable=False, default=0)
    vwap = Column(DECIMAL(18, 6), nullable=True)
    high_price = Column(DECIMAL(18, 6), nullable=True)
    low_price = Column(DECIMAL(18, 6), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    __table_args__ = (
        UniqueConstraint('exchange', 'symbol', 'timestamp',
                         name='market_trades_aggregated_exchange_symbol_timestamp_key'),
    )


class MarketOrderbookSnapshots(Base):
    """Order book snapshots for depth ratio and liquidity analysis"""
    __tablename__ = "market_orderbook_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String(20), nullable=False, default="hyperliquid", index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timestamp = Column(BigInteger, nullable=False, index=True)  # milliseconds
    best_bid = Column(DECIMAL(18, 6), nullable=True)
    best_ask = Column(DECIMAL(18, 6), nullable=True)
    spread = Column(DECIMAL(18, 6), nullable=True)
    bid_depth_5 = Column(DECIMAL(24, 8), nullable=False, default=0)
    ask_depth_5 = Column(DECIMAL(24, 8), nullable=False, default=0)
    bid_depth_10 = Column(DECIMAL(24, 8), nullable=False, default=0)
    ask_depth_10 = Column(DECIMAL(24, 8), nullable=False, default=0)
    bid_orders_count = Column(Integer, nullable=False, default=0)
    ask_orders_count = Column(Integer, nullable=False, default=0)
    raw_levels = Column(Text, nullable=True)  # JSON string of full orderbook
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    __table_args__ = (
        UniqueConstraint('exchange', 'symbol', 'timestamp',
                         name='market_orderbook_snapshots_exchange_symbol_timestamp_key'),
    )


class MarketAssetMetrics(Base):
    """Asset metrics snapshots for OI, Funding Rate, and Premium analysis"""
    __tablename__ = "market_asset_metrics"

    id = Column(Integer, primary_key=True, index=True)
    exchange = Column(String(20), nullable=False, default="hyperliquid", index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timestamp = Column(BigInteger, nullable=False, index=True)  # milliseconds
    open_interest = Column(DECIMAL(24, 8), nullable=True)
    funding_rate = Column(DECIMAL(18, 8), nullable=True)
    mark_price = Column(DECIMAL(18, 6), nullable=True)
    oracle_price = Column(DECIMAL(18, 6), nullable=True)
    mid_price = Column(DECIMAL(18, 6), nullable=True)
    premium = Column(DECIMAL(18, 8), nullable=True)
    day_notional_volume = Column(DECIMAL(24, 6), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    __table_args__ = (
        UniqueConstraint('exchange', 'symbol', 'timestamp',
                         name='market_asset_metrics_exchange_symbol_timestamp_key'),
    )


# ============================================================================
# Signal System Tables (for signal-based trading triggers)
# ============================================================================

class SignalDefinition(Base):
    """Signal definitions for market condition triggers"""
    __tablename__ = "signal_definitions"

    id = Column(Integer, primary_key=True, index=True)
    signal_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    trigger_condition = Column(Text, nullable=False)  # JSONB stored as text
    enabled = Column(Boolean, nullable=True, default=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp())


class SignalPool(Base):
    """Signal pools for grouping multiple signals"""
    __tablename__ = "signal_pools"

    id = Column(Integer, primary_key=True, index=True)
    pool_name = Column(String(100), nullable=False)
    signal_ids = Column(Text, nullable=False, default="[]")  # JSONB stored as text
    symbols = Column(Text, nullable=False, default="[]")  # JSONB stored as text
    logic = Column(String(10), nullable=True, default="OR")  # AND/OR logic
    enabled = Column(Boolean, nullable=True, default=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())


class SignalTriggerLog(Base):
    """Logs of signal triggers for audit and analysis"""
    __tablename__ = "signal_trigger_logs"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, nullable=True)
    pool_id = Column(Integer, nullable=True)
    symbol = Column(String(20), nullable=False)
    trigger_value = Column(Text, nullable=True)  # JSONB stored as text
    triggered_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    market_regime = Column(Text, nullable=True)  # JSON: {"regime", "direction", "confidence", "reason"}


class TraderTriggerConfig(Base):
    """Configuration for trader trigger settings"""
    __tablename__ = "trader_trigger_config"

    trader_id = Column(String(36), primary_key=True)  # UUID as string
    scheduled_enabled = Column(Boolean, nullable=True, default=True)
    scheduled_interval = Column(Integer, nullable=True, default=30)
    signal_pool_id = Column(Integer, nullable=True)  # Deprecated: use signal_pool_ids instead
    signal_pool_ids = Column(Text, nullable=True)  # JSON array of signal pool IDs, e.g. "[1, 2, 3]"
    last_trigger_time = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp())


class MarketRegimeConfig(Base):
    """Configuration for Market Regime classification thresholds"""
    __tablename__ = "market_regime_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    is_default = Column(Boolean, nullable=True, default=False)
    rolling_window = Column(Integer, nullable=True, default=48)
    # Breakout thresholds
    breakout_cvd_z = Column(Float, nullable=True, default=1.5)
    breakout_oi_z = Column(Float, nullable=True, default=1.0)
    breakout_price_atr = Column(Float, nullable=True, default=0.5)
    breakout_taker_high = Column(Float, nullable=True, default=1.8)
    breakout_taker_low = Column(Float, nullable=True, default=0.55)
    # Absorption thresholds
    absorption_cvd_z = Column(Float, nullable=True, default=1.5)
    absorption_price_atr = Column(Float, nullable=True, default=0.3)
    # Trap thresholds
    trap_cvd_z = Column(Float, nullable=True, default=1.0)
    trap_oi_z = Column(Float, nullable=True, default=-1.0)
    # Exhaustion thresholds
    exhaustion_cvd_z = Column(Float, nullable=True, default=1.0)
    exhaustion_rsi_high = Column(Float, nullable=True, default=70.0)
    exhaustion_rsi_low = Column(Float, nullable=True, default=30.0)
    # Stop Hunt thresholds
    stop_hunt_range_atr = Column(Float, nullable=True, default=1.0)
    stop_hunt_close_atr = Column(Float, nullable=True, default=0.3)
    # Noise thresholds
    noise_cvd_z = Column(Float, nullable=True, default=0.5)
    # Timestamps
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp())


# ============================================================================
# Prompt Backtest Tables
# ============================================================================

class PromptBacktestTask(Base):
    """Prompt backtest task - batch test prompt modifications against historical decisions"""
    __tablename__ = "prompt_backtest_tasks"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    wallet_address = Column(String(100), nullable=True, index=True)
    environment = Column(String(20), nullable=True)  # testnet/mainnet
    name = Column(String(200), nullable=True)  # User-defined task name
    status = Column(String(20), nullable=False, default="pending")  # pending/running/completed/failed
    total_count = Column(Integer, nullable=False, default=0)
    completed_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    replace_rules = Column(Text, nullable=True)  # JSON: replacement rules used
    started_at = Column(TIMESTAMP, nullable=True)
    finished_at = Column(TIMESTAMP, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp())

    # Relationships
    account = relationship("Account")
    items = relationship("PromptBacktestItem", back_populates="task", cascade="all, delete-orphan")


class PromptBacktestItem(Base):
    """Individual item in a prompt backtest task"""
    __tablename__ = "prompt_backtest_items"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("prompt_backtest_tasks.id"), nullable=False, index=True)
    original_decision_log_id = Column(Integer, ForeignKey("ai_decision_logs.id"), nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # pending/running/completed/failed
    error_message = Column(Text, nullable=True)

    # Original data snapshot
    original_operation = Column(String(20), nullable=True)
    original_symbol = Column(String(20), nullable=True)
    original_target_portion = Column(DECIMAL(10, 6), nullable=True)
    original_reasoning = Column(Text, nullable=True)
    original_decision_json = Column(Text, nullable=True)
    original_realized_pnl = Column(DECIMAL(18, 6), nullable=True)
    original_decision_time = Column(TIMESTAMP, nullable=True)
    original_prompt_template_name = Column(String(200), nullable=True)

    # Modified prompt (cache)
    modified_prompt = Column(Text, nullable=True)

    # New decision results
    new_operation = Column(String(20), nullable=True)
    new_symbol = Column(String(20), nullable=True)
    new_target_portion = Column(DECIMAL(10, 6), nullable=True)
    new_reasoning = Column(Text, nullable=True)
    new_decision_json = Column(Text, nullable=True)

    # Derived fields
    decision_changed = Column(Boolean, nullable=True)
    change_type = Column(String(50), nullable=True)  # e.g., buy_to_hold
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    # Relationships
    task = relationship("PromptBacktestTask", back_populates="items")
    original_decision_log = relationship("AIDecisionLog")


# ============================================================================
# CRYPTO market trading configuration constants
# ============================================================================
CRYPTO_MIN_COMMISSION = 0.1  # $0.1 minimum commission
CRYPTO_COMMISSION_RATE = 0.001  # 0.1% commission rate
CRYPTO_MIN_ORDER_QUANTITY = 1
CRYPTO_LOT_SIZE = 1
