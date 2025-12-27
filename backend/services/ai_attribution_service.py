"""
AI Attribution Analysis Service

Handles AI-assisted attribution analysis conversations using LLM.
Supports Function Calling for AI to query trading performance data.
Role: Strategy Diagnosis Doctor - analyze performance, identify issues, suggest improvements.
"""

import json
import logging
import re
import time
import requests
from typing import Dict, List, Optional, Any, Generator
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import text

from database.models import (
    AiAttributionConversation, AiAttributionMessage,
    Account, AIDecisionLog, PromptTemplate, SignalPool
)
from services.ai_decision_service import build_chat_completion_endpoints, _extract_text_from_message

logger = logging.getLogger(__name__)

# System prompt for AI Attribution Analysis
ATTRIBUTION_SYSTEM_PROMPT = """You are a professional Trading Strategy Diagnosis Doctor.

## YOUR ROLE
Analyze user's trading performance data, identify problem patterns, and provide actionable improvement suggestions.

## CRITICAL: ENVIRONMENT CONFIRMATION
Before any analysis, you MUST confirm which trading environment to analyze:
- **testnet**: Test network trades (paper trading, testing)
- **mainnet**: Real money trades on Hyperliquid mainnet

Ask the user: "Which environment do you want to analyze - testnet or mainnet?"
Only proceed after getting a clear answer. Pass the environment parameter to ALL tool calls.

## ACCOUNT IDENTIFICATION
Users typically refer to accounts by NAME (e.g., "Deepseek", "Claude", "GPT"), not by ID.
When user mentions an account name:
1. FIRST call `list_ai_accounts` to get all accounts with their IDs and names
2. Match the user's description to find the correct account ID
3. Then proceed with analysis using that account ID

NEVER ask user for account ID directly. Instead, use `list_ai_accounts` and present options like:
"I found these AI accounts: Deepseek (ID: 1), Claude (ID: 2). Which one would you like to analyze?"

## GUIDED CONVERSATION
Before using analysis tools, confirm:
1. Which environment? (testnet or mainnet) - REQUIRED
2. Which account? (use `list_ai_accounts` to find by name)
3. Time period? (default: 30 days)

## WORKFLOW
1. Confirm environment (testnet/mainnet) with user
2. Use `list_ai_accounts` to identify account by name
3. Use `get_attribution_summary` to get overall performance metrics
4. Use `get_account_strategy` to understand current strategy configuration
5. Use `get_prompt_template` to see the AI prompt being used
6. Use `get_trade_decision_chain` to examine specific trade decisions
7. Identify patterns: which symbols or time periods perform poorly
8. Use `suggest_prompt_modification` to output structured improvement suggestions

## OUTPUT FORMAT
After analysis, output diagnosis cards using this format:

```diagnosis-card
{
  "type": "problem",
  "title": "High Loss Rate on DOGE",
  "severity": "high",
  "metrics": {"win_rate": "23%", "loss_count": 15, "symbol": "DOGE"},
  "description": "Your strategy loses 77% of trades on DOGE."
}
```

```prompt-suggestion
{
  "title": "Add DOGE Filter",
  "current": "Execute trades based on signal triggers",
  "suggested": "Avoid DOGE trades or reduce position size by 50%",
  "reason": "Historical data shows poor performance on DOGE"
}
```

## IMPORTANT RULES
- ALWAYS confirm environment before analysis
- NEVER ask for account ID - use `list_ai_accounts` to find by name
- Always use tools to get real data before making conclusions
- Be specific with numbers and percentages
- Provide actionable suggestions, not vague advice
- Connect diagnosis to prompt modifications when possible
"""

# Tools schema for Function Calling
ATTRIBUTION_TOOLS = []  # Will be defined below


