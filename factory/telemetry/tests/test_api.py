# test_api.py — Unit tests for the telemetry module API
#
# Tests registry validation, unknown vs unregistered checks, soft degradation,
# corrupted log parsing, and SQLite-backed hypothesis query routing.

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from factory.artifacts.api import HypothesisId
from factory.telemetry.api import (
    KNOWN_NAMESPACES,
    AuditQuery,
    EventRegistry,
    TelemetryEmitter,
    aggregate_jsonl_events,
    emit,
    set_active_emitter,
)
from factory.telemetry.errors import (
    EventTaxonomyViolation,
    JSONLineCorrupted,
)


def test_event_registry_build() -> None:
    """Verifies that the EventRegistry compiles all known module events correctly."""
    registry = EventRegistry.build()

    # Assert namespaces match the KNOWN_NAMESPACES list
    assert registry.namespaces() == KNOWN_NAMESPACES

    # Check some required Phase-A events are registered
    assert registry.contains("factory.genver.iteration_start")
    assert registry.contains("factory.genver.promote_succeeded")
    assert registry.contains("factory.ledger.entry_inserted")
    assert registry.contains("factory.budget.cap_exhausted")
    assert registry.contains("factory.state_machine.cycle_complete")
    assert registry.contains("factory.surrogate.ood_escalation")

    # Assert that namespaces events_for returns the registered subset
    genver_events = registry.events_for("factory.genver")
    assert "factory.genver.iteration_start" in genver_events
    assert len(genver_events) >= 7


def test_namespace_vs_event_violation(tmp_path: Path) -> None:
    """Confirm taxonomy violations distinguish namespace and suffix failures."""
    registry = EventRegistry.build()
    emitter = TelemetryEmitter(tmp_path, registry, cycle_id="cyc-test")

    # Unknown namespace
    with pytest.raises(EventTaxonomyViolation) as exc_info_ns:
        emitter.emit("factory.unknown_ns.some_event", {})
    assert "unknown namespace" in str(exc_info_ns.value)

    # Known namespace but unregistered suffix
    with pytest.raises(EventTaxonomyViolation) as exc_info_suffix:
        emitter.emit("factory.genver.nonexistent_event_suffix", {})
    assert "unregistered event" in str(exc_info_suffix.value)


