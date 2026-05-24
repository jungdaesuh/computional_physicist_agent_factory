# events.py — Ledger module event definitions
#
# This file defines the event suffixes for the ledger module.
#
# Use cases:
# 1. Insertion of evidence ledger entry.
# 2. Evaluation of ledger trigger checks.

from __future__ import annotations

NAMESPACE: str = "factory.ledger"

REGISTERED_EVENTS: tuple[str, ...] = (
    "entry_inserted",
    "trigger_check_failed",
    "evaluate_triggers_complete",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
