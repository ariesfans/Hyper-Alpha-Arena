"""
Prompt Backtest Service

Handles async execution of prompt backtest tasks:
- Processes items in parallel with real-time progress updates
- Calls LLM with modified prompts
- Parses responses and updates results immediately
"""

import json
import logging
import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy import text
from database.connection import SessionLocal
from database.models import (
    Account,
    PromptTemplate,
    PromptBacktestTask,
    PromptBacktestItem,
    AccountPromptBinding,
)

logger = logging.getLogger(__name__)

# Parallel execution config
MAX_WORKERS = 20


def execute_backtest_task(task_id: int) -> None:
    """Execute a backtest task with parallel LLM calls and real-time progress."""
    logger.info(f"Starting backtest task {task_id} with {MAX_WORKERS} workers")

    # Get task info and prepare data
    with SessionLocal() as db:
        task = db.query(PromptBacktestTask).filter(
            PromptBacktestTask.id == task_id
        ).first()

        if not task:
            logger.error(f"Task {task_id} not found")
            return

        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        db.commit()

        account = db.query(Account).filter(Account.id == task.account_id).first()
        if not account:
            task.status = "failed"
            task.error_message = "Account not found"
            task.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        system_prompt = _get_system_prompt(db, account.id)

        items = db.query(PromptBacktestItem).filter(
            PromptBacktestItem.task_id == task_id,
            PromptBacktestItem.status == "pending"
        ).all()

        item_data = [
            {
                "item_id": item.id,
                "task_id": task_id,
                "modified_prompt": item.modified_prompt,
                "original_operation": item.original_operation,
            }
            for item in items
        ]

        account_config = {
            "api_key": account.api_key,
            "base_url": account.base_url,
            "model": account.model,
        }

    # Process items in parallel with real-time storage
    _process_items_realtime(item_data, account_config, system_prompt)

    # Finalize task
    with SessionLocal() as db:
        task = db.query(PromptBacktestTask).filter(
            PromptBacktestTask.id == task_id
        ).first()
        task.status = "completed"
        task.finished_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(
            f"Backtest task {task_id} completed: "
            f"{task.completed_count} success, {task.failed_count} failed"
        )


def _process_items_realtime(
    items: List[Dict], account_config: Dict, system_prompt: str
) -> None:
    """Process items in parallel, saving each result immediately."""
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                _process_and_save_item,
                item,
                account_config,
                system_prompt
            ): item["item_id"]
            for item in items
        }

        for future in as_completed(futures):
            item_id = futures[future]
            try:
                future.result()
            except Exception as e:
                logger.error(f"Item {item_id} raised exception: {e}")


def _process_and_save_item(
    item: Dict, account_config: Dict, system_prompt: str
) -> None:
    """Process a single item and save result immediately (called in thread)."""
    item_id = item["item_id"]
    task_id = item["task_id"]
    response = None

    try:
        # Call LLM
        response = _call_llm_with_config(
            account_config, system_prompt, item["modified_prompt"]
        )

        if not response:
            _save_item_result(item_id, task_id, {
                "success": False,
                "error": "LLM call failed - no response",
            })
            return

        # Parse decision
        decision = _parse_decision(response)
        if not decision:
            _save_item_result(item_id, task_id, {
                "success": False,
                "error": "Failed to parse decision",
                "raw_response": response[:2000],
            })
            return

        # Calculate change
        new_op = (decision.get("operation") or "").lower()
        orig_op = (item["original_operation"] or "").lower()
        decision_changed = orig_op != new_op
        change_type = f"{orig_op}_to_{new_op}" if decision_changed else None

        _save_item_result(item_id, task_id, {
            "success": True,
            "operation": decision.get("operation"),
            "symbol": decision.get("symbol"),
            "target_portion": decision.get("target_portion_of_balance"),
            "reasoning": decision.get("_reasoning", response[:2000]),
            "decision_json": json.dumps(decision),
            "decision_changed": decision_changed,
            "change_type": change_type,
        })

    except Exception as e:
        logger.error(f"Error processing item {item_id}: {e}")
        _save_item_result(item_id, task_id, {
            "success": False,
            "error": str(e)[:500],
            "raw_response": response[:2000] if response else None,
        })


def _save_item_result(item_id: int, task_id: int, result: Dict) -> None:
    """Save item result and update task count atomically."""
    with SessionLocal() as db:
        item = db.query(PromptBacktestItem).filter(
            PromptBacktestItem.id == item_id
        ).first()

        if not item:
            return

        if result.get("success"):
            item.status = "completed"
            item.new_operation = result.get("operation")
            item.new_symbol = result.get("symbol")
            item.new_target_portion = result.get("target_portion")
            item.new_reasoning = result.get("reasoning")
            item.new_decision_json = result.get("decision_json")
            item.decision_changed = result.get("decision_changed")
            item.change_type = result.get("change_type")
            # Atomic increment completed_count
            db.execute(
                text("UPDATE prompt_backtest_tasks SET completed_count = completed_count + 1 WHERE id = :task_id"),
                {"task_id": task_id}
            )
        else:
            item.status = "failed"
            item.error_message = result.get("error", "Unknown error")[:500]
            if result.get("raw_response"):
                item.new_reasoning = result.get("raw_response")
            # Atomic increment failed_count
            db.execute(
                text("UPDATE prompt_backtest_tasks SET failed_count = failed_count + 1 WHERE id = :task_id"),
                {"task_id": task_id}
            )

        db.commit()


