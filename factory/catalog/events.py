# events.py — Catalog module event definitions
#
# This file defines the event suffixes for the catalog module.
#
# Use cases:
# 1. Smoke test passed for container environment checks.
# 2. Smoke test failed.

from __future__ import annotations

NAMESPACE: str = "factory.catalog"

REGISTERED_EVENTS: tuple[str, ...] = (
    "smoke_test_passed",
    "smoke_test_failed",
)

PAYLOAD_SCHEMAS: dict[str, type] = {}
