"""Public implementation contract for the state_machine module."""

from __future__ import annotations

from factory.module_contracts import ModuleContract
from factory.state_machine.c5 import (
    C5CadenceResult,
    DomainShift,
    StrategyArchiveSummary,
    parse_c5_cadence,
)
from factory.state_machine.checkpoint import (
    CheckpointSnapshot,
    ResumePlan,
    build_resume_plan,
    load_checkpoint,
    save_checkpoint,
)
from factory.state_machine.concurrency import (
    CycleTaskInput,
    CycleTaskResult,
    GateTaskInput,
    GateTaskResult,
    run_cycle,
    run_cycles_concurrently,
)
from factory.state_machine.literature import (
    LiteratureDiscoveryRequest,
    LiteratureDiscoveryResult,
    run_literature_discovery,
)

MODULE_CONTRACT = ModuleContract(
    module_name="state_machine",
    spec_id="003",
    responsibility="Route immutable artifacts through the factory gates and terminal states.",
    required_inputs=(
        "FactoryState",
        "GateOutcome",
    ),
    produced_outputs=("FactoryStateTransition",),
)


def describe_contract() -> ModuleContract:
    """Return the stable public contract for this module."""
    return MODULE_CONTRACT


__all__ = [
    "C5CadenceResult",
    "CheckpointSnapshot",
    "CycleTaskInput",
    "CycleTaskResult",
    "DomainShift",
    "GateTaskInput",
    "GateTaskResult",
    "LiteratureDiscoveryRequest",
    "LiteratureDiscoveryResult",
    "MODULE_CONTRACT",
    "ResumePlan",
    "StrategyArchiveSummary",
    "build_resume_plan",
    "describe_contract",
    "load_checkpoint",
    "parse_c5_cadence",
    "run_literature_discovery",
    "run_cycle",
    "run_cycles_concurrently",
    "save_checkpoint",
]
