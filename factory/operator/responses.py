"""Pydantic response models for the operator HTTP API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from factory.artifacts.results import CouncilVerdict, EvidenceLedgerEntry, RunReport


class BaseResponse(BaseModel):
    """Common base for all operator API responses with staleness metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stale: bool
    served_at: datetime


class ActiveCycleInfo(BaseModel):
    """Summary of a cycle currently executing in the state machine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cycle_id: str
    hypothesis_id: str
    title: str
    current_gate: str
    elapsed_seconds: float
    cost_usd: float
    gate_states: tuple[str, ...]  # list of gate status strings (e.g. "passed", "running")


class RecentVerdictInfo(BaseModel):
    """Summary of a recently generated gate verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    hypothesis_id: str
    gate_name: str
    outcome: str
    snippet: str


class MissionControlResponse(BaseResponse):
    """Response payload for GET /api/mission_control."""

    factory_state: Literal["running", "paused", "human-gated", "idle"]
    current_cycle_id: str | None
    current_hypothesis_id: str | None
    elapsed_seconds: float | None
    today_cost_usd: float
    daily_cap_usd: float
    remaining_budget_usd: float
    active_cycles: tuple[ActiveCycleInfo, ...]
    recent_verdicts: tuple[RecentVerdictInfo, ...]


class CycleDetailResponse(BaseResponse):
    """Response payload for GET /api/cycles/{cycle_id}."""

    cycle_id: str
    hypothesis_id: str
    status: str
    elapsed_seconds: float
    cost_usd: float
    logs: str
    artifacts: dict[str, str]  # filename -> hash mapping


class GatePipelineResponse(BaseResponse):
    """Response payload for GET /api/cycles/{cycle_id}/gates."""

    cycle_id: str
    gates: tuple[dict[str, Any], ...]  # gate list details


class VerdictDetailResponse(BaseResponse):
    """Response payload for GET /api/verdicts/{session_id}."""

    verdict: CouncilVerdict


class CatalogListResponse(BaseResponse):
    """Response payload for GET /api/catalog."""

    simulators: tuple[str, ...]


class CatalogDetailResponse(BaseResponse):
    """Response payload for GET /api/catalog/{simulator_id}."""

    simulator_id: str
    version: str
    license: str
    maintenance_status: str
    capabilities: tuple[str, ...]
    container_sha: str
    dependencies: dict[str, str]


class LedgerSearchResponse(BaseResponse):
    """Response payload for GET /api/ledger/search."""

    results: tuple[EvidenceLedgerEntry, ...]
    total_count: int


class LedgerDetailResponse(BaseResponse):
    """Response payload for GET /api/ledger/{entry_id}."""

    entry: EvidenceLedgerEntry


class ReportDetailResponse(BaseResponse):
    """Response payload for GET /api/reports/{report_id}."""

    report: RunReport


class G6QueueResponse(BaseResponse):
    """Response payload for GET /api/approval_queue."""

    pending_reports: tuple[RunReport, ...]


class SettingsResponse(BaseResponse):
    """Response payload for GET /api/settings."""

    budgets: dict[str, Any]
    rate_limits: dict[str, Any]
    active_lineup: tuple[dict[str, Any], ...]
