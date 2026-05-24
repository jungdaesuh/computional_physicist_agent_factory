"""Fidelity error taxonomy."""

from __future__ import annotations

from factory.artifacts import FactoryError


class FidelityError(FactoryError):
    """Base exception for the fidelity module."""


class LadderEmpty(FidelityError):
    """Raised when a scheduler is constructed or advanced without tiers."""


class TierOutOfOrder(FidelityError):
    """Raised when fidelity ladder state or results are inconsistent."""


class TierBudgetExhausted(FidelityError):
    """Raised when a tier cannot be reserved within the configured budget."""


class TierKillThresholdHit(FidelityError):
    """Raised by callers that choose exception-style kill-threshold handling."""


class SurrogatePredictionUnavailable(FidelityError):
    """Raised when a surrogate tier cannot produce a prediction."""


class AdapterRunFailed(FidelityError):
    """Raised when an adapter-backed tier fails at runtime."""


class MetricMissing(FidelityError):
    """Raised when a tier result lacks the experiment success metric."""


__all__ = [
    "AdapterRunFailed",
    "FidelityError",
    "LadderEmpty",
    "MetricMissing",
    "SurrogatePredictionUnavailable",
    "TierBudgetExhausted",
    "TierKillThresholdHit",
    "TierOutOfOrder",
]