def _define_tools():
    """Define Function Calling tools for attribution analysis"""
    global ATTRIBUTION_TOOLS
    ATTRIBUTION_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "list_ai_accounts",
                "description": "List all AI trading accounts with their IDs, names, and models. Use this FIRST when user mentions an account by name (e.g., 'Deepseek', 'Claude') to find the account ID.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_attribution_summary",
                "description": "Get trading performance summary including win rate, PnL, trade counts by operation/symbol.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "integer", "description": "Account ID to analyze. Use 0 for all accounts."},
                        "environment": {"type": "string", "enum": ["testnet", "mainnet"], "description": "Trading environment to analyze. REQUIRED."},
                        "days": {"type": "integer", "description": "Number of days to analyze (7, 30, 90)", "default": 30}
                    },
                    "required": ["account_id", "environment"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_account_strategy",
                "description": "Get account's trading strategy configuration including signal pool and prompt binding.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "integer", "description": "Account ID to query"}
                    },
                    "required": ["account_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_prompt_template",
                "description": "Get the prompt template content used by an account.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "integer", "description": "Account ID to get prompt for"}
                    },
                    "required": ["account_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_signal_pool_config",
                "description": "Get signal pool configuration including signals and trigger conditions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pool_id": {"type": "integer", "description": "Signal pool ID to query"}
                    },
                    "required": ["pool_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_trade_decision_chain",
                "description": "Get detailed decision chain for specific trades including AI reasoning and execution results.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "integer", "description": "Account ID"},
                        "environment": {"type": "string", "enum": ["testnet", "mainnet"], "description": "Trading environment. REQUIRED."},
                        "limit": {"type": "integer", "description": "Number of recent trades to fetch", "default": 10},
                        "filter_type": {"type": "string", "enum": ["all", "wins", "losses"], "description": "Filter by trade outcome"}
                    },
                    "required": ["account_id", "environment"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "suggest_prompt_modification",
                "description": "Generate a structured prompt modification suggestion card based on diagnosis.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short title for the suggestion"},
                        "current_behavior": {"type": "string", "description": "Current prompt behavior causing issues"},
                        "suggested_change": {"type": "string", "description": "Specific prompt modification to apply"},
                        "reason": {"type": "string", "description": "Why this change will improve performance"}
                    },
                    "required": ["title", "current_behavior", "suggested_change", "reason"]
                }
            }
        }
    ]


# Initialize tools
_define_tools()


def _execute_tool(db: Session, tool_name: str, args: Dict) -> str:
    """Execute a tool and return JSON result string"""
    try:
        if tool_name == "list_ai_accounts":
            return _tool_list_ai_accounts(db)
        elif tool_name == "get_attribution_summary":
            return _tool_get_attribution_summary(db, args)
        elif tool_name == "get_account_strategy":
            return _tool_get_account_strategy(db, args)
        elif tool_name == "get_prompt_template":
            return _tool_get_prompt_template(db, args)
        elif tool_name == "get_signal_pool_config":
            return _tool_get_signal_pool_config(db, args)
        elif tool_name == "get_trade_decision_chain":
            return _tool_get_trade_decision_chain(db, args)
        elif tool_name == "suggest_prompt_modification":
            return _tool_suggest_prompt_modification(args)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    except Exception as e:
        logger.error(f"Tool execution error: {tool_name}: {e}")
        return json.dumps({"error": str(e)})


def _tool_get_attribution_summary(db: Session, args: Dict) -> str:
    """Get trading performance summary"""
    account_id = args.get("account_id", 0)
    environment = args.get("environment")
    days = args.get("days", 30)

    if not environment:
        return json.dumps({"error": "environment is required (testnet or mainnet)"})

    start_date = datetime.now() - timedelta(days=days)

    # Build query with environment filter
    # Only include trades with non-zero PnL (exclude opening trades)
    query = db.query(AIDecisionLog).filter(
        AIDecisionLog.operation.in_(["buy", "sell", "close"]),
        AIDecisionLog.executed == "true",
        AIDecisionLog.realized_pnl.isnot(None),
        AIDecisionLog.realized_pnl != 0,  # Exclude opening trades (no settled PnL)
        AIDecisionLog.created_at >= start_date,
        AIDecisionLog.hyperliquid_environment == environment
    )

    if account_id > 0:
        query = query.filter(AIDecisionLog.account_id == account_id)

    decisions = query.all()

    if not decisions:
        return json.dumps({"message": "No trading data found for the specified period"})

    # Calculate metrics
    total_trades = len(decisions)
    wins = sum(1 for d in decisions if d.realized_pnl and float(d.realized_pnl) > 0)
    losses = sum(1 for d in decisions if d.realized_pnl and float(d.realized_pnl) < 0)
    total_pnl = sum(float(d.realized_pnl or 0) for d in decisions)

    # By operation
    by_operation = {}
    for d in decisions:
        op = d.operation
        if op not in by_operation:
            by_operation[op] = {"count": 0, "wins": 0, "pnl": 0}
        by_operation[op]["count"] += 1
        by_operation[op]["pnl"] += float(d.realized_pnl or 0)
        if d.realized_pnl and float(d.realized_pnl) > 0:
            by_operation[op]["wins"] += 1

    # By symbol
    by_symbol = {}
    for d in decisions:
        sym = d.symbol or "UNKNOWN"
        if sym not in by_symbol:
            by_symbol[sym] = {"count": 0, "wins": 0, "pnl": 0}
        by_symbol[sym]["count"] += 1
        by_symbol[sym]["pnl"] += float(d.realized_pnl or 0)
        if d.realized_pnl and float(d.realized_pnl) > 0:
            by_symbol[sym]["wins"] += 1

    return json.dumps({
        "period_days": days,
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": f"{(wins/total_trades*100):.1f}%" if total_trades > 0 else "N/A",
        "total_pnl": round(total_pnl, 2),
        "by_operation": by_operation,
        "by_symbol": by_symbol
    })


