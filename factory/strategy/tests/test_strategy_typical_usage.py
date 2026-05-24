from __future__ import annotations

import pytest

from factory.strategy.api import StrategyArchiveConfig
from factory.strategy.errors import SurpriseInvariantViolation


def test_strategy_typical_usage() -> None:
    config = StrategyArchiveConfig()

    assert config.reward_alpha + config.surprise_beta == pytest.approx(1.0)
    assert config.surprise_mode == "graded"

    with pytest.raises(SurpriseInvariantViolation):
        StrategyArchiveConfig(reward_alpha=0.8, surprise_beta=0.4)
