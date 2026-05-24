# events.py — Adapter module event definitions
#
# This file defines the event suffixes for the adapter module.
#
# Use cases:
# 1. Adapter initialization or run status logging.

from __future__ import annotations

NAMESPACE: str = "factory.adapter"

REGISTERED_EVENTS: tuple[str, ...] = (
    "adapter_initialized",
    "sim_run_started",
    "sim_run_completed",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
