# events.py — Council module event definitions
#
# This file defines the event suffixes for the council (deliberation) module.
#
# Use cases:
# 1. Deliberation completion event when council reaches consensus.
# 2. Sycophancy detection event when calibration probes fail.

from __future__ import annotations

NAMESPACE: str = "factory.council"

REGISTERED_EVENTS: tuple[str, ...] = (
    "deliberation_complete",
    "sycophancy_detected",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
