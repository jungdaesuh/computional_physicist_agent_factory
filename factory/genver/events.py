# events.py — Genver module event definitions
#
# This file defines the event suffixes for the genver module.
#
# Use cases:
# 1. Tracking ReAct agent loop execution milestones.
# 2. Tracking candidate promotion attempts and status.

from __future__ import annotations

NAMESPACE: str = "factory.genver"

REGISTERED_EVENTS: tuple[str, ...] = (
    "iteration_start",
    "iteration_end",
    "sandbox_open",
    "sandbox_exit",
    "promote_attempt",
    "promote_succeeded",
    "promote_failed",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
