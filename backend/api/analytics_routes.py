"""
Strategy Analytics API routes.
Provides multi-dimensional analysis of trading decisions and performance.
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, case, and_, or_
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import AIDecisionLog, Account, PromptTemplate
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============== Pydantic Models ==============

class MetricsResponse(BaseModel):
    total_pnl: float
    total_fee: float
    net_pnl: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float
    avg_win: Optional[float]
    avg_loss: Optional[float]
    profit_factor: Optional[float]


class DataCompleteness(BaseModel):
    total_decisions: int
    with_strategy: int
    with_signal: int
    with_pnl: int


class TriggerTypeBreakdown(BaseModel):
    count: int
    net_pnl: float


# ============== Helper Functions ==============

def calculate_metrics(records: List[Dict]) -> Dict[str, Any]:
    """Calculate standard metrics from a list of decision records."""
    if not records:
        return {
            "total_pnl": 0.0,
            "total_fee": 0.0,
            "net_pnl": 0.0,
            "trade_count": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
            "avg_win": None,
            "avg_loss": None,
            "profit_factor": None,
        }

    total_pnl = sum(r.get("pnl", 0) or 0 for r in records)
    total_fee = sum(r.get("fee", 0) or 0 for r in records)
    net_pnl = total_pnl - total_fee

    wins = [r for r in records if (r.get("pnl") or 0) > 0]
    losses = [r for r in records if (r.get("pnl") or 0) < 0]

    win_count = len(wins)
    loss_count = len(losses)
    trade_count = len(records)
    win_rate = win_count / trade_count if trade_count > 0 else 0.0

    total_win = sum(r.get("pnl", 0) or 0 for r in wins)
    total_loss = abs(sum(r.get("pnl", 0) or 0 for r in losses))

    avg_win = total_win / win_count if win_count > 0 else None
    avg_loss = -total_loss / loss_count if loss_count > 0 else None
    profit_factor = total_win / total_loss if total_loss > 0 else None

    return {
        "total_pnl": round(total_pnl, 2),
        "total_fee": round(total_fee, 2),
        "net_pnl": round(net_pnl, 2),
        "trade_count": trade_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 2) if avg_win else None,
        "avg_loss": round(avg_loss, 2) if avg_loss else None,
        "profit_factor": round(profit_factor, 2) if profit_factor else None,
    }


def get_trigger_type(decision: AIDecisionLog) -> str:
    """Determine trigger type for a decision."""
    if decision.signal_trigger_id is not None:
        return "signal"
    elif decision.executed == "true" and decision.operation in ("buy", "sell", "close"):
        return "scheduled"
    return "unknown"


def build_base_query(
    db: Session,
    start_date: Optional[date],
    end_date: Optional[date],
    environment: Optional[str],
    account_id: Optional[int],
):
    """Build base query with common filters.

    Only includes decisions with non-zero realized_pnl (i.e., actually closed positions).
    This ensures statistics only count trades that have settled PnL,
    excluding opening trades (pnl=0) and unsync trades (pnl=NULL).
    """
    query = db.query(AIDecisionLog).filter(
        AIDecisionLog.operation.in_(["buy", "sell", "close"]),
        AIDecisionLog.executed == "true",
        AIDecisionLog.realized_pnl.isnot(None),  # Exclude unsync trades
        AIDecisionLog.realized_pnl != 0,  # Exclude opening trades (no settled PnL)
    )

    if start_date:
        query = query.filter(AIDecisionLog.decision_time >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(AIDecisionLog.decision_time <= datetime.combine(end_date, datetime.max.time()))
    if environment and environment != "all":
        query = query.filter(AIDecisionLog.hyperliquid_environment == environment)
    if account_id:
        query = query.filter(AIDecisionLog.account_id == account_id)

    return query


# ============== API Endpoints ==============

@router.get("/summary")
def get_analytics_summary(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Get overall analytics summary."""
    query = build_base_query(db, start_date, end_date, environment, account_id)
    decisions = query.all()

    # Convert to records for metrics calculation
    records = []
    signal_records = []
    scheduled_records = []
    unknown_records = []

    with_strategy = 0
    with_signal = 0
    with_pnl = 0

    for d in decisions:
        pnl = float(d.realized_pnl) if d.realized_pnl else 0
        fee = 0  # Fee is in HyperliquidTrade, not AIDecisionLog
        record = {"pnl": pnl, "fee": fee}
        records.append(record)

        trigger_type = get_trigger_type(d)
        if trigger_type == "signal":
            signal_records.append(record)
        elif trigger_type == "scheduled":
            scheduled_records.append(record)
        else:
            unknown_records.append(record)

        if d.prompt_template_id:
            with_strategy += 1
        if d.signal_trigger_id:
            with_signal += 1
        if d.realized_pnl:
            with_pnl += 1

    overview = calculate_metrics(records)

    return {
        "period": {
            "start": start_date.isoformat() if start_date else None,
            "end": end_date.isoformat() if end_date else None,
        },
        "overview": overview,
        "data_completeness": {
            "total_decisions": len(decisions),
            "with_strategy": with_strategy,
            "with_signal": with_signal,
            "with_pnl": with_pnl,
        },
        "by_trigger_type": {
            "signal": {
                "count": len(signal_records),
                "net_pnl": round(sum(r["pnl"] - r["fee"] for r in signal_records), 2),
            },
            "scheduled": {
                "count": len(scheduled_records),
                "net_pnl": round(sum(r["pnl"] - r["fee"] for r in scheduled_records), 2),
            },
            "unknown": {
                "count": len(unknown_records),
                "net_pnl": round(sum(r["pnl"] - r["fee"] for r in unknown_records), 2),
            },
        },
    }


