# events.py — State machine module event definitions
#
# This file defines the event suffixes for the state machine.
#
# Use cases:
# 1. Gate execution routing events.
# 2. Cycle completion.

from __future__ import annotations

NAMESPACE: str = "factory.state_machine"

REGISTERED_EVENTS: tuple[str, ...] = (
    "gate_enter",
    "gate_exit",
    "cycle_complete",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
