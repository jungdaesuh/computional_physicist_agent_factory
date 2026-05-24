# events.py — Strategy module event definitions
#
# This file defines the event suffixes for the strategy module.

from __future__ import annotations

NAMESPACE: str = "factory.strategy"

REGISTERED_EVENTS: tuple[str, ...] = (
    "attribute",
    "select_lineages",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