def test_soft_dependency_degradation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify emit degrades to no-op without an active emitter."""
    # 1. No active emitter -> should not raise or log error, just debug log drop
    emit("factory.genver.iteration_start", {"index": 1})

    # 2. Set environment override -> should return immediately without using emitter
    monkeypatch.setenv("FACTORY_TELEMETRY_DISABLED", "1")
    registry = EventRegistry.build()

    # We create an emitter that would raise on emit to prove it is bypassed
    class RaisingEmitter(TelemetryEmitter):
        def emit(
            self,
            event: str,
            payload: dict[str, object],
            level: str = "info",
        ) -> None:
            del event, payload, level
            raise ValueError("Should not be called")

    emitter = RaisingEmitter(tmp_path, registry, cycle_id="cyc-test")
    set_active_emitter(emitter)

    try:
        # Should degrade to no-op silently
        emit("factory.genver.iteration_start", {"index": 1})
    finally:
        set_active_emitter(None)


def test_corrupted_line_handling(tmp_path: Path) -> None:
    """Verifies that corrupted log lines are skipped and logged to side-channels."""
    cycle_dir = tmp_path / "cyc-corrupt"
    cycle_dir.mkdir()
    log_file = cycle_dir / "cycle.jsonl"

    # Write one valid line, one corrupted line, and another valid line
    log_file.write_text(
        json.dumps(
            {
                "ts": "2026-05-23T00:00:00Z",
                "cycle_id": "cyc-corrupt",
                "module": "factory.genver",
                "level": "info",
                "event": "factory.genver.iteration_start",
                "payload": {"idx": 1},
            }
        )
        + "\n"
        + "this-is-not-valid-json-and-will-corrupt-the-line\n"
        + json.dumps(
            {
                "ts": "2026-05-23T00:00:02Z",
                "cycle_id": "cyc-corrupt",
                "module": "factory.genver",
                "level": "info",
                "event": "factory.genver.iteration_end",
                "payload": {"idx": 1},
            }
        )
        + "\n"
    )

    query = AuditQuery(runs_dir=tmp_path)
    records = list(query.by_cycle("cyc-corrupt"))

    # Valid lines are successfully parsed
    assert len(records) == 2
    assert records[0]["event"] == "factory.genver.iteration_start"
    assert records[1]["event"] == "factory.genver.iteration_end"

    # Side-channel corruption log created
    side_log = cycle_dir / "corrupt.jsonl"
    assert side_log.exists()
    corrupt_content = side_log.read_text()
    assert "this-is-not-valid-json-and-will-corrupt-the-line" in corrupt_content


def test_export_and_query_by_hypothesis(tmp_path: Path) -> None:
    """Tests querying via AuditQuery by_hypothesis resolving through SQLite ledger."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # 1. Setup mock SQLite database simulating the EvidenceLedger table
    db_path = tmp_path / "ledger.db"
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            """
            CREATE TABLE entries (
                entry_hash TEXT PRIMARY KEY,
                hypothesis_id TEXT,
                cycle_id TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO entries (entry_hash, hypothesis_id, cycle_id) VALUES (?, ?, ?)",
            ("hash1", "hyp-001", "cyc-alpha"),
        )
        conn.execute(
            "INSERT INTO entries (entry_hash, hypothesis_id, cycle_id) VALUES (?, ?, ?)",
            ("hash2", "hyp-001", "cyc-beta"),
        )
    conn.close()

    # 2. Write cycle logs
    cyc_alpha_dir = runs_dir / "cyc-alpha"
    cyc_alpha_dir.mkdir()
    (cyc_alpha_dir / "cycle.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-05-23T01:00:00Z",
                "cycle_id": "cyc-alpha",
                "module": "factory.genver",
                "level": "info",
                "event": "factory.genver.iteration_start",
                "payload": {"cycle": "alpha"},
            }
        )
        + "\n"
    )

    cyc_beta_dir = runs_dir / "cyc-beta"
    cyc_beta_dir.mkdir()
    (cyc_beta_dir / "cycle.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-05-23T02:00:00Z",
                "cycle_id": "cyc-beta",
                "module": "factory.genver",
                "level": "info",
                "event": "factory.genver.iteration_end",
                "payload": {"cycle": "beta"},
            }
        )
        + "\n"
    )

    # 3. Perform query
    query = AuditQuery(runs_dir=runs_dir, ledger_db_path=db_path)
    records = list(query.by_hypothesis(HypothesisId("hyp-001")))

    assert len(records) == 2
    assert records[0]["cycle_id"] == "cyc-alpha"
    assert records[1]["cycle_id"] == "cyc-beta"


def test_aggregate_jsonl_events_writes_deterministic_snapshot(tmp_path: Path) -> None:
    log_file = tmp_path / "cycle.jsonl"
    log_file.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "ts": "2026-05-23T00:00:00Z",
                        "cycle_id": "c1",
                        "module": "factory.writer",
                        "level": "info",
                        "event": "factory.writer.draft_created",
                        "payload": {"cost_usd": 0.25},
                    }
                ),
                json.dumps(
                    {
                        "ts": "2026-05-23T00:00:01Z",
                        "cycle_id": "c1",
                        "module": "factory.writer",
                        "level": "info",
                        "event": "factory.writer.draft_created",
                        "payload": {"total_cost_usd": 0.5},
                    }
                ),
            )
        )
        + "\n"
    )

    output_dir = tmp_path / "aggregate"
    snapshot = aggregate_jsonl_events((log_file,), output_dir)

    assert snapshot.total_events == 2
    assert snapshot.event_counts == (("factory.writer.draft_created", 2),)
    assert snapshot.module_costs[0].module == "factory.writer"
    assert snapshot.module_costs[0].cost_usd == 0.75
    assert (output_dir / "aggregate_snapshot.json").exists()
    assert (output_dir / "module_costs.csv").read_text().splitlines()[0] == (
        "module,event_count,cost_usd"
    )


def test_aggregate_jsonl_events_surfaces_corrupted_lines_loudly(tmp_path: Path) -> None:
    log_file = tmp_path / "cycle.jsonl"
    log_file.write_text("not-json\n", encoding="utf-8")

    with pytest.raises(JSONLineCorrupted, match="invalid JSON"):
        aggregate_jsonl_events((log_file,), tmp_path / "aggregate")
