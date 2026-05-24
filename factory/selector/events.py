# events.py — Selector module event definitions
#
# This file defines the event suffixes for the selector module.
#
# Use cases:
# 1. Simulator selected for a hypothesis.

from __future__ import annotations

NAMESPACE: str = "factory.selector"

REGISTERED_EVENTS: tuple[str, ...] = ("simulator_selected",)

PAYLOAD_SCHEMAS: dict[str, type] = {}
