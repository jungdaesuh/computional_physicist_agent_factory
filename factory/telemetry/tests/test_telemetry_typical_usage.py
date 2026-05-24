# test_telemetry_typical_usage.py — Integration test showing typical usage
#
# This test demonstrates a typical setup, registration building, event emission,
# thread-global activation, and querying via AuditQuery.

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from factory.telemetry.api import (
    AuditQuery,
    EventRegistry,
    TelemetryEmitter,
    emit,
    set_active_emitter,
)
from factory.telemetry.errors import EventTaxonomyViolation

logger = logging.getLogger("factory.telemetry.tests")


class MockPayloadSchema(BaseModel):
    cost_usd: float = Field(..., ge=0.0)
    agent_id: str


def test_telemetry_typical_usage(tmp_path: Path) -> None:
    """Demonstrates typical usage of the telemetry module."""
    logger.info("Running typical usage test for telemetry")

    # 1. Build the registry
    registry = EventRegistry.build()
    assert len(registry.namespaces()) > 0

    # Let's temporarily inject a validation schema to test it
    # We do this for the test specifically to keep it hermetic
    registry._payload_schemas["factory.council.deliberation_complete"] = MockPayloadSchema

    # 2. Construct the emitter
    cycle_dir = tmp_path / "cyc-0001"
    emitter = TelemetryEmitter(
        cycle_dir=cycle_dir,
        registry=registry,
        mock_mode=False,
        flush_every_n=1,
        cycle_id="cyc-0001",
    )

    # Activate global context
    set_active_emitter(emitter)

    try:
        # 3. Emit valid events (convenience function and direct emitter)
        # Verify direct emit
        emitter.emit(
            "factory.council.deliberation_complete",
            {"cost_usd": 0.05, "agent_id": "agent-alpha"},
        )

        # Verify global convenience function
        emit(
            "factory.genver.iteration_start",
            {"iteration_index": 0},
        )

        # 4. Attempt to emit an invalid event (unregistered suffix)
        with pytest.raises(EventTaxonomyViolation) as exc_info:
            emitter.emit(
                "factory.council.nonexistent_suffix",
                {},
            )
        assert "unregistered event" in str(exc_info.value)

        # 5. Attempt to emit an invalid event (unknown namespace)
        with pytest.raises(EventTaxonomyViolation) as exc_info:
            emitter.emit(
                "factory.invalidns.event",
                {},
            )
        assert "unknown namespace" in str(exc_info.value)

        # 6. Attempt to emit invalid payload schema
        with pytest.raises(EventTaxonomyViolation) as exc_info:
            emitter.emit(
                "factory.council.deliberation_complete",
                {"cost_usd": -10.0, "agent_id": "invalid-cost"},
            )
        assert "payload schema mismatch" in str(exc_info.value)

    finally:
        emitter.close()
        set_active_emitter(None)

    # 7. Query/Verify output file exists and has correct contents
    log_file = cycle_dir / "cycle.jsonl"
    assert log_file.exists()

    with open(log_file) as f:
        lines = f.readlines()
        assert len(lines) == 2

        event1 = json.loads(lines[0])
        assert event1["event"] == "factory.council.deliberation_complete"
        assert event1["payload"]["cost_usd"] == 0.05
        assert event1["cycle_id"] == "cyc-0001"

        event2 = json.loads(lines[1])
        assert event2["event"] == "factory.genver.iteration_start"
        assert event2["payload"]["iteration_index"] == 0

    # 8. Query via AuditQuery
    query = AuditQuery(runs_dir=tmp_path)
    records = list(query.by_cycle("cyc-0001"))
    assert len(records) == 2
    assert records[0]["event"] == "factory.council.deliberation_complete"