def _tool_get_account_strategy(db: Session, args: Dict) -> str:
    """Get account strategy configuration"""
    account_id = args.get("account_id")
    if not account_id:
        return json.dumps({"error": "account_id is required"})

    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        return json.dumps({"error": f"Account {account_id} not found"})

    # Get prompt binding - handle case where account is not bound to signal pool
    prompt_binding = getattr(account, 'prompt_binding', None)
    prompt_info = None
    signal_pool_id = None

    if prompt_binding:
        signal_pool_id = prompt_binding.signal_pool_id
        if prompt_binding.prompt_template:
            prompt_info = {
                "id": prompt_binding.prompt_template.id,
                "name": prompt_binding.prompt_template.name
            }

    return json.dumps({
        "account_id": account.id,
        "name": account.name,
        "model": account.model,
        "auto_trading_enabled": account.auto_trading_enabled,
        "hyperliquid_enabled": account.hyperliquid_enabled,
        "hyperliquid_environment": account.hyperliquid_environment,
        "max_leverage": account.max_leverage,
        "default_leverage": account.default_leverage,
        "prompt_template": prompt_info,
        "signal_pool_id": signal_pool_id,
        "note": "Account not bound to any signal pool" if not prompt_binding else None
    })


def _tool_get_prompt_template(db: Session, args: Dict) -> str:
    """Get prompt template content for an account"""
    account_id = args.get("account_id")
    if not account_id:
        return json.dumps({"error": "account_id is required"})

    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        return json.dumps({"error": f"Account {account_id} not found"})

    if not account.prompt_binding or not account.prompt_binding.prompt_template:
        return json.dumps({"message": "No prompt template bound to this account"})

    template = account.prompt_binding.prompt_template
    return json.dumps({
        "id": template.id,
        "name": template.name,
        "content": template.template_text,  # Return full content without truncation
        "is_system": template.is_system
    })


def _tool_get_signal_pool_config(db: Session, args: Dict) -> str:
    """Get signal pool configuration"""
    pool_id = args.get("pool_id")
    if not pool_id:
        return json.dumps({"error": "pool_id is required"})

    pool = db.query(SignalPool).filter(SignalPool.id == pool_id).first()
    if not pool:
        return json.dumps({"error": f"Signal pool {pool_id} not found"})

    # Parse signals JSON
    signals = []
    if pool.signals:
        try:
            signals = json.loads(pool.signals) if isinstance(pool.signals, str) else pool.signals
        except:
            pass

    return json.dumps({
        "id": pool.id,
        "name": pool.name,
        "symbol": pool.symbol,
        "logic": pool.logic,
        "enabled": pool.enabled,
        "signals": signals
    })


def _tool_get_trade_decision_chain(db: Session, args: Dict) -> str:
    """Get detailed trade decision chain"""
    account_id = args.get("account_id")
    environment = args.get("environment")
    limit = args.get("limit", 10)
    filter_type = args.get("filter_type", "all")

    if not account_id:
        return json.dumps({"error": "account_id is required"})

    if not environment:
        return json.dumps({"error": "environment is required (testnet or mainnet)"})

    query = db.query(AIDecisionLog).filter(
        AIDecisionLog.account_id == account_id,
        AIDecisionLog.executed == "true",
        AIDecisionLog.realized_pnl.isnot(None),
        AIDecisionLog.hyperliquid_environment == environment
    )

    if filter_type == "wins":
        query = query.filter(AIDecisionLog.realized_pnl > 0)
    elif filter_type == "losses":
        query = query.filter(AIDecisionLog.realized_pnl < 0)

    decisions = query.order_by(AIDecisionLog.created_at.desc()).limit(limit).all()

    trades = []
    for d in decisions:
        trades.append({
            "id": d.id,
            "symbol": d.symbol,
            "operation": d.operation,
            "realized_pnl": float(d.realized_pnl) if d.realized_pnl else 0,
            "reason": (d.reason[:500] if d.reason else None),  # Truncate
            "created_at": d.created_at.isoformat() if d.created_at else None
        })

    return json.dumps({"trades": trades, "count": len(trades)})


