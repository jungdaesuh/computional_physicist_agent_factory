# events.py — Literature module event definitions
#
# This file defines the event suffixes for the literature module.
#
# Use cases:
# 1. API search queries and gap mining milestones.

from __future__ import annotations

NAMESPACE: str = "factory.literature"

REGISTERED_EVENTS: tuple[str, ...] = (
    "query_started",
    "query_completed",
    "gaps_mined",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
