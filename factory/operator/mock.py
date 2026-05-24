"""Mock implementations for the operator HTTP API endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from factory.artifacts.results import (
    CouncilId,
    CouncilVerdict,
    DissentEntry,
    EvidenceLedgerEntry,
    EvidenceResult,
    PersonaName,
    ProvenanceBlock,
    RelitigationTrigger,
    RunReport,
    UncertaintyBlock,
)
from factory.operator.responses import (
    ActiveCycleInfo,
    CatalogDetailResponse,
    CatalogListResponse,
    CycleDetailResponse,
    G6QueueResponse,
    GatePipelineResponse,
    LedgerDetailResponse,
    LedgerSearchResponse,
    MissionControlResponse,
    RecentVerdictInfo,
    ReportDetailResponse,
    SettingsResponse,
    VerdictDetailResponse,
)

logger = logging.getLogger("factory.operator.mock")

_ZERO_HASH = "0" * 64
_MOCK_TIME = datetime(2026, 5, 23, 16, 0, 0, tzinfo=UTC)


def get_mock_mission_control() -> MissionControlResponse:
    """Return mock mission control payload."""
    active = ActiveCycleInfo(
        cycle_id="mock-cycle-1",
        hypothesis_id="H-STELLA-001",
        title="Quark-Gluon Plasma Dynamics under DESC optimization",
        current_gate="G3 — Surrogate",
        elapsed_seconds=1204.5,
        cost_usd=12.45,
        gate_states=("passed", "passed", "passed", "running", "pending", "pending", "pending"),
    )
    verdict = RecentVerdictInfo(
        timestamp=_MOCK_TIME,
        hypothesis_id="H-STELLA-001",
        gate_name="G2 — Worthiness",
        outcome="passed",
        snippet="Deliberation consensus resolved with minor dissent.",
    )
    return MissionControlResponse(
        stale=False,
        served_at=datetime.now(UTC),
        factory_state="running",
        current_cycle_id="mock-cycle-1",
        current_hypothesis_id="H-STELLA-001",
        elapsed_seconds=1204.5,
        today_cost_usd=12.45,
        daily_cap_usd=100.0,
        remaining_budget_usd=87.55,
        active_cycles=(active,),
        recent_verdicts=(verdict,),
    )


def get_mock_cycle_detail(cycle_id: str) -> CycleDetailResponse:
    """Return mock cycle detail payload."""
    return CycleDetailResponse(
        stale=False,
        served_at=datetime.now(UTC),
        cycle_id=cycle_id,
        hypothesis_id="H-STELLA-001",
        status="running",
        elapsed_seconds=1204.5,
        cost_usd=12.45,
        logs="[2026-05-23T16:00:00] Initializing cycle mock-cycle-1...\n[2026-05-23T16:05:00] Gate G1 passed.\n[2026-05-23T16:10:00] Running gate G3 surrogate pre-screening...",
        artifacts={"GapCandidate.json": _ZERO_HASH, "HypothesisSpec.json": _ZERO_HASH},
    )


def get_mock_gate_pipeline(cycle_id: str) -> GatePipelineResponse:
    """Return mock gate pipeline payload."""
    gates = (
        {"name": "G0 — Domain", "status": "passed", "duration": 12.0},
        {"name": "G1 — Falsifiability", "status": "passed", "duration": 34.0},
        {"name": "G1.5 — Simulability", "status": "passed", "duration": 22.0},
        {"name": "G2 — Worthiness", "status": "passed", "duration": 180.0},
        {"name": "G2.5 — Tractability", "status": "passed", "duration": 45.0},
        {"name": "G3 — Surrogate", "status": "running", "duration": 15.0},
        {"name": "G4 — Validation", "status": "pending", "duration": 0.0},
        {"name": "G5 — Interpretation", "status": "pending", "duration": 0.0},
        {"name": "G6 — Human", "status": "pending", "duration": 0.0},
    )
    return GatePipelineResponse(
        stale=False, served_at=datetime.now(UTC), cycle_id=cycle_id, gates=gates
    )


def get_mock_verdict(session_id: str) -> VerdictDetailResponse:
    """Return mock verdict payload."""
    dissent = DissentEntry(
        model_id="anthropic/claude-opus-4.7",
        persona=PersonaName.PESSIMIST,
        view="reject",
        rationale="Uncertainty quantification method fails to bound edge cases.",
    )
    verdict = CouncilVerdict(
        artifact_type="CouncilVerdict",
        created_at=_MOCK_TIME,
        provenance_hash=_ZERO_HASH,
        parent_hashes=(),
        council_id=CouncilId.C1_WORTHINESS,
        question="Is Quark-Gluon Plasma Dynamics worthy of C1 gate?",
        model_lineup=("openai/gpt-5.5", "anthropic/claude-opus-4.7"),
        persona_assignment={
            "openai/gpt-5.5": PersonaName.VISIONARY,
            "anthropic/claude-opus-4.7": PersonaName.PESSIMIST,
        },
        chairman_model="openai/gpt-5.5",
        majority_view="Approved. The proposed model scales well and shows convergence.",
        preserved_dissents=(dissent,),
        chairman_decision="qualified",
        total_cost_usd=0.045,
        wall_clock_seconds=12.4,
        session_id=session_id,
    )
    return VerdictDetailResponse(stale=False, served_at=datetime.now(UTC), verdict=verdict)


def get_mock_catalog() -> CatalogListResponse:
    """Return mock catalog list."""
    return CatalogListResponse(stale=False, served_at=datetime.now(UTC), simulators=("sim_a", "sim_b"))


def get_mock_catalog_detail(simulator_id: str) -> CatalogDetailResponse:
    """Return mock catalog detail."""
    return CatalogDetailResponse(
        stale=False,
        served_at=datetime.now(UTC),
        simulator_id=simulator_id,
        version="1.0.0",
        license="MIT",
        maintenance_status="active",
        capabilities=("force_balance_residual", "solver_residual_norm"),
        container_sha="sha256:reference-mock-sha",
        dependencies={"python": ">=3.12", "numpy": ">=1.26.0"},
    )


def _create_mock_ledger_entry(hypothesis_id: str) -> EvidenceLedgerEntry:
    prov = ProvenanceBlock(
        code_hash=_ZERO_HASH,
        env_hash=_ZERO_HASH,
        input_hash=_ZERO_HASH,
        seed=42,
        simulator_id="sim_a",
        simulator_version="1.0.0",
        container_sha="sha256:mock-sha",
    )
    unc = UncertaintyBlock(
        metric_name="force_balance_residual",
        point_estimate=0.15,
        ci_lower=0.12,
        ci_upper=0.18,
        ci_method="t_interval",
        n_seeds=5,
    )
    trigger = RelitigationTrigger(
        condition="diverges",
        check_fn="diverge_check",
        last_evaluated_at=_MOCK_TIME,
        currently_satisfied=False,
    )
    return EvidenceLedgerEntry(
        artifact_type="EvidenceLedgerEntry",
        created_at=_MOCK_TIME,
        provenance_hash=_ZERO_HASH,
        parent_hashes=(),
        hypothesis_id=hypothesis_id,
        result=EvidenceResult.PASSED,
        terminal_state="G5 passed",
        provenance=prov,
        uncertainty=unc,
        relitigate_if=(trigger,),
        council_verdict_hashes=(_ZERO_HASH,),
        run_report_hash=_ZERO_HASH,
        surprise_bits=2.4,
    )


def get_mock_ledger_search() -> LedgerSearchResponse:
    """Return mock ledger search payload."""
    entry = _create_mock_ledger_entry("H-STELLA-001")
    return LedgerSearchResponse(
        stale=False, served_at=datetime.now(UTC), results=(entry,), total_count=1
    )


def get_mock_ledger_detail(entry_id: str) -> LedgerDetailResponse:
    """Return mock ledger detail."""
    entry = _create_mock_ledger_entry(entry_id)
    return LedgerDetailResponse(stale=False, served_at=datetime.now(UTC), entry=entry)


def _create_mock_report(report_id: str) -> RunReport:
    return RunReport(
        artifact_type="RunReport",
        created_at=_MOCK_TIME,
        provenance_hash=report_id,
        parent_hashes=(),
        hypothesis_id="H-STELLA-001",
        title="Autonomous Discovery of Quark-Gluon Plasma Dynamics",
        abstract="Stellarator optimization routines are enhanced under self-consistent MHD fluid model derivations...",
        latex_source="\\documentclass{article}\n\\begin{document}\n\\title{Autonomous Discovery}\n\\maketitle\n\\end{document}",
        figure_paths=("runs/mock-cycle-1/figures/fig1.png",),
        bibtex="@article{stella2026,\n  title={Autonomous Discovery},\n  author={StellaEvolve},\n  year={2026}\n}",
        embedded_council_verdict_hashes=(_ZERO_HASH,),
        g6_approved=False,
        g6_approver=None,
        g6_approved_at=None,
    )


def get_mock_report(report_id: str) -> ReportDetailResponse:
    """Return mock report detail."""
    return ReportDetailResponse(
        stale=False, served_at=datetime.now(UTC), report=_create_mock_report(report_id)
    )


def get_mock_approval_queue() -> G6QueueResponse:
    """Return mock approval queue."""
    return G6QueueResponse(
        stale=False, served_at=datetime.now(UTC), pending_reports=(_create_mock_report(_ZERO_HASH),)
    )


def get_mock_settings() -> SettingsResponse:
    """Return mock settings payload."""
    return SettingsResponse(
        stale=False,
        served_at=datetime.now(UTC),
        budgets={
            "aggregate_cap_usd": 1000.0,
            "aggregate_burn_usd": 120.50,
            "daily_cap_usd": 100.0,
            "daily_burn_usd": 12.45,
            "per_hypothesis_cap_usd": 50.0,
        },
        rate_limits={"tokens_per_minute": 80000, "requests_per_minute": 200},
        active_lineup=(
            {"model_id": "openai/gpt-5.5", "persona": "visionary", "enabled": True},
            {"model_id": "anthropic/claude-opus-4.7", "persona": "pessimist", "enabled": True},
        ),
    )
