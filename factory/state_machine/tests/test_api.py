"""Unit tests for Phase B state-machine surfaces."""

from __future__ import annotations

import asyncio
from pathlib import Path

from factory.state_machine.api import (
    CheckpointSnapshot,
    CycleTaskInput,
    GateTaskInput,
    GateTaskResult,
    LiteratureDiscoveryRequest,
    StrategyArchiveSummary,
    build_resume_plan,
    load_checkpoint,
    parse_c5_cadence,
    run_cycles_concurrently,
    run_literature_discovery,
    save_checkpoint,
)


def test_run_cycles_concurrently_preserves_order_and_payload_isolation() -> None:
    seen_payloads: list[dict[str, object]] = []

    async def gate_executor(task_input: GateTaskInput) -> GateTaskResult:
        task_input.state_payload["mutated"] = task_input.gate
        seen_payloads.append(task_input.state_payload)
        return GateTaskResult(gate=task_input.gate, status="passed", detail=task_input.cycle_id)

    cycle_inputs = (
        CycleTaskInput("cycle-b", "hyp-1", ("G1", "G2"), {"seed": "b"}),
        CycleTaskInput("cycle-a", "hyp-2", ("G1",), {"seed": "a"}),
    )

    results = asyncio.run(run_cycles_concurrently(cycle_inputs, gate_executor))

    assert tuple(result.cycle_id for result in results) == ("cycle-b", "cycle-a")
    assert results[0].completed_gates == ("G1", "G2")
    assert cycle_inputs[0].state_payload == {"seed": "b"}
    assert seen_payloads[0] is not seen_payloads[1]


def test_parse_c5_cadence_extracts_domain_shifts_and_no_consensus() -> None:
    no_consensus = parse_c5_cadence(
        (StrategyArchiveSummary(strategy_sha="s0", summary_md="No agreement."),)
    )
    assert no_consensus.outcome == "no_consensus"
    assert no_consensus.allowed_domain_shifts == ()

    parsed = parse_c5_cadence(
        (
            StrategyArchiveSummary(
                strategy_sha="s1",
                summary_md="Allowed-domain-shift: stellarator transport | evidence improved",
            ),
        )
    )

    assert parsed.outcome == "domain_shift"
    assert parsed.allowed_domain_shifts[0].domain == "stellarator transport"
    assert parsed.allowed_domain_shifts[0].rationale == "evidence improved"


def test_checkpoint_resume_does_not_replay_completed_gates(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    snapshot = CheckpointSnapshot(
        cycle_id="cycle-1",
        hypothesis_id="hyp-1",
        completed_gates=("G1", "G2", "G4"),
        state_payload={"cursor": "after-g4"},
    )

    save_checkpoint(checkpoint_path, snapshot)
    loaded = load_checkpoint(checkpoint_path)
    plan = build_resume_plan(loaded, ("G1", "G2", "G3", "G4", "G5", "G6"))

    assert loaded == snapshot
    assert plan.pending_gates == ("G3", "G5", "G6")
    assert plan.state_payload == {"cursor": "after-g4"}


def test_state_machine_literature_surface_runs_mock_discovery(tmp_path: Path) -> None:
    result = run_literature_discovery(
        LiteratureDiscoveryRequest(
            seed_query="stellarator coil",
            graph_db_path=tmp_path / "graph.sqlite",
            paper_store_root=tmp_path / "papers",
            max_depth=1,
            branch_factor=1,
            mock_mode=True,
        )
    )

    assert result.source_work_ids == ("W-MOCK-ROOT",)
    assert result.promoted_work_ids == ("W-MOCK-ROOT",)
    assert result.gap_types == (
        "structural_hole",
        "methodology_transfer",
        "contradiction",
        "negative_result",
    )
    assert result.graph_summary["works"] == 1
