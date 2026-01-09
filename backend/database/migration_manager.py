#!/usr/bin/env python3
"""
Database Migration Manager

Runs all migrations on every startup, relying on idempotency.
Each migration script must check if changes are needed before applying.

Architecture:
- No migration records - we don't track "what ran", only "what's correct"
- Idempotency is the core guarantee - scripts check before executing
- schema_validator provides final fallback after migrations
"""
import os
import sys
import logging
from pathlib import Path

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# List of migration scripts in execution order
# Each script MUST have idempotency checks (check if column/table exists before adding)
MIGRATIONS = [
    "add_environment_to_crypto_klines.py",
    "add_prompt_template_fields.py",
    "add_ai_prompt_chat.py",
    "fix_timestamp_bigint.py",
    "create_signal_system_tables.py",
    "add_wallet_address_to_snapshot_tables.py",
    "add_wallet_address_to_hyperliquid_trades.py",
    "add_ai_signal_chat.py",
    "add_signal_pool_to_strategy.py",
    "add_logic_to_signal_pools.py",
    "fix_enabled_column_type.py",
    "convert_signal_jsonb_to_text.py",
    "create_market_regime_configs.py",
    "add_market_regime_to_trigger_logs.py",
    "add_decision_tracking_fields.py",
    "add_ai_attribution_chat.py",
    "add_scheduled_trigger_enabled.py",
    "add_show_on_dashboard.py",
    "add_signal_pool_ids_field.py",
    "add_prompt_backtest_tables.py",
]


def run_migration(migration_file: str) -> bool:
    """
    Execute a single migration script.
    Returns True if successful (or already applied), False if failed.
    """
    migrations_dir = Path(__file__).parent / "migrations"
    migration_path = migrations_dir / migration_file

    if not migration_path.exists():
        logger.error(f"Migration file not found: {migration_path}")
        return False

    try:
        spec = __import__(f"database.migrations.{migration_file[:-3]}", fromlist=["upgrade"])
        if hasattr(spec, 'upgrade'):
            logger.debug(f"Running migration: {migration_file}")
            spec.upgrade()
            return True
        else:
            logger.error(f"Migration {migration_file} missing upgrade function")
            return False
    except Exception as e:
        # Log error but don't fail - migration may have already been applied
        # or schema_validator will fix it later
        logger.warning(f"Migration {migration_file} error (may be already applied): {e}")
        return False


def run_all_migrations() -> bool:
    """
    Run all migrations on every startup.
    Relies on idempotency - each script checks if changes are needed.

    NEVER blocks startup - all errors are logged but execution continues.
    """
    logger.info("Running all migrations (idempotency-based)...")

    success_count = 0
    skip_count = 0
    error_count = 0

    for migration in MIGRATIONS:
        try:
            if run_migration(migration):
                success_count += 1
            else:
                error_count += 1
        except Exception as e:
            logger.error(f"Unexpected error in {migration}: {e}")
            error_count += 1

    # Log summary
    if error_count > 0:
        logger.warning(f"Migrations: {success_count} ok, {error_count} errors (may be already applied)")
    else:
        logger.info(f"Migrations: {success_count} completed successfully")

    # Always return True - never block startup
    # schema_validator will catch any remaining issues
    return True


# Backward compatibility alias
run_pending_migrations = run_all_migrations


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    success = run_all_migrations()
    sys.exit(0 if success else 1)
