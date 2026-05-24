# events.py — Artifacts module event definitions
#
# This file defines the event suffixes for the artifacts module.
#
# Use cases:
# 1. Validation or generation of physical run artifacts.

from __future__ import annotations

NAMESPACE: str = "factory.artifacts"

REGISTERED_EVENTS: tuple[str, ...] = (
    "artifact_created",
    "artifact_validated",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