def _get_system_prompt(db, account_id: int) -> str:
    """Get system prompt from account's prompt binding."""
    binding = db.query(AccountPromptBinding).filter(
        AccountPromptBinding.account_id == account_id
    ).first()

    if binding and binding.prompt_template_id:
        template = db.query(PromptTemplate).filter(
            PromptTemplate.id == binding.prompt_template_id
        ).first()
        if template and template.system_template_text:
            return template.system_template_text

    # Default system prompt
    return "You are a systematic trading assistant. Analyze the market data and make trading decisions."


def _call_llm_with_config(
    config: Dict[str, str], system_prompt: str, user_prompt: str
) -> Optional[str]:
    """Call LLM API with config dict (thread-safe, no ORM objects)."""
    from services.ai_decision_service import build_chat_completion_endpoints

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }

    model = config.get("model", "")
    model_lower = model.lower()

    # Detect reasoning models
    is_reasoning_model = any(
        marker in model_lower for marker in [
            "gpt-5", "o1-preview", "o1-mini", "o1-", "o3-", "o4-",
            "deepseek-r1", "deepseek-reasoner",
            "qwq", "qwen-plus-thinking", "qwen-max-thinking",
            "claude-4", "claude-sonnet-4-5",
            "gemini-2.5", "gemini-3",
        ]
    )

    is_new_model = is_reasoning_model or "gpt-4o" in model_lower

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    if not is_reasoning_model:
        payload["temperature"] = 0.7

    if is_new_model:
        payload["max_completion_tokens"] = 5000
    else:
        payload["max_tokens"] = 5000

    endpoints = build_chat_completion_endpoints(config.get("base_url", ""), model)
    if not endpoints:
        logger.error(f"No valid API endpoint for model {model}")
        return None

    request_timeout = 240 if is_reasoning_model else 120

    for endpoint in endpoints:
        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=request_timeout,
                verify=False,
            )

            if response.status_code == 200:
                data = response.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")

            logger.warning(f"LLM call failed: {response.status_code} - {response.text[:200]}")

        except Exception as e:
            logger.error(f"LLM call exception: {e}")
            continue

    return None


def _parse_decision(response: str) -> Optional[Dict[str, Any]]:
    """Parse decision JSON from LLM response.

    Logic mirrors ai_decision_service.py for consistency:
    1. Extract from code blocks if present
    2. Direct json.loads on cleaned content
    3. Cleanup special characters and retry
    4. Handle {"decisions": [...]} nested structure
    """
    if not response:
        return None

    cleaned_content = response.strip()

    # Step 1: Extract from code blocks (same as ai_decision_service.py)
    if "```json" in cleaned_content:
        cleaned_content = cleaned_content.split("```json")[1].split("```")[0].strip()
    elif "```" in cleaned_content:
        cleaned_content = cleaned_content.split("```")[1].split("```")[0].strip()

    # Step 2: Try direct json.loads
    decision = None
    try:
        decision = json.loads(cleaned_content)
    except json.JSONDecodeError:
        # Step 3: Cleanup special characters and retry (same as ai_decision_service.py)
        cleaned = (
            cleaned_content.replace("\n", " ")
            .replace("\r", " ")
            .replace("\t", " ")
        )
        # Fix common unicode issues
        cleaned = cleaned.replace(""", '"').replace(""", '"')
        cleaned = cleaned.replace("'", "'").replace("'", "'")
        cleaned = cleaned.replace("–", "-").replace("—", "-").replace("‑", "-")

        try:
            decision = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning(f"JSON parsing failed for backtest response: {cleaned[:200]}...")
            return None

    if not decision:
        return None

    # Step 4: Handle {"decisions": [...]} nested structure (same as ai_decision_service.py)
    if isinstance(decision, dict) and isinstance(decision.get("decisions"), list):
        decisions = decision.get("decisions") or []
        if decisions and isinstance(decisions[0], dict):
            result = dict(decisions[0])  # Copy to avoid mutation
            result["_reasoning"] = response[:2000]
            return result
    elif isinstance(decision, list) and decision:
        # Handle direct array format
        if isinstance(decision[0], dict):
            result = dict(decision[0])
            result["_reasoning"] = response[:2000]
            return result
    elif isinstance(decision, dict) and "operation" in decision:
        # Direct format {"operation": "buy", ...}
        decision["_reasoning"] = response[:2000]
        return decision

    logger.warning(f"Unexpected decision structure: {type(decision)}")
    return None
