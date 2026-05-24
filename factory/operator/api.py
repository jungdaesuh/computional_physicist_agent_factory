"""Public implementation contract for the operator module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from factory.module_contracts import ModuleContract
from factory.operator.errors import (
    AmbiguousHypothesisId,
    ApprovalDenied,
    CycleNotFound,
    FactoryNotRunning,
    NonLoopbackBindRejected,
    OperatorError,
    TelemetryUnavailable,
)

from factory.operator.secrets import KeyringBackend, ResolvedSecret, SecretRef, SecretResolver

MODULE_CONTRACT = ModuleContract(
    module_name="operator",
    spec_id="015",
    responsibility=(
        "Expose operator control events for pause, resume, approval, rejection, and halt."
    ),
    required_inputs=("FactoryControlCommand",),
    produced_outputs=("FactoryControlEvent",),
)


def describe_contract() -> ModuleContract:
    """Return the stable public contract for this module."""
    return MODULE_CONTRACT


@dataclass(frozen=True, slots=True)
class G6DecisionEvent:
    """Operator G6 decision event with explicit approval or rejection evidence."""

    event_type: Literal["g6_approve", "g6_reject"]
    target_id: str
    operator: str
    invoked_at: datetime
    approval_signature: str | None
    reject_reason: str | None


def create_g6_approval_event(
    *,
    target_id: str,
    operator: str,
    approval_signature: str,
    invoked_at: datetime | None = None,
) -> G6DecisionEvent:
    """Create an explicit G6 approval event; signatures are mandatory."""
    if approval_signature.strip() == "":
        raise OperatorError("G6 approval requires an explicit approval signature.")
    return G6DecisionEvent(
        event_type="g6_approve",
        target_id=target_id,
        operator=operator,
        invoked_at=invoked_at or datetime.now(),
        approval_signature=approval_signature,
        reject_reason=None,
    )


def create_g6_rejection_event(
    *,
    target_id: str,
    operator: str,
    reject_reason: str,
    invoked_at: datetime | None = None,
) -> G6DecisionEvent:
    """Create a G6 rejection event; a rejection reason is mandatory."""
    if reject_reason.strip() == "":
        raise OperatorError("G6 rejection requires a reason.")
    return G6DecisionEvent(
        event_type="g6_reject",
        target_id=target_id,
        operator=operator,
        invoked_at=invoked_at or datetime.now(),
        approval_signature=None,
        reject_reason=reject_reason,
    )


__all__ = [
    "AmbiguousHypothesisId",
    "ApprovalDenied",
    "CycleNotFound",
    "FactoryNotRunning",
    "G6DecisionEvent",
    "KeyringBackend",
    "MODULE_CONTRACT",
    "NonLoopbackBindRejected",
    "OperatorError",
    "ResolvedSecret",
    "SecretRef",
    "SecretResolver",
    "TelemetryUnavailable",
    "create_g6_approval_event",
    "create_g6_rejection_event",
    "describe_contract",
]

