# events.py — Telemetry module event definitions
#
# This file defines the event suffixes and schema metadata for the telemetry module.
# Every event emitted by this module must have its suffix registered in REGISTERED_EVENTS.
#
# Use cases:
# 1. Registering line corruption events when parsing truncated log files.
# 2. Registering backlog warnings when the aggregator falls behind.

from __future__ import annotations

NAMESPACE: str = "factory.telemetry"

REGISTERED_EVENTS: tuple[str, ...] = (
    "line_corrupted",
    "aggregator_backlog",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
