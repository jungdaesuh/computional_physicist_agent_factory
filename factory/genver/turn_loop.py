"""Bounded multi-turn ReAct execution loop."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from factory.genver.tools import GenVerToolName, ToolCall, ToolValidation, validate_tool_call

MAX_TURNS = 25


class TurnStatus(StrEnum):
    """Terminal status for a ReAct turn loop."""

    FINISHED = "finished"
    MAX_TURNS_EXHAUSTED = "max_turns_exhausted"
    TOOL_REJECTED = "tool_rejected"


@dataclass(frozen=True)
class TurnObservation:
    """Observed output from one ReAct tool call."""

    content: str


@dataclass(frozen=True)
class TurnRequest:
    """Agent output for one turn."""

    thought: str
    tool_call: ToolCall


@dataclass(frozen=True)
class TurnRecord:
    """Immutable record of one executed ReAct turn."""

    turn_index: int
    thought: str
    tool_call: ToolCall
    observation: TurnObservation


@dataclass(frozen=True)
class TurnLoopState:
    """State passed to the agent and refresh_state callback."""

    prompt: str
    records: tuple[TurnRecord, ...] = ()


@dataclass(frozen=True)
class TurnLoopResult:
    """Final bounded loop result."""

    status: TurnStatus
    records: tuple[TurnRecord, ...]
    diagnostic: str


class GenVerAgent(Protocol):
    """Callable agent protocol without coupling the loop to a concrete LLM client."""

    def __call__(self, state: TurnLoopState) -> TurnRequest:
        """Return the next ReAct request for the current state."""
        ...


ToolExecutor = Callable[[ToolCall], TurnObservation]
RefreshState = Callable[[TurnLoopState], TurnLoopState]


def run_turn_loop(
    initial_prompt: str,
    agent: GenVerAgent,
    execute_tool: ToolExecutor,
    *,
    refresh_state: RefreshState | None = None,
    max_turns: int = MAX_TURNS,
) -> TurnLoopResult:
    """Run a bounded ReAct loop with validation before every tool dispatch."""
    state = TurnLoopState(prompt=initial_prompt)
    for turn_index in range(max_turns):
        state = state if refresh_state is None else refresh_state(state)
        request = agent(state)
        validation = validate_tool_call(request.tool_call)
        if not validation.valid:
            return _rejected(state.records, validation)

        observation = execute_tool(request.tool_call)
        record = TurnRecord(
            turn_index=turn_index,
            thought=request.thought,
            tool_call=request.tool_call,
            observation=observation,
        )
        records = (*state.records, record)
        if request.tool_call.name == GenVerToolName.FINISH:
            return TurnLoopResult(TurnStatus.FINISHED, records, observation.content)
        state = TurnLoopState(prompt=state.prompt, records=records)

    return TurnLoopResult(
        status=TurnStatus.MAX_TURNS_EXHAUSTED,
        records=state.records,
        diagnostic=f"reached MAX_TURNS={max_turns}",
    )


def _rejected(records: Sequence[TurnRecord], validation: ToolValidation) -> TurnLoopResult:
    return TurnLoopResult(
        status=TurnStatus.TOOL_REJECTED,
        records=tuple(records),
        diagnostic=validation.diagnostic,
    )


__all__ = [
    "GenVerAgent",
    "MAX_TURNS",
    "RefreshState",
    "ToolExecutor",
    "TurnLoopResult",
    "TurnLoopState",
    "TurnObservation",
    "TurnRecord",
    "TurnRequest",
    "TurnStatus",
    "run_turn_loop",
]
