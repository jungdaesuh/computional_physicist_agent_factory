# events.py — Surrogate module event definitions
#
# This file defines the event suffixes for the surrogate module.
#
# Use cases:
# 1. kNN surrogate validation and retrain milestones.

from __future__ import annotations

NAMESPACE: str = "factory.surrogate"

REGISTERED_EVENTS: tuple[str, ...] = (
    "evaluated",
    "ood_escalation",
    "retrain_started",
    "retrain_complete",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
