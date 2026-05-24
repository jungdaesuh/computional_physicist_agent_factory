# types.py — Local types for the Budget Tracker module
#
# This file defines the dataclasses used to track budget envelopes,
# remaining headroom, cost breakdowns, and active reservations.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from factory.artifacts import HypothesisId

if TYPE_CHECKING:
    from factory.budget.api import BudgetTracker


@dataclass(frozen=True)
class HypothesisCaps:
    """Per-hypothesis budget caps. Iterations count is only valid here."""

    dollars: float
    tokens: int
    wall_clock_seconds: float
    iterations: int


@dataclass(frozen=True)
class TimeWindowCaps:
    """Per-day or program-aggregate budget caps."""

    dollars: float
    tokens: int
    wall_clock_seconds: float


@dataclass(frozen=True)
class RemainingBudget:
    """Headroom snapshot across all three tiers."""

    hypothesis: HypothesisCaps
    day: TimeWindowCaps
    aggregate: TimeWindowCaps


@dataclass(frozen=True)
class CostBreakdown:
    """Attribution of monetary cost across different modules."""

    window: tuple[datetime, datetime]
    by_module: dict[str, float]
    total_usd: float


@dataclass(frozen=True)
class Reservation:
    """Represents a budget reservation during an operation."""

    reservation_id: str
    hypothesis_id: HypothesisId
    module: str
    estimated_cost_usd: float
    estimated_tokens: int
    estimated_wall_clock_seconds: float
    estimated_iterations: int
    expires_at: datetime
    tracker: BudgetTracker = field(compare=False, hash=False, repr=False)

    def commit(
        self, *, actual_cost_usd: float, actual_tokens: int, wall_clock_seconds: float
    ) -> None:
        """Commits the actual cost, releasing the reservation."""
        self.tracker.record(
            hypothesis_id=self.hypothesis_id,
            module=self.module,
            cost_usd=actual_cost_usd,
            tokens=actual_tokens,
            wall_clock_seconds=wall_clock_seconds,
            description=f"Commit reservation {self.reservation_id}",
            reservation=self,
        )

    def cancel(self) -> None:
        """Cancels the reservation, releasing the estimated cost."""
        self.tracker._release_reservation(self.reservation_id)
