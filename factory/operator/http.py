"""FastAPI read-only and control entry HTTP server for the operator module."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from factory.artifacts.results import FactoryControlEvent
from factory.operator.api import create_g6_approval_event, create_g6_rejection_event
from factory.operator.mock import (
    get_mock_approval_queue,
    get_mock_catalog,
    get_mock_catalog_detail,
    get_mock_cycle_detail,
    get_mock_gate_pipeline,
    get_mock_ledger_detail,
    get_mock_ledger_search,
    get_mock_mission_control,
    get_mock_report,
    get_mock_settings,
    get_mock_verdict,
)
from factory.operator.responses import (
    CatalogDetailResponse,
    CatalogListResponse,
    CycleDetailResponse,
    G6QueueResponse,
    GatePipelineResponse,
    LedgerDetailResponse,
    LedgerSearchResponse,
    MissionControlResponse,
    ReportDetailResponse,
    SettingsResponse,
    VerdictDetailResponse,
)

logger = logging.getLogger("factory.operator.http")

app = FastAPI(title="Factory Operator API", version="0.1.0")

# Enable CORS for frontend dashboard local requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ApprovalRequest(BaseModel):
    operator: str
    signature: str


class RejectionRequest(BaseModel):
    operator: str
    reason: str


def is_mock_mode() -> bool:
    """Return True if mock mode is forced via environment."""
    return os.environ.get("FACTORY_MOCK") == "1"


@app.get("/api/mission_control", response_model=MissionControlResponse)
def read_mission_control() -> Any:
    """Screen 1: Mission Control dashboard status."""
    if is_mock_mode():
        return get_mock_mission_control()
    # Live mode fallback
    raise HTTPException(status_code=501, detail="Live mode not implemented")


@app.get("/api/cycles/{cycle_id}", response_model=CycleDetailResponse)
def read_cycle_detail(cycle_id: str) -> Any:
    """Screen 4/5: Cycle details, logs, and artifacts."""
    if is_mock_mode():
        return get_mock_cycle_detail(cycle_id)
    raise HTTPException(status_code=501, detail="Live mode not implemented")


@app.get("/api/cycles/{cycle_id}/gates", response_model=GatePipelineResponse)
def read_gate_pipeline(cycle_id: str) -> Any:
    """Screen 2: Gate pipeline sequence execution status."""
    if is_mock_mode():
        return get_mock_gate_pipeline(cycle_id)
    raise HTTPException(status_code=501, detail="Live mode not implemented")


@app.get("/api/verdicts/{session_id}", response_model=VerdictDetailResponse)
def read_verdict_detail(session_id: str) -> Any:
    """Screen 3: Council deliberation details."""
    if is_mock_mode():
        return get_mock_verdict(session_id)
    raise HTTPException(status_code=501, detail="Live mode not implemented")


@app.get("/api/catalog", response_model=CatalogListResponse)
def read_catalog() -> Any:
    """Screen 6: Simulator catalog list."""
    if is_mock_mode():
        return get_mock_catalog()
    raise HTTPException(status_code=501, detail="Live mode not implemented")


@app.get("/api/catalog/{simulator_id}", response_model=CatalogDetailResponse)
def read_catalog_detail(simulator_id: str) -> Any:
    """Screen 6: Detailed simulator specifications."""
    if is_mock_mode():
        return get_mock_catalog_detail(simulator_id)
    raise HTTPException(status_code=501, detail="Live mode not implemented")


@app.get("/api/ledger/search", response_model=LedgerSearchResponse)
def search_ledger() -> Any:
    """Screen 7: Evidence ledger search browser."""
    if is_mock_mode():
        return get_mock_ledger_search()
    raise HTTPException(status_code=501, detail="Live mode not implemented")


@app.get("/api/ledger/{entry_id}", response_model=LedgerDetailResponse)
def read_ledger_detail(entry_id: str) -> Any:
    """Screen 7: Detailed evidence ledger row."""
    if is_mock_mode():
        return get_mock_ledger_detail(entry_id)
    raise HTTPException(status_code=501, detail="Live mode not implemented")


@app.get("/api/reports/{report_id}", response_model=ReportDetailResponse)
def read_report_detail(report_id: str) -> Any:
    """Screen 8: Auto-generated research paper report."""
    if is_mock_mode():
        return get_mock_report(report_id)
    raise HTTPException(status_code=501, detail="Live mode not implemented")


@app.get("/api/approval_queue", response_model=G6QueueResponse)
def read_approval_queue() -> Any:
    """Screen 9: Queue of preprints awaiting G6 human gate clearance."""
    if is_mock_mode():
        return get_mock_approval_queue()
    raise HTTPException(status_code=501, detail="Live mode not implemented")


@app.get("/api/settings", response_model=SettingsResponse)
def read_settings() -> Any:
    """Screen 11: Configuration settings."""
    if is_mock_mode():
        return get_mock_settings()
    raise HTTPException(status_code=501, detail="Live mode not implemented")


@app.post("/api/approve/{report_hash}")
def approve_report(report_hash: str, req: ApprovalRequest) -> dict[str, str]:
    """Execute G6 approval and record Operator control event."""
    try:
        event = create_g6_approval_event(
            target_id=report_hash,
            operator=req.operator,
            approval_signature=req.signature,
        )
        logger.info("G6 approval event created: %s", event)
        # In a real environment, we would persist this event to runs/_control/events/
        # and notify the state machine.
        return {"status": "success", "message": f"Report {report_hash} approved by {req.operator}."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/reject/{report_hash}")
def reject_report(report_hash: str, req: RejectionRequest) -> dict[str, str]:
    """Execute G6 rejection and record Operator control event."""
    try:
        event = create_g6_rejection_event(
            target_id=report_hash,
            operator=req.operator,
            reject_reason=req.reason,
        )
        logger.info("G6 rejection event created: %s", event)
        return {"status": "success", "message": f"Report {report_hash} rejected by {req.operator}."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
