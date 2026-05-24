# errors.py — Exception Hierarchy for Strategy Module
#
# This module defines all custom exceptions thrown by the strategy module,
# ensuring a clear taxonomy. All exceptions inherit from the base FactoryError.

from __future__ import annotations

import logging

from factory.artifacts.api import FactoryError

logger = logging.getLogger("factory.strategy.errors")


class StrategyError(FactoryError):
    """Base exception for the strategy module."""

    pass


class StrategyArchiveError(StrategyError):
    """Base exception for Strategy Archive errors."""

    pass


class SurpriseInvariantViolation(StrategyArchiveError):
    """Raised when the reward and surprise weights do not sum to 1.0."""

    pass


class DirichletDegenerateAlpha(StrategyArchiveError):
    """Raised when a Dirichlet/Beta KL calculation receives non-positive parameters."""

    pass


class BucketCountsEmpty(StrategyArchiveError):
    """Raised when GuideLLM yields zero valid responses pre- or post-evidence."""

    pass


class BehaviorDescriptorMissing(StrategyArchiveError):
    """Raised when lineage selection is invoked with no behavior descriptors in candidates."""

    pass


class GuideLLMRefusal(StrategyArchiveError):
    """Raised when GuideLLM refuses or gets safety-filtered twice on a prompt."""

    pass


class UCTAllScoresZero(StrategyArchiveError):
    """Raised when all candidates score exactly 0.0 on the UCT composite."""

    pass


class LineageSelectionEmpty(StrategyArchiveError):
    """Raised when select_lineages returns fewer than k lineages (tripwire for padding bug)."""

    pass
