# events.py — Operator module event definitions
#
# This file defines the event suffixes for the operator module.
#
# Use cases:
# 1. External operator commands and execution logging.

from __future__ import annotations

NAMESPACE: str = "factory.operator"

REGISTERED_EVENTS: tuple[str, ...] = (
    "command_received",
    "command_executed",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
