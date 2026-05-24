# api.py — Public interface of strategy
#
# This file defines the public-facing API for the strategy module.
# All functions/classes have docstrings and log their calls.

from __future__ import annotations

from factory.strategy.archive import StrategyArchive, StrategyArchiveConfig
from factory.strategy.distill import extract_behavior_descriptor
from factory.strategy.errors import (
    BehaviorDescriptorMissing,
    BucketCountsEmpty,
    DirichletDegenerateAlpha,
    GuideLLMRefusal,
    LineageSelectionEmpty,
    StrategyArchiveError,
    StrategyError,
    SurpriseInvariantViolation,
    UCTAllScoresZero,
)
from factory.strategy.offline import distill_offline_strategies

__all__ = [
    "StrategyArchive",
    "StrategyArchiveConfig",
    "extract_behavior_descriptor",
    "distill_offline_strategies",
    "StrategyError",
    "StrategyArchiveError",
    "SurpriseInvariantViolation",
    "DirichletDegenerateAlpha",
    "BucketCountsEmpty",
    "BehaviorDescriptorMissing",
    "GuideLLMRefusal",
    "UCTAllScoresZero",
    "LineageSelectionEmpty",
]
