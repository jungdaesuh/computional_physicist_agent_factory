"""Async cycle orchestration for independent factory gate work."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

GateName = Literal["G1", "G2", "G3", "G4", "G5", "G6"]
GateStatus = Literal["passed", "failed", "skipped"]


@dataclass(frozen=True, slots=True)
class CycleTaskInput:
    """Immutable input for one cycle; gate workers receive copies of this context."""

    cycle_id: str
    hypothesis_id: str
    gates: tuple[GateName, ...]
    state_payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class GateTaskInput:
    """Single gate execution request derived from one cycle input."""

    cycle_id: str
    hypothesis_id: str
    gate: GateName
    state_payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class GateTaskResult:
    """Result emitted by one gate worker."""

    gate: GateName
    status: GateStatus
    detail: str


@dataclass(frozen=True, slots=True)
class CycleTaskResult:
    """Deterministic cycle result with gate outputs ordered by the input gate list."""

    cycle_id: str
    hypothesis_id: str
    gate_results: tuple[GateTaskResult, ...]

    @property
    def completed_gates(self) -> tuple[GateName, ...]:
        """Return gates that reached a terminal non-skipped status."""
        return tuple(
            result.gate for result in self.gate_results if result.status in {"passed", "failed"}
        )


class GateExecutor(Protocol):
    """Callable protocol for async gate execution."""

    def __call__(self, task_input: GateTaskInput) -> Coroutine[object, object, GateTaskResult]:
        """Execute one gate task and return its typed result."""


async def run_cycle(task_input: CycleTaskInput, gate_executor: GateExecutor) -> CycleTaskResult:
    """Run all requested gates for one cycle with TaskGroup fail-fast semantics."""
    tasks: dict[GateName, asyncio.Task[GateTaskResult]] = {}
    async with asyncio.TaskGroup() as task_group:
        for gate in task_input.gates:
            gate_input = GateTaskInput(
                cycle_id=task_input.cycle_id,
                hypothesis_id=task_input.hypothesis_id,
                gate=gate,
                state_payload=dict(task_input.state_payload),
            )
            tasks[gate] = task_group.create_task(gate_executor(gate_input))

    return CycleTaskResult(
        cycle_id=task_input.cycle_id,
        hypothesis_id=task_input.hypothesis_id,
        gate_results=tuple(tasks[gate].result() for gate in task_input.gates),
    )


async def run_cycles_concurrently(
    cycle_inputs: Sequence[CycleTaskInput],
    gate_executor: GateExecutor,
) -> tuple[CycleTaskResult, ...]:
    """Run multiple cycles concurrently and preserve caller input order in the result."""

    def cycle_runner(cycle_input: CycleTaskInput) -> Coroutine[object, object, CycleTaskResult]:
        return run_cycle(cycle_input, gate_executor)

    async with asyncio.TaskGroup() as task_group:
        tasks = tuple(
            task_group.create_task(cycle_runner(cycle_input)) for cycle_input in cycle_inputs
        )
    return tuple(task.result() for task in tasks)
