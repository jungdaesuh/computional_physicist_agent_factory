# selection.py — Strategy Archive parent selection for parallel lineages
#
# This module implements the lineage selection algorithm for the Strategy Archive.
# It selects K parent strategy SHAs for parallel Best-First Tree Search (BFTS) branches.
#
# Detailed Use Cases and Workflow:
# 1. Loading candidates: The selection engine queries the strategies table in SQLite,
#    aggregating child counts from the edges table.
# 2. Score Normalization: Candidate reward, surprise, and feasibility distance EMAs
#    are min-max normalized. Cold-start values are used if metrics are missing.
# 3. UCT Scoring: Compiles the composite UCT score using:
#    - reward_alpha * reward_norm
#    - surprise_beta * surprise_norm
#    - feasibility_gamma * feasibility_pressure
#    - uct_exploration_constant * sqrt(log(total_visits) / (visits + 1))
# 4. Novelty Bonus: Calculates behavior-space novelty via average cosine distance to
#    the 4 nearest neighbors in the archive.
# 5. Child-Count Penalty: Prioritizes leaf nodes (nodes with fewer child edges) by scaling
#    the base score by 1 / (1 + child_count).
# 6. MAP-Elites Diversity: In Phase B, selects the best elite per populated cell key
#    before falling back to the wider archive, enforcing cell-based diversification.
# 7. Deterministic tie-breaking uses lexicographic SHA order for reproducibility.
# 8. Padding: Returns exactly K elements, using "novel:<index>" tokens to pad under-sized archives.

from __future__ import annotations

import json
import logging
import math
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from factory.artifacts import BehaviorDescriptor
from factory.strategy.errors import (
    BehaviorDescriptorMissing,
    LineageSelectionEmpty,
    UCTAllScoresZero,
)

if TYPE_CHECKING:
    from factory.strategy.archive import StrategyArchive

logger = logging.getLogger("factory.strategy.selection")

NOVEL_LINEAGE_TOKEN = "novel"


@dataclass(frozen=True)
class _StrategyCandidate:
    """Internal structure representing a strategy candidate loaded from the database."""

    sha: str
    reward_ema: float | None
    feasibility_distance_ema: float | None
    feasible_count: int
    surprise_ema: float | None
    visits: int
    children_count: int
    behavior_descriptor_json: str | None


def _normalize(
    value: float | None,
    lo: float | None,
    hi: float | None,
    *,
    cold_start: float,
) -> float:
    """Normalize value to [0, 1] using min-max bounds.

    Returns cold_start if value, lo, or hi is None, or if hi <= lo.
    """
    if value is None or lo is None or hi is None:
        return cold_start
    if hi <= lo:
        return cold_start
    return (value - lo) / (hi - lo)


def _load_descriptor(
    descriptor_json: str | None,
    *,
    candidate_sha: str,
    enforce: bool,
) -> BehaviorDescriptor | None:
    """Load a BehaviorDescriptor, optionally failing on missing or malformed data."""
    if descriptor_json is None:
        if enforce:
            raise BehaviorDescriptorMissing(
                f"Strategy {candidate_sha} is missing behavior_descriptor_json."
            )
        return None
    try:
        data = json.loads(descriptor_json)
    except json.JSONDecodeError as exc:
        if enforce:
            raise BehaviorDescriptorMissing(
                f"Strategy {candidate_sha} has malformed behavior_descriptor_json."
            ) from exc
        return None
    if not isinstance(data, dict):
        if enforce:
            raise BehaviorDescriptorMissing(
                f"Strategy {candidate_sha} behavior_descriptor_json must be an object."
            )
        return None
    try:
        return BehaviorDescriptor.model_validate(data)
    except ValidationError as exc:
        if enforce:
            raise BehaviorDescriptorMissing(
                f"Strategy {candidate_sha} has invalid behavior_descriptor_json."
            ) from exc
        return None


def _descriptor_vector(
    candidate: _StrategyCandidate,
    *,
    enforce: bool,
) -> tuple[float, ...] | None:
    """Extract the numeric behavior-space vector for novelty calculation."""
    desc = _load_descriptor(
        candidate.behavior_descriptor_json,
        candidate_sha=candidate.sha,
        enforce=enforce,
    )
    if desc is None:
        return None
    return desc.to_vector()


def _descriptor_cell(
    candidate: _StrategyCandidate,
    *,
    enforce: bool,
) -> tuple[str, ...] | None:
    """Extract the MAP-Elites cell key."""
    desc = _load_descriptor(
        candidate.behavior_descriptor_json,
        candidate_sha=candidate.sha,
        enforce=enforce,
    )
    if desc is None:
        return None
    return desc.to_cell_key()


