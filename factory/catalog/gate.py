"""Human approval gate records for catalog onboarding."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Literal

GateDecision = Literal["approve", "reject"]


@dataclass(frozen=True)
class HumanGateRecord:
    """Immutable approval or rejection record for one onboarding proposal."""

    proposal_hash: str
    simulator_id: str
    reviewer_id: str
    decision: GateDecision
    reason: str
    decided_at: datetime.datetime


def approve_onboarding(
    proposal_hash: str,
    simulator_id: str,
    reviewer_id: str,
    reason: str = "approved",
    decided_at: datetime.datetime | None = None,
) -> HumanGateRecord:
    """Create a human approval record for a manifest proposal."""

    return _gate_record(
        proposal_hash=proposal_hash,
        simulator_id=simulator_id,
        reviewer_id=reviewer_id,
        decision="approve",
        reason=reason,
        decided_at=decided_at,
    )


def reject_onboarding(
    proposal_hash: str,
    simulator_id: str,
    reviewer_id: str,
    reason: str,
    decided_at: datetime.datetime | None = None,
) -> HumanGateRecord:
    """Create a human rejection record for a manifest proposal."""

    return _gate_record(
        proposal_hash=proposal_hash,
        simulator_id=simulator_id,
        reviewer_id=reviewer_id,
        decision="reject",
        reason=reason,
        decided_at=decided_at,
    )


def _gate_record(
    proposal_hash: str,
    simulator_id: str,
    reviewer_id: str,
    decision: GateDecision,
    reason: str,
    decided_at: datetime.datetime | None,
) -> HumanGateRecord:
    if not proposal_hash:
        raise ValueError("proposal_hash is required")
    if not simulator_id:
        raise ValueError("simulator_id is required")
    if not reviewer_id:
        raise ValueError("reviewer_id is required")
    if not reason:
        raise ValueError("reason is required")
    return HumanGateRecord(
        proposal_hash=proposal_hash,
        simulator_id=simulator_id,
        reviewer_id=reviewer_id,
        decision=decision,
        reason=reason,
        decided_at=decided_at or datetime.datetime.now(datetime.UTC),
    )
