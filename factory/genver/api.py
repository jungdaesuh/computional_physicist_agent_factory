"""Public implementation contract for the genver module."""

from __future__ import annotations

from factory.genver.compaction import (
    AUTO_COMPACT_TOKEN_LIMIT,
    CompactedContext,
    ContextBudget,
    ContextMessage,
    compact_messages,
    context_budget,
    should_auto_compact,
)
from factory.genver.promote import (
    PromotionCandidate,
    PromotionResult,
    StageResult,
    ValidationStage,
    promote_candidate,
    validate_candidate,
)
from factory.genver.tools import (
    GenVerToolName,
    ToolCall,
    ToolSpec,
    ToolValidation,
    react_tool_surface,
    validate_python_ast,
    validate_sql,
    validate_tool_call,
)
from factory.genver.turn_loop import (
    MAX_TURNS,
    GenVerAgent,
    TurnLoopResult,
    TurnLoopState,
    TurnObservation,
    TurnRecord,
    TurnRequest,
    TurnStatus,
    run_turn_loop,
)
from factory.module_contracts import ModuleContract

MODULE_CONTRACT = ModuleContract(
    module_name="genver",
    spec_id="008",
    responsibility="Coordinate bounded generator-verifier code attempts for an experiment.",
    required_inputs=(
        "ExperimentSpec",
        "Budget",
    ),
    produced_outputs=("GenVerResult",),
)


def describe_contract() -> ModuleContract:
    """Return the stable public contract for this module."""
    return MODULE_CONTRACT


__all__ = [
    "AUTO_COMPACT_TOKEN_LIMIT",
    "CompactedContext",
    "ContextBudget",
    "ContextMessage",
    "GenVerAgent",
    "GenVerToolName",
    "MAX_TURNS",
    "MODULE_CONTRACT",
    "PromotionCandidate",
    "PromotionResult",
    "StageResult",
    "ToolCall",
    "ToolSpec",
    "ToolValidation",
    "TurnLoopResult",
    "TurnLoopState",
    "TurnObservation",
    "TurnRecord",
    "TurnRequest",
    "TurnStatus",
    "ValidationStage",
    "compact_messages",
    "context_budget",
    "describe_contract",
    "promote_candidate",
    "react_tool_surface",
    "run_turn_loop",
    "should_auto_compact",
    "validate_candidate",
    "validate_python_ast",
    "validate_sql",
    "validate_tool_call",
]
