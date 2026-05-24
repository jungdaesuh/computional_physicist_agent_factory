"""Deterministic JSONL telemetry aggregation with loud corruption errors."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from factory.telemetry.errors import JSONLineCorrupted


@dataclass(frozen=True, slots=True)
class ModuleCostRow:
    """Aggregate cost for one module namespace."""

    module: str
    event_count: int
    cost_usd: float


@dataclass(frozen=True, slots=True)
class TelemetryAggregateSnapshot:
    """Deterministic aggregate view over a fixed JSONL event set."""

    total_events: int
    event_counts: tuple[tuple[str, int], ...]
    module_costs: tuple[ModuleCostRow, ...]


@dataclass(frozen=True, slots=True)
class TelemetryEventRecord:
    """Validated telemetry event record used by aggregate reducers."""

    module: str
    event: str
    payload: Mapping[str, object]


def aggregate_jsonl_events(
    jsonl_paths: tuple[Path, ...],
    output_dir: Path,
) -> TelemetryAggregateSnapshot:
    """Read JSONL event files, write aggregate tables, and return the snapshot."""
    records = tuple(_read_event_records(jsonl_paths))
    event_counts: Counter[str] = Counter(record.event for record in records)
    module_counts: Counter[str] = Counter(record.module for record in records)
    module_costs: dict[str, float] = {}

    for record in records:
        cost = record.payload.get("cost_usd", record.payload.get("total_cost_usd"))
        if isinstance(cost, int | float):
            module_costs[record.module] = module_costs.get(record.module, 0.0) + float(cost)

    snapshot = TelemetryAggregateSnapshot(
        total_events=len(records),
        event_counts=tuple(sorted(event_counts.items())),
        module_costs=tuple(
            ModuleCostRow(
                module=module,
                event_count=module_counts[module],
                cost_usd=round(module_costs.get(module, 0.0), 12),
            )
            for module in sorted(module_counts)
        ),
    )
    _write_snapshot(output_dir, snapshot)
    return snapshot


def _read_event_records(paths: tuple[Path, ...]) -> list[TelemetryEventRecord]:
    records: list[TelemetryEventRecord] = []
    for path in sorted(paths):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.strip() == "":
                continue
            parsed: object = _parse_json_line(path, line_number, line)
            records.append(_validate_record(path, line_number, parsed))
    return records


def _parse_json_line(path: Path, line_number: int, line: str) -> object:
    try:
        return json.loads(line)
    except json.JSONDecodeError as error:
        raise JSONLineCorrupted(f"{path}:{line_number}: invalid JSON: {error.msg}") from error


def _validate_record(path: Path, line_number: int, parsed: object) -> TelemetryEventRecord:
    if not isinstance(parsed, dict):
        raise JSONLineCorrupted(f"{path}:{line_number}: event line must be a JSON object")

    required_fields = ("ts", "cycle_id", "module", "level", "event", "payload")
    missing = tuple(field for field in required_fields if field not in parsed)
    if missing:
        joined = ", ".join(missing)
        raise JSONLineCorrupted(f"{path}:{line_number}: missing fields: {joined}")

    module = parsed["module"]
    event = parsed["event"]
    payload = parsed["payload"]
    if not isinstance(module, str) or not isinstance(event, str) or not isinstance(payload, dict):
        raise JSONLineCorrupted(f"{path}:{line_number}: malformed module, event, or payload")

    return TelemetryEventRecord(module=module, event=event, payload=payload)


def _write_snapshot(output_dir: Path, snapshot: TelemetryAggregateSnapshot) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_payload = {
        "total_events": snapshot.total_events,
        "event_counts": list(snapshot.event_counts),
        "module_costs": [
            {
                "module": row.module,
                "event_count": row.event_count,
                "cost_usd": row.cost_usd,
            }
            for row in snapshot.module_costs
        ],
    }
    (output_dir / "aggregate_snapshot.json").write_text(
        json.dumps(snapshot_payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    rows = ["module,event_count,cost_usd"]
    rows.extend(
        f"{row.module},{row.event_count},{row.cost_usd:.12g}" for row in snapshot.module_costs
    )
    (output_dir / "module_costs.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