def _tool_suggest_prompt_modification(args: Dict) -> str:
    """Generate structured prompt modification suggestion"""
    return json.dumps({
        "_type": "prompt_suggestion",
        "title": args.get("title", "Untitled Suggestion"),
        "current_behavior": args.get("current_behavior", ""),
        "suggested_change": args.get("suggested_change", ""),
        "reason": args.get("reason", "")
    })


def _tool_list_ai_accounts(db: Session) -> str:
    """List all AI trading accounts with their IDs, names, and models"""
    accounts = db.query(Account).filter(Account.account_type == "AI").all()

    if not accounts:
        return json.dumps({"message": "No AI accounts found", "accounts": []})

    account_list = []
    for acc in accounts:
        account_list.append({
            "id": acc.id,
            "name": acc.name,
            "model": acc.model,
            "environment": acc.hyperliquid_environment,
            "auto_trading_enabled": acc.auto_trading_enabled
        })

    return json.dumps({"accounts": account_list, "count": len(account_list)})


def extract_diagnosis_results(content: str) -> List[Dict]:
    """Extract diagnosis cards and prompt suggestions from AI response"""
    results = []

    # Extract diagnosis cards
    diagnosis_pattern = r"```diagnosis-card\s*([\s\S]*?)```"
    for match in re.findall(diagnosis_pattern, content):
        try:
            card = json.loads(match.strip())
            card["_type"] = "diagnosis"
            results.append(card)
        except:
            pass

    # Extract prompt suggestions
    suggestion_pattern = r"```prompt-suggestion\s*([\s\S]*?)```"
    for match in re.findall(suggestion_pattern, content):
        try:
            suggestion = json.loads(match.strip())
            suggestion["_type"] = "prompt_suggestion"
            results.append(suggestion)
        except:
            pass

    return results


