# events.py — Budget module event definitions
#
# This file defines the event suffixes for the budget module.
#
# Use cases:
# 1. Budget cap warning or exhaustion events.

from __future__ import annotations

NAMESPACE: str = "factory.budget"

REGISTERED_EVENTS: tuple[str, ...] = (
    "cap_warning",
    "cap_exhausted",
    "aggregate_halt",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