@router.get("/by-strategy")
def get_analytics_by_strategy(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Get analytics grouped by strategy (prompt template)."""
    query = build_base_query(db, start_date, end_date, environment, account_id)
    decisions = query.all()

    # Group by strategy
    by_strategy: Dict[Optional[int], List[Dict]] = {}
    strategy_names: Dict[int, str] = {}

    for d in decisions:
        strategy_id = d.prompt_template_id
        pnl = float(d.realized_pnl) if d.realized_pnl else 0
        record = {
            "pnl": pnl,
            "fee": 0,
            "trigger_type": get_trigger_type(d),
        }

        if strategy_id not in by_strategy:
            by_strategy[strategy_id] = []
        by_strategy[strategy_id].append(record)

    # Get strategy names
    strategy_ids = [sid for sid in by_strategy.keys() if sid is not None]
    if strategy_ids:
        templates = db.query(PromptTemplate).filter(PromptTemplate.id.in_(strategy_ids)).all()
        strategy_names = {t.id: t.name for t in templates}

    # Build response
    items = []
    for strategy_id, records in by_strategy.items():
        if strategy_id is None:
            continue

        signal_records = [r for r in records if r["trigger_type"] == "signal"]
        scheduled_records = [r for r in records if r["trigger_type"] == "scheduled"]

        items.append({
            "strategy_id": strategy_id,
            "strategy_name": strategy_names.get(strategy_id, f"Strategy {strategy_id}"),
            "metrics": calculate_metrics(records),
            "by_trigger_type": {
                "signal": {"count": len(signal_records), "net_pnl": round(sum(r["pnl"] for r in signal_records), 2)},
                "scheduled": {"count": len(scheduled_records), "net_pnl": round(sum(r["pnl"] for r in scheduled_records), 2)},
            },
        })

    # Sort by net_pnl descending
    items.sort(key=lambda x: x["metrics"]["net_pnl"], reverse=True)

    # Unattributed (no strategy)
    unattributed_records = by_strategy.get(None, [])

    return {
        "items": items,
        "unattributed": {
            "count": len(unattributed_records),
            "metrics": calculate_metrics(unattributed_records) if unattributed_records else None,
        },
    }


@router.get("/by-account")
def get_analytics_by_account(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    db: Session = Depends(get_db),
):
    """Get analytics grouped by account."""
    query = build_base_query(db, start_date, end_date, environment, None)
    decisions = query.all()

    # Group by account
    by_account: Dict[Optional[int], List[Dict]] = {}

    for d in decisions:
        account_id = d.account_id
        pnl = float(d.realized_pnl) if d.realized_pnl else 0
        record = {"pnl": pnl, "fee": 0, "trigger_type": get_trigger_type(d)}

        if account_id not in by_account:
            by_account[account_id] = []
        by_account[account_id].append(record)

    # Get account info (name, current model)
    account_ids = [aid for aid in by_account.keys() if aid is not None]
    account_info: Dict[int, Dict] = {}
    if account_ids:
        accounts = db.query(Account).filter(Account.id.in_(account_ids)).all()
        account_info = {
            a.id: {"name": a.name, "model": a.model, "environment": a.hyperliquid_environment}
            for a in accounts
        }

    # Build response
    items = []
    for account_id, records in by_account.items():
        if account_id is None:
            continue

        info = account_info.get(account_id, {})
        signal_records = [r for r in records if r["trigger_type"] == "signal"]
        scheduled_records = [r for r in records if r["trigger_type"] == "scheduled"]

        items.append({
            "account_id": account_id,
            "account_name": info.get("name", f"Account {account_id}"),
            "model": info.get("model"),
            "environment": info.get("environment"),
            "metrics": calculate_metrics(records),
            "by_trigger_type": {
                "signal": {"count": len(signal_records), "net_pnl": round(sum(r["pnl"] for r in signal_records), 2)},
                "scheduled": {"count": len(scheduled_records), "net_pnl": round(sum(r["pnl"] for r in scheduled_records), 2)},
            },
        })

    # Sort by net_pnl descending
    items.sort(key=lambda x: x["metrics"]["net_pnl"], reverse=True)

    # Unattributed (no account)
    unattributed_records = by_account.get(None, [])

    return {
        "items": items,
        "unattributed": {
            "count": len(unattributed_records),
            "metrics": calculate_metrics(unattributed_records) if unattributed_records else None,
        },
    }


@router.get("/by-symbol")
def get_analytics_by_symbol(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Get analytics grouped by trading symbol."""
    query = build_base_query(db, start_date, end_date, environment, account_id)
    decisions = query.all()

    # Group by symbol
    by_symbol: Dict[Optional[str], List[Dict]] = {}

    for d in decisions:
        symbol = d.symbol
        pnl = float(d.realized_pnl) if d.realized_pnl else 0
        record = {"pnl": pnl, "fee": 0, "trigger_type": get_trigger_type(d)}

        if symbol not in by_symbol:
            by_symbol[symbol] = []
        by_symbol[symbol].append(record)

    # Build response
    items = []
    for symbol, records in by_symbol.items():
        if symbol is None:
            continue

        signal_records = [r for r in records if r["trigger_type"] == "signal"]
        scheduled_records = [r for r in records if r["trigger_type"] == "scheduled"]

        items.append({
            "symbol": symbol,
            "metrics": calculate_metrics(records),
            "by_trigger_type": {
                "signal": {"count": len(signal_records), "net_pnl": round(sum(r["pnl"] for r in signal_records), 2)},
                "scheduled": {"count": len(scheduled_records), "net_pnl": round(sum(r["pnl"] for r in scheduled_records), 2)},
            },
        })

    # Sort by net_pnl descending
    items.sort(key=lambda x: x["metrics"]["net_pnl"], reverse=True)

    # Unattributed (no symbol)
    unattributed_records = by_symbol.get(None, [])

    return {
        "items": items,
        "unattributed": {
            "count": len(unattributed_records),
            "metrics": calculate_metrics(unattributed_records) if unattributed_records else None,
        },
    }


@router.get("/by-operation")
def get_analytics_by_operation(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Get analytics grouped by operation type (buy/sell/close)."""
    query = build_base_query(db, start_date, end_date, environment, account_id)
    decisions = query.all()

    # Group by operation
    by_operation: Dict[str, List[Dict]] = {}

    for d in decisions:
        operation = d.operation or "unknown"
        pnl = float(d.realized_pnl) if d.realized_pnl else 0
        record = {"pnl": pnl, "fee": 0, "trigger_type": get_trigger_type(d)}

        if operation not in by_operation:
            by_operation[operation] = []
        by_operation[operation].append(record)

    # Build response
    items = []
    for operation, records in by_operation.items():
        signal_records = [r for r in records if r["trigger_type"] == "signal"]
        scheduled_records = [r for r in records if r["trigger_type"] == "scheduled"]

        items.append({
            "operation": operation,
            "metrics": calculate_metrics(records),
            "by_trigger_type": {
                "signal": {"count": len(signal_records), "net_pnl": round(sum(r["pnl"] for r in signal_records), 2)},
                "scheduled": {"count": len(scheduled_records), "net_pnl": round(sum(r["pnl"] for r in scheduled_records), 2)},
            },
        })

    # Sort by trade_count descending
    items.sort(key=lambda x: x["metrics"]["trade_count"], reverse=True)

    return {"items": items}


@router.get("/by-trigger-type")
def get_analytics_by_trigger_type(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    environment: Optional[str] = Query("all"),
    account_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Get analytics grouped by trigger type (signal/scheduled/unknown)."""
    query = build_base_query(db, start_date, end_date, environment, account_id)
    decisions = query.all()

    # Group by trigger type
    by_trigger: Dict[str, List[Dict]] = {"signal": [], "scheduled": [], "unknown": []}

    for d in decisions:
        trigger_type = get_trigger_type(d)
        pnl = float(d.realized_pnl) if d.realized_pnl else 0
        record = {"pnl": pnl, "fee": 0}
        by_trigger[trigger_type].append(record)

    # Build response
    items = []
    for trigger_type in ["signal", "scheduled", "unknown"]:
        records = by_trigger[trigger_type]
        if records:
            items.append({
                "trigger_type": trigger_type,
                "metrics": calculate_metrics(records),
            })

    # Sort by trade_count descending
    items.sort(key=lambda x: x["metrics"]["trade_count"], reverse=True)

    return {"items": items}


# ============== AI Attribution Analysis Routes ==============

from fastapi.responses import StreamingResponse
from pydantic import BaseModel as PydanticBaseModel
from services.ai_attribution_service import (
    generate_attribution_analysis_stream,
    get_attribution_conversations,
    get_attribution_messages
)


class AiAttributionChatRequest(PydanticBaseModel):
    accountId: int
    userMessage: str
    conversationId: Optional[int] = None


@router.post("/ai-attribution/chat-stream")
async def ai_attribution_chat_stream(
    request: AiAttributionChatRequest,
    db: Session = Depends(get_db)
):
    """SSE streaming endpoint for AI attribution analysis chat."""
    return StreamingResponse(
        generate_attribution_analysis_stream(
            db=db,
            account_id=request.accountId,
            user_message=request.userMessage,
            conversation_id=request.conversationId
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/ai-attribution/conversations")
async def list_attribution_conversations(db: Session = Depends(get_db)):
    """Get list of AI attribution analysis conversations."""
    conversations = get_attribution_conversations(db)
    return {"conversations": conversations}


@router.get("/ai-attribution/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db)
):
    """Get messages for a specific conversation."""
    messages = get_attribution_messages(db, conversation_id)
    return {"messages": messages}
