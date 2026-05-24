# events.py — Writer module event definitions
#
# This file defines the event suffixes for the writer module.
#
# Use cases:
# 1. Paper writing or RAG compilation log milestones.

from __future__ import annotations

NAMESPACE: str = "factory.writer"

REGISTERED_EVENTS: tuple[str, ...] = (
    "writer_started",
    "paper_written",
    "report_compiled",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
