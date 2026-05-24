# events.py — Validation module event definitions
#
# This file defines the event suffixes for the validation module.
#
# Use cases:
# 1. Logging validation portfolio checks (passed or failed).

from __future__ import annotations

NAMESPACE: str = "factory.validation"

REGISTERED_EVENTS: tuple[str, ...] = (
    "portfolio_passed",
    "portfolio_failed",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
