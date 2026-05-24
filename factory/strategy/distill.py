# distill.py — Behavior Descriptor Feature Extractor for Strategy Archive
#
# This file implements the extraction of behavioral coordinates and MAP-Elites
# cell identifiers from strategy candidate specifications (summary_md/metadata).
#
# Use cases:
# 1. Parsing a stellarator strategy's keywords to construct a behavior vector.
# 2. Projecting high-dimensional strategy attributes onto a discrete grid key (MAP-Elites).
#
# Constraints:
# - No dynamic imports.
# - Strict type annotations.
# - Functional programming patterns (pure transformations).

from __future__ import annotations

import logging
import re
from typing import Final

from factory.artifacts.strategies import BehaviorDescriptor

logger = logging.getLogger("factory.strategy.distill")

# Dimension vectors representing different strategic directions
KEYWORDS_RESOLUTION: Final[list[str]] = ["grid", "resolution", "mesh", "nodes", "radial"]
KEYWORDS_PHYSICS: Final[list[str]] = [
    "mhd",
    "stability",
    "quasisymmetry",
    "qs",
    "aspect",
    "curvature",
]
KEYWORDS_SOLVER: Final[list[str]] = ["adam", "gd", "newton", "lbfgs", "gradient", "step"]


def extract_behavior_descriptor(summary_md: str) -> BehaviorDescriptor:
    """Extract a behavior descriptor vector and cell ID from strategy text.

    Args:
        summary_md: The markdown summary of the stellarator strategy.

    Returns:
        A BehaviorDescriptor containing a 3D coordinate vector and a cell key.
    """
    logger.info("extract_behavior_descriptor(summary_md_len=%d)", len(summary_md))
    text_lower = summary_md.lower()

    # Calculate frequencies of keyword groups to define coordinate values
    def score_group(keywords: list[str]) -> float:
        score = 0.0
        for kw in keywords:
            # Find all occurrences of keyword
            matches = len(re.findall(r"\b" + re.escape(kw) + r"\b", text_lower))
            score += matches * 0.25
        # Clamp to [0.0, 1.0]
        return min(score, 1.0)

    res_score = score_group(KEYWORDS_RESOLUTION)
    phys_score = score_group(KEYWORDS_PHYSICS)
    solv_score = score_group(KEYWORDS_SOLVER)

    vector = (res_score, phys_score, solv_score)

    # Discretize coordinates to determine the cell grid partition
    # Grids: 0 (Low < 0.33), 1 (Mid 0.33-0.66), 2 (High > 0.66)
    def discretize(val: float) -> str:
        if val < 0.33:
            return "L"
        elif val < 0.66:
            return "M"
        return "H"

    cell_key = f"cell_{discretize(res_score)}_{discretize(phys_score)}_{discretize(solv_score)}"
    descriptor = BehaviorDescriptor(vector=vector, cell_id=cell_key)
    logger.info("extract_behavior_descriptor created descriptor: %s", descriptor)
    return descriptor