def _cosine_distance(lhs: tuple[float, ...], rhs: tuple[float, ...]) -> float:
    """Compute the cosine distance between two numeric vectors, clamped to [0, 2]."""
    dot = sum(a * b for a, b in zip(lhs, rhs, strict=False))
    lhs_norm = math.sqrt(sum(a * a for a in lhs))
    rhs_norm = math.sqrt(sum(b * b for b in rhs))
    if lhs_norm == 0.0 or rhs_norm == 0.0:
        return 0.0
    val = dot / (lhs_norm * rhs_norm)
    val = max(-1.0, min(1.0, val))
    return 1.0 - val


def _novelty(
    vector: tuple[float, ...] | None,
    all_vectors: tuple[tuple[float, ...], ...],
) -> float:
    """Calculate the average cosine distance to the 4 nearest neighbors in behavior space."""
    if vector is None or len(all_vectors) <= 1:
        return 0.0
    distances = sorted(_cosine_distance(vector, other) for other in all_vectors if other != vector)
    if not distances:
        return 0.0
    nearest = distances[:4]
    return sum(nearest) / len(nearest)


def _elite_key(candidate: _StrategyCandidate) -> tuple[int, float, float, str]:
    """Compute the lexicographic sorting key for MAP-Elites cell elite comparison."""
    distance_score = (
        -candidate.feasibility_distance_ema
        if candidate.feasibility_distance_ema is not None
        else -math.inf
    )
    reward = candidate.reward_ema if candidate.reward_ema is not None else -math.inf
    return (candidate.feasible_count, distance_score, reward, candidate.sha)


def _cell_elites(
    candidates: list[_StrategyCandidate],
    cells_by_sha: dict[str, tuple[str, ...] | None],
) -> set[str]:
    """Identify the single best-evidence strategy candidate per populated MAP-Elites cell."""
    elites: dict[tuple[str, ...], _StrategyCandidate] = {}
    for candidate in candidates:
        cell = cells_by_sha[candidate.sha]
        if cell is None:
            continue
        current = elites.get(cell)
        if current is None or _elite_key(candidate) > _elite_key(current):
            elites[cell] = candidate
    return {candidate.sha for candidate in elites.values()}


def _load_candidates(
    conn: sqlite3.Connection,
    experiment_id: int,
) -> list[_StrategyCandidate]:
    """Load all candidates matching the experiment ID and count their child edges."""
    cursor = conn.cursor()
    rows = cursor.execute(
        """
        SELECT
          s.sha,
          s.reward_ema,
          s.feasibility_distance_ema,
          s.feasible_count,
          s.surprise_ema,
          s.visits,
          s.behavior_descriptor_json,
          COUNT(e.child_sha) AS children_count
        FROM strategies s
        LEFT JOIN strategy_edges e ON e.parent_sha = s.sha
        WHERE s.experiment_id = ?
        GROUP BY s.sha
        """,
        (experiment_id,),
    ).fetchall()

    candidates = []
    for row in rows:
        sha = str(row[0])
        reward_ema = None if row[1] is None else float(row[1])
        feasibility_distance_ema = None if row[2] is None else float(row[2])
        feasible_count = int(row[3])
        surprise_ema = None if row[4] is None else float(row[4])
        visits = int(row[5])
        behavior_descriptor_json = row[6]
        children_count = int(row[7])
        candidates.append(
            _StrategyCandidate(
                sha=sha,
                reward_ema=reward_ema,
                feasibility_distance_ema=feasibility_distance_ema,
                feasible_count=feasible_count,
                surprise_ema=surprise_ema,
                visits=visits,
                children_count=children_count,
                behavior_descriptor_json=behavior_descriptor_json,
            )
        )
    return candidates


