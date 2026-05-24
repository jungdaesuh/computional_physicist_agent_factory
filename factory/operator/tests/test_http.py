"""Unit and integration tests for the operator HTTP server."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from factory.operator.api import NonLoopbackBindRejected
from factory.operator.cli import main
from factory.operator.http import app


def test_fastapi_endpoints() -> None:
    """Verify that all read endpoints return 200 with required staleness tags."""
    # Force mock mode for HTTP endpoints via env var
    with patch.dict(os.environ, {"FACTORY_MOCK": "1"}):
        client = TestClient(app)

        endpoints = [
            "/api/mission_control",
            "/api/cycles/mock-cycle-1",
            "/api/cycles/mock-cycle-1/gates",
            "/api/verdicts/C1",
            "/api/catalog",
            "/api/catalog/sim_a",
            "/api/ledger/search",
            "/api/ledger/H-STELLA-001",
            "/api/reports/0000000000000000000000000000000000000000000000000000000000000000",
            "/api/approval_queue",
            "/api/settings",
        ]

        for path in endpoints:
            response = client.get(path)
            assert response.status_code == 200, f"Failed at {path}: {response.text}"
            data = response.json()
            assert "stale" in data
            assert "served_at" in data


def test_g6_approvals() -> None:
    """Verify post routes for human G6 approval/rejection gates."""
    with patch.dict(os.environ, {"FACTORY_MOCK": "1"}):
        client = TestClient(app)

        report_hash = "0000000000000000000000000000000000000000000000000000000000000000"

        # Approve
        resp = client.post(
            f"/api/approve/{report_hash}",
            json={"operator": "ada", "signature": "ada@example.com sha256:abc"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

        # Approve - empty signature validation
        resp_empty = client.post(
            f"/api/approve/{report_hash}",
            json={"operator": "ada", "signature": " "},
        )
        assert resp_empty.status_code == 400

        # Reject
        resp_reject = client.post(
            f"/api/reject/{report_hash}",
            json={"operator": "ada", "reason": "poor accuracy"},
        )
        assert resp_reject.status_code == 200
        assert resp_reject.json()["status"] == "success"

        # Reject - empty reason validation
        resp_reject_empty = client.post(
            f"/api/reject/{report_hash}",
            json={"operator": "ada", "reason": ""},
        )
        assert resp_reject_empty.status_code == 400


def test_non_loopback_bind_is_rejected() -> None:
    """Verify that binding to non-loopback host raises NonLoopbackBindRejected."""
    with pytest.raises(NonLoopbackBindRejected):
        main(("serve", "--host", "0.0.0.0", "--port", "8765"))
