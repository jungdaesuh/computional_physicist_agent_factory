# strategy_config.py — Strategy Archive Configuration
#
# This file defines the StrategyArchiveConfig class, which manages all hyperparameters
# for selection scoring, exploration weighting, EMA smoothing, and surprise elicitation.
#
# It validates invariants at construction, including reward_alpha + surprise_beta == 1.0.

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Literal

from factory.strategy.errors import SurpriseInvariantViolation

logger = logging.getLogger("factory.strategy.strategy_config")


@dataclass(frozen=True)
class StrategyArchiveConfig:
    """Configuration parameter set for StrategyArchive.

    Enforces the convex combination invariant: reward_alpha + surprise_beta == 1.0.
    """

    reward_alpha: float = 0.6
    surprise_beta: float = 0.4
    feasibility_gamma: float = 0.2
    uct_exploration_constant: float = 1.414
    behavior_novelty_weight: float = 0.1
    map_elites_cell_bonus: float = 0.5
    ema_alpha: float = 0.3
    surprise_mode: Literal["binary", "graded"] = "graded"
    surprise_n_samples: int = 5
    enforce_behavior_descriptors: bool = True

    def __post_init__(self) -> None:
        """Validate configuration invariants."""
        # Check reward_alpha + surprise_beta == 1.0 convex combination
        total = self.reward_alpha + self.surprise_beta
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            raise SurpriseInvariantViolation(
                f"Surprise invariant violated: reward_alpha ({self.reward_alpha}) + "
                f"surprise_beta ({self.surprise_beta}) = {total} (must sum to 1.0)"
            )

        # Non-negative weights checks
        if self.reward_alpha < 0.0 or self.surprise_beta < 0.0:
            raise SurpriseInvariantViolation(
                "Weights reward_alpha and surprise_beta must be non-negative."
            )

        if self.feasibility_gamma < 0.0:
            raise SurpriseInvariantViolation("feasibility_gamma must be non-negative.")

        if self.uct_exploration_constant < 0.0:
            raise SurpriseInvariantViolation("uct_exploration_constant must be non-negative.")

        if self.behavior_novelty_weight < 0.0:
            raise SurpriseInvariantViolation("behavior_novelty_weight must be non-negative.")

        if self.map_elites_cell_bonus < 0.0:
            raise SurpriseInvariantViolation("map_elites_cell_bonus must be non-negative.")

        if not (0.0 < self.ema_alpha <= 1.0):
            raise SurpriseInvariantViolation("ema_alpha must be in the range (0.0, 1.0].")

        if self.surprise_n_samples <= 0:
            raise SurpriseInvariantViolation("surprise_n_samples must be strictly positive.")