def select_lineages(archive: StrategyArchive, k: int) -> list[str]:
    """Select parent strategy SHAs for parallel BFTS branches.

    Uses composite UCT scoring, novelty bonus, and MAP-Elites cell-first selection.

    Args:
        archive: The StrategyArchive stateful object.
        k: The number of parent strategy SHAs to return.

    Returns:
        A list of selected parent strategy SHAs.

    Raises:
        UCTAllScoresZero: If all candidate strategies score exactly 0.0.
        LineageSelectionEmpty: If the selection returns fewer than k elements.
    """
    logger.info("select_lineages(archive=%s, k=%d) entered", archive, k)
    candidates = _load_candidates(archive.conn, archive.experiment_id)
    if not candidates:
        res = [f"{NOVEL_LINEAGE_TOKEN}:{idx}" for idx in range(k)]
        logger.info("No candidates found, returned novel tokens: %s", res)
        return res

    rewards = [c.reward_ema for c in candidates if c.reward_ema is not None]
    distances = [
        c.feasibility_distance_ema for c in candidates if c.feasibility_distance_ema is not None
    ]
    surprises = [c.surprise_ema for c in candidates if c.surprise_ema is not None]

    reward_lo = min(rewards) if rewards else None
    reward_hi = max(rewards) if rewards else None
    distance_lo = min(distances) if distances else None
    distance_hi = max(distances) if distances else None
    surprise_lo = min(surprises) if surprises else None
    surprise_hi = max(surprises) if surprises else None

    total_visits = max(sum(c.visits for c in candidates), 1)
    max_feasible_count = max((c.feasible_count for c in candidates), default=0)

    enforce_descriptors = archive.config.enforce_behavior_descriptors
    vectors_by_sha = {
        candidate.sha: _descriptor_vector(candidate, enforce=enforce_descriptors)
        for candidate in candidates
    }
    cells_by_sha = {
        candidate.sha: _descriptor_cell(candidate, enforce=enforce_descriptors)
        for candidate in candidates
    }
    all_vectors = tuple(v for v in vectors_by_sha.values() if v is not None)

    base_scores: dict[str, float] = {}
    for candidate in candidates:
        reward_norm = _normalize(
            candidate.reward_ema,
            reward_lo,
            reward_hi,
            cold_start=0.5,
        )
        surprise_norm = _normalize(
            candidate.surprise_ema,
            surprise_lo,
            surprise_hi,
            cold_start=0.0,
        )
        if max_feasible_count > 0:
            feasibility_pressure = candidate.feasible_count / max_feasible_count
        else:
            distance_norm = _normalize(
                candidate.feasibility_distance_ema,
                distance_lo,
                distance_hi,
                cold_start=1.0,
            )
            feasibility_pressure = 1.0 - distance_norm

        exploration = archive.config.uct_exploration_constant * math.sqrt(
            math.log(float(total_visits)) / (candidate.visits + 1)
        )

        uct_score = (
            archive.config.reward_alpha * reward_norm
            + archive.config.surprise_beta * surprise_norm
            + archive.config.feasibility_gamma * feasibility_pressure
            + exploration
        )

        novelty_bonus = archive.config.behavior_novelty_weight * _novelty(
            vectors_by_sha[candidate.sha],
            all_vectors,
        )

        child_penalty = 1.0 / (1.0 + candidate.children_count)
        base_scores[candidate.sha] = (uct_score + novelty_bonus) * child_penalty

    if base_scores and all(
        math.isclose(score, 0.0, abs_tol=1e-9) for score in base_scores.values()
    ):
        raise UCTAllScoresZero("Every candidate scored exactly 0.0 on the UCT composite.")

    remaining = {candidate.sha for candidate in candidates}
    selected: list[str] = []
    selected_vectors: list[tuple[float, ...]] = []
    elite_shas = _cell_elites(candidates, cells_by_sha)

    while remaining and len(selected) < k:
        eligible = remaining & elite_shas
        if not eligible:
            eligible = remaining

        scored: list[tuple[float, str]] = []
        for sha in eligible:
            selected_bonus = 0.0
            vector = vectors_by_sha[sha]
            if vector is not None and selected_vectors:
                selected_bonus = archive.config.behavior_novelty_weight * (
                    sum(_cosine_distance(vector, chosen) for chosen in selected_vectors)
                    / len(selected_vectors)
                )
            map_elites_bonus = archive.config.map_elites_cell_bonus if sha in elite_shas else 0.0
            score = base_scores[sha] + selected_bonus + map_elites_bonus
            scored.append((score, sha))

        # Tie-break by SHA (lexicographic) for determinism.
        _score, chosen_sha = min(scored, key=lambda item: (-item[0], item[1]))
        selected.append(chosen_sha)
        remaining.remove(chosen_sha)

        chosen_cell = cells_by_sha[chosen_sha]
        if chosen_cell is not None:
            elite_shas = {sha for sha in elite_shas if cells_by_sha[sha] != chosen_cell}

        chosen_vector = vectors_by_sha[chosen_sha]
        if chosen_vector is not None:
            selected_vectors.append(chosen_vector)

    while len(selected) < k:
        selected.append(f"{NOVEL_LINEAGE_TOKEN}:{len(selected)}")

    if len(selected) < k:
        raise LineageSelectionEmpty(f"padding loop failed to fill k={k}")

    logger.info("select_lineages(k=%d) selected: %s", k, selected)
    return selected