def generate_attribution_analysis_stream(
    db: Session,
    account_id: int,
    user_message: str,
    conversation_id: Optional[int] = None,
    user_id: int = 1
) -> Generator[str, None, None]:
    """Generate attribution analysis with SSE streaming"""
    start_time = time.time()
    request_id = f"attr_analysis_{int(start_time)}"

    logger.info(f"[AI Attribution {request_id}] Starting: account_id={account_id}")

    try:
        # Get AI account
        account = db.query(Account).filter(
            Account.id == account_id,
            Account.account_type == "AI"
        ).first()

        if not account:
            yield f"event: error\ndata: {json.dumps({'message': 'AI account not found'})}\n\n"
            return

        # Get or create conversation
        conversation = None
        if conversation_id:
            conversation = db.query(AiAttributionConversation).filter(
                AiAttributionConversation.id == conversation_id,
                AiAttributionConversation.user_id == user_id
            ).first()

        if not conversation:
            title = user_message[:50] + "..." if len(user_message) > 50 else user_message
            conversation = AiAttributionConversation(user_id=user_id, title=title)
            db.add(conversation)
            db.flush()

        # Save user message
        user_msg = AiAttributionMessage(
            conversation_id=conversation.id,
            role="user",
            content=user_message
        )
        db.add(user_msg)
        db.flush()

        yield f"event: status\ndata: {json.dumps({'message': 'Analyzing...'})}\n\n"

        # Build message history
        messages = [{"role": "system", "content": ATTRIBUTION_SYSTEM_PROMPT}]

        history = db.query(AiAttributionMessage).filter(
            AiAttributionMessage.conversation_id == conversation.id,
            AiAttributionMessage.id != user_msg.id
        ).order_by(AiAttributionMessage.created_at).limit(10).all()

        for msg in history:
            messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": user_message})

        # Call LLM with Function Calling
        endpoints = build_chat_completion_endpoints(account.base_url, account.model)
        if not endpoints:
            yield f"event: error\ndata: {json.dumps({'message': 'Invalid API configuration'})}\n\n"
            return

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {account.api_key}"
        }

        # Function calling loop
        max_rounds = 15
        assistant_content = None

        # Collect reasoning and analysis log for storage
        all_reasoning_parts = []
        all_analysis_log = []

        for round_num in range(max_rounds):
            is_last = (round_num == max_rounds - 1)

            request_payload = {
                "model": account.model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 4096,
            }

            if is_last:
                messages.append({
                    "role": "user",
                    "content": "Now provide your final analysis with diagnosis cards and suggestions."
                })
            else:
                request_payload["tools"] = ATTRIBUTION_TOOLS
                request_payload["tool_choice"] = "auto"

            response = None
            for endpoint in endpoints:
                try:
                    response = requests.post(endpoint, json=request_payload, headers=headers, timeout=120)
                    if response.status_code == 200:
                        break
                except:
                    continue

            if not response or response.status_code != 200:
                yield f"event: error\ndata: {json.dumps({'message': 'API request failed'})}\n\n"
                return

            resp_json = response.json()
            message = resp_json["choices"][0]["message"]
            tool_calls = message.get("tool_calls", [])
            content = message.get("content", "")
            reasoning = message.get("reasoning_content", "")

            if reasoning:
                yield f"event: reasoning\ndata: {json.dumps({'content': reasoning[:200]})}\n\n"
                # Collect full reasoning for storage
                all_reasoning_parts.append(reasoning)

            if tool_calls:
                msg_dict = {"role": "assistant", "content": content or "", "tool_calls": tool_calls}
                if reasoning:
                    msg_dict["reasoning_content"] = reasoning
                messages.append(msg_dict)

                for tc in tool_calls:
                    func_name = tc["function"]["name"]
                    try:
                        func_args = json.loads(tc["function"]["arguments"])
                    except:
                        func_args = {}

                    yield f"event: tool_call\ndata: {json.dumps({'name': func_name, 'arguments': func_args})}\n\n"

                    result = _execute_tool(db, func_name, func_args)
                    yield f"event: tool_result\ndata: {json.dumps({'name': func_name, 'result': json.loads(result)})}\n\n"

                    # Collect tool call and result for storage
                    all_analysis_log.append({
                        "type": "tool_call",
                        "name": func_name,
                        "arguments": func_args
                    })
                    all_analysis_log.append({
                        "type": "tool_result",
                        "name": func_name,
                        "result": json.loads(result)
                    })

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result
                    })
            else:
                # Final response - only use content, not reasoning
                assistant_content = _extract_text_from_message(content) if content else ""
                break

        if not assistant_content:
            assistant_content = "Analysis completed but no final response generated."

        # Extract diagnosis results
        diagnosis_results = extract_diagnosis_results(assistant_content)

        # Save assistant message with reasoning and analysis log
        reasoning_snapshot = "\n\n---\n\n".join(all_reasoning_parts) if all_reasoning_parts else None
        analysis_log_json = json.dumps(all_analysis_log) if all_analysis_log else None

        assistant_msg = AiAttributionMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=assistant_content,
            diagnosis_result=json.dumps(diagnosis_results) if diagnosis_results else None,
            reasoning_snapshot=reasoning_snapshot,
            analysis_log=analysis_log_json
        )
        db.add(assistant_msg)
        db.commit()

        # Send final response
        yield f"event: content\ndata: {json.dumps({'content': assistant_content})}\n\n"
        yield f"event: done\ndata: {json.dumps({'conversation_id': conversation.id, 'message_id': assistant_msg.id, 'content': assistant_content, 'diagnosis_results': diagnosis_results})}\n\n"

    except Exception as e:
        logger.error(f"[AI Attribution {request_id}] Error: {e}", exc_info=True)
        db.rollback()
        yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"


def get_attribution_conversations(db: Session, user_id: int = 1, limit: int = 20) -> List[Dict]:
    """Get list of attribution analysis conversations"""
    conversations = db.query(AiAttributionConversation).filter(
        AiAttributionConversation.user_id == user_id
    ).order_by(AiAttributionConversation.updated_at.desc()).limit(limit).all()

    return [{
        "id": c.id,
        "title": c.title,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None
    } for c in conversations]


def get_attribution_messages(db: Session, conversation_id: int, user_id: int = 1) -> List[Dict]:
    """Get messages for a specific conversation"""
    conversation = db.query(AiAttributionConversation).filter(
        AiAttributionConversation.id == conversation_id,
        AiAttributionConversation.user_id == user_id
    ).first()

    if not conversation:
        return []

    messages = db.query(AiAttributionMessage).filter(
        AiAttributionMessage.conversation_id == conversation_id
    ).order_by(AiAttributionMessage.created_at).all()

    result = []
    for m in messages:
        msg_dict = {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None
        }
        if m.diagnosis_result:
            try:
                msg_dict["diagnosis_results"] = json.loads(m.diagnosis_result)
            except:
                pass
        # Include reasoning and analysis log for history display
        if m.reasoning_snapshot:
            msg_dict["reasoning_snapshot"] = m.reasoning_snapshot
        if m.analysis_log:
            try:
                msg_dict["analysis_log"] = json.loads(m.analysis_log)
            except:
                pass
        result.append(msg_dict)

    return result

