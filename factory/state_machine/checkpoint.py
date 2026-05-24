"""Atomic checkpoint persistence and replay-free resume planning."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from factory.state_machine.concurrency import GateName
from factory.state_machine.errors import StateMachineError

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_GATE_NAMES: dict[str, GateName] = {
    "G1": "G1",
    "G2": "G2",
    "G3": "G3",
    "G4": "G4",
    "G5": "G5",
    "G6": "G6",
}


@dataclass(frozen=True, slots=True)
class CheckpointSnapshot:
    """Durable cycle checkpoint; completed gates are never replayed on resume."""

    cycle_id: str
    hypothesis_id: str
    completed_gates: tuple[GateName, ...]
    state_payload: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ResumePlan:
    """Next executable gates computed from a checkpoint and canonical gate order."""

    cycle_id: str
    hypothesis_id: str
    pending_gates: tuple[GateName, ...]
    state_payload: dict[str, JsonValue]


def save_checkpoint(path: Path, snapshot: CheckpointSnapshot) -> None:
    """Atomically write one checkpoint JSON document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    payload = {
        "cycle_id": snapshot.cycle_id,
        "hypothesis_id": snapshot.hypothesis_id,
        "completed_gates": list(snapshot.completed_gates),
        "state_payload": snapshot.state_payload,
    }
    temp_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, path)


def load_checkpoint(path: Path) -> CheckpointSnapshot:
    """Load and validate a checkpoint JSON document."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise StateMachineError(f"Checkpoint must be a JSON object: {path}")

    completed_gates = payload.get("completed_gates")
    state_payload = payload.get("state_payload")
    cycle_id = payload.get("cycle_id")
    hypothesis_id = payload.get("hypothesis_id")
    if not isinstance(cycle_id, str) or not isinstance(hypothesis_id, str):
        raise StateMachineError(f"Checkpoint missing cycle_id or hypothesis_id: {path}")
    if not isinstance(completed_gates, list) or not all(
        isinstance(gate, str) for gate in completed_gates
    ):
        raise StateMachineError(f"Checkpoint completed_gates must be a string list: {path}")
    if not isinstance(state_payload, dict):
        raise StateMachineError(f"Checkpoint state_payload must be an object: {path}")

    return CheckpointSnapshot(
        cycle_id=cycle_id,
        hypothesis_id=hypothesis_id,
        completed_gates=tuple(_gate_name(gate) for gate in completed_gates),
        state_payload=state_payload,
    )


def build_resume_plan(
    checkpoint: CheckpointSnapshot,
    canonical_gate_order: tuple[GateName, ...],
) -> ResumePlan:
    """Return only gates that are not already completed in the checkpoint."""
    completed = frozenset(checkpoint.completed_gates)
    return ResumePlan(
        cycle_id=checkpoint.cycle_id,
        hypothesis_id=checkpoint.hypothesis_id,
        pending_gates=tuple(gate for gate in canonical_gate_order if gate not in completed),
        state_payload=dict(checkpoint.state_payload),
    )


def _gate_name(value: str) -> GateName:
    gate = _GATE_NAMES.get(value)
    if gate is None:
        raise StateMachineError(f"Unknown checkpoint gate: {value}")
    return gate
