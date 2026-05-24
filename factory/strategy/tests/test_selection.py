# test_selection.py — Unit tests for Strategy Archive selection logic
#
# This file tests UCT composite scoring, novelty bonus, child penalties,
# MAP-Elites cell diversity, and exception conditions in select_lineages.

import sqlite3
from collections.abc import Generator

import pytest

from factory.artifacts import BehaviorDescriptor
from factory.strategy.archive import StrategyArchive, StrategyArchiveConfig
from factory.strategy.errors import (
    BehaviorDescriptorMissing,
    SurpriseInvariantViolation,
    UCTAllScoresZero,
)
from factory.strategy.selection import select_lineages


@pytest.fixture
def db_conn() -> Generator[sqlite3.Connection, None, None]:
    """Provide a clean, initialized in-memory SQLite database connection."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            constellaration_sha TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS strategies (
            sha TEXT PRIMARY KEY,
            experiment_id INTEGER,
            reward_ema REAL,
            feasibility_distance_ema REAL,
            feasible_count INTEGER,
            surprise_ema REAL,
            visits INTEGER,
            behavior_descriptor_json TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_edges (
            parent_sha TEXT,
            child_sha TEXT
        )
        """
    )
    conn.commit()
    yield conn
    conn.close()


def test_config_invariants() -> None:
    """Verify that StrategyArchiveConfig validates invariants on construction."""
    # Valid config
    config = StrategyArchiveConfig(reward_alpha=0.7, surprise_beta=0.3)
    assert config.reward_alpha + config.surprise_beta == 1.0

    # Invalid convex combination
    with pytest.raises(SurpriseInvariantViolation):
        StrategyArchiveConfig(reward_alpha=0.8, surprise_beta=0.3)

    # Invalid ranges
    with pytest.raises(SurpriseInvariantViolation):
        StrategyArchiveConfig(reward_alpha=1.5, surprise_beta=-0.5)

    with pytest.raises(SurpriseInvariantViolation):
        StrategyArchiveConfig(surprise_n_samples=0)

    with pytest.raises(SurpriseInvariantViolation):
        StrategyArchiveConfig(ema_alpha=1.2)


def test_empty_archive(db_conn: sqlite3.Connection) -> None:
    """Verify that an empty archive returns novel padding tokens."""
    config = StrategyArchiveConfig(reward_alpha=0.5, surprise_beta=0.5)
    archive = StrategyArchive(
        config=config,
        conn=db_conn,
        guide_llm=None,
        experiment_id=1,
        problem_id="test-prob",
    )

    selected = select_lineages(archive, k=3)
    assert selected == ["novel:0", "novel:1", "novel:2"]


def test_uct_scoring_and_selection(db_conn: sqlite3.Connection) -> None:
    """Test standard UCT lineage selection under normal operations."""
    cursor = db_conn.cursor()
    # Insert experiment
    cursor.execute("INSERT INTO experiments (id, constellaration_sha) VALUES (1, 'const-1')")
    # Insert two strategies
    # Strategy A: high reward, low visits
    cursor.execute(
        """
        INSERT INTO strategies (
            sha, experiment_id, reward_ema, feasibility_distance_ema,
            feasible_count, surprise_ema, visits, behavior_descriptor_json
        )
        VALUES ('shaA', 1, 0.9, 0.1, 5, 0.2, 2, ?)
        """,
        (BehaviorDescriptor(vector=(1.0, 0.0), cell_id="cell-1").model_dump_json(),),
    )
    # Strategy B: low reward, high visits
    cursor.execute(
        """
        INSERT INTO strategies (
            sha, experiment_id, reward_ema, feasibility_distance_ema,
            feasible_count, surprise_ema, visits, behavior_descriptor_json
        )
        VALUES ('shaB', 1, 0.1, 0.9, 1, 0.8, 10, ?)
        """,
        (BehaviorDescriptor(vector=(0.0, 1.0), cell_id="cell-2").model_dump_json(),),
    )
    db_conn.commit()

    config = StrategyArchiveConfig(
        reward_alpha=0.8,
        surprise_beta=0.2,
        feasibility_gamma=0.5,
        uct_exploration_constant=1.0,
    )
    archive = StrategyArchive(
        config=config,
        conn=db_conn,
        guide_llm=None,
        experiment_id=1,
        problem_id="test-prob",
    )

    selected = select_lineages(archive, k=1)
    # Strategy A has higher reward, feasibility pressure, and exploration score.
    assert selected == ["shaA"]


def test_uct_all_scores_zero(db_conn: sqlite3.Connection) -> None:
    """Verify that UCTAllScoresZero is raised if all candidate scores are zero."""
    cursor = db_conn.cursor()
    cursor.execute("INSERT INTO experiments (id, constellaration_sha) VALUES (1, 'const-1')")
    # Insert a corrupt or specifically zero-scored candidate with 0 reward, 0 visits etc.
    # Visits and total_visits are zero, so all configured score terms can be zero.
    cursor.execute(
        """
        INSERT INTO strategies (
            sha, experiment_id, reward_ema, feasibility_distance_ema,
            feasible_count, surprise_ema, visits, behavior_descriptor_json
        )
        VALUES ('shaZero', 1, 0.0, 0.0, 0, 0.0, 0, NULL)
        """
    )
    db_conn.commit()

    config = StrategyArchiveConfig(
        reward_alpha=0.0,
        surprise_beta=1.0,
        feasibility_gamma=0.0,
        uct_exploration_constant=0.0,
        behavior_novelty_weight=0.0,
        enforce_behavior_descriptors=False,
    )
    archive = StrategyArchive(
        config=config,
        conn=db_conn,
        guide_llm=None,
        experiment_id=1,
        problem_id="test-prob",
    )

    with pytest.raises(UCTAllScoresZero):
        select_lineages(archive, k=1)


def test_map_elites_cell_diversity(db_conn: sqlite3.Connection) -> None:
    """Verify that selection prioritizes candidates in unique cells first."""
    cursor = db_conn.cursor()
    cursor.execute("INSERT INTO experiments (id, constellaration_sha) VALUES (1, 'const-1')")

    # Insert 3 strategies. A and B are in the same cell 'cell-1'. C is in 'cell-2'.
    # A has slightly higher reward than B.
    # C has lower reward but is in a unique cell.
    cursor.execute(
        """
        INSERT INTO strategies (
            sha, experiment_id, reward_ema, feasibility_distance_ema,
            feasible_count, surprise_ema, visits, behavior_descriptor_json
        )
        VALUES ('shaA', 1, 0.8, 0.2, 2, 0.1, 1, ?)
        """,
        (BehaviorDescriptor(vector=(1.0, 0.0), cell_id="cell-1").model_dump_json(),),
    )
    cursor.execute(
        """
        INSERT INTO strategies (
            sha, experiment_id, reward_ema, feasibility_distance_ema,
            feasible_count, surprise_ema, visits, behavior_descriptor_json
        )
        VALUES ('shaB', 1, 0.7, 0.2, 2, 0.1, 1, ?)
        """,
        (BehaviorDescriptor(vector=(1.0, 0.05), cell_id="cell-1").model_dump_json(),),
    )
    cursor.execute(
        """
        INSERT INTO strategies (
            sha, experiment_id, reward_ema, feasibility_distance_ema,
            feasible_count, surprise_ema, visits, behavior_descriptor_json
        )
        VALUES ('shaC', 1, 0.4, 0.2, 2, 0.1, 1, ?)
        """,
        (BehaviorDescriptor(vector=(0.0, 1.0), cell_id="cell-2").model_dump_json(),),
    )
    db_conn.commit()

    config = StrategyArchiveConfig(
        reward_alpha=1.0,
        surprise_beta=0.0,
        feasibility_gamma=0.0,
        uct_exploration_constant=0.0,
        behavior_novelty_weight=0.0,
        map_elites_cell_bonus=10.0,  # huge bonus for unique cell elites
    )
    archive = StrategyArchive(
        config=config,
        conn=db_conn,
        guide_llm=None,
        experiment_id=1,
        problem_id="test-prob",
    )

    # When k=2, select elites from separate cells before another same-cell candidate.
    selected = select_lineages(archive, k=2)
    assert "shaA" in selected
    assert "shaC" in selected
    assert "shaB" not in selected


def test_deterministic_tie_breaking(db_conn: sqlite3.Connection) -> None:
    """Verify that ties in score are broken lexicographically by SHA."""
    cursor = db_conn.cursor()
    cursor.execute("INSERT INTO experiments (id, constellaration_sha) VALUES (1, 'const-1')")

    # Insert 3 identical candidates but with different SHAs
    for sha in ["shaC", "shaA", "shaB"]:
        cursor.execute(
            """
            INSERT INTO strategies (
            sha, experiment_id, reward_ema, feasibility_distance_ema,
            feasible_count, surprise_ema, visits, behavior_descriptor_json
        )
            VALUES (?, 1, 0.5, 0.5, 1, 0.5, 1, NULL)
            """,
            (sha,),
        )
    db_conn.commit()

    config = StrategyArchiveConfig(
        reward_alpha=0.5,
        surprise_beta=0.5,
        feasibility_gamma=0.0,
        uct_exploration_constant=0.0,
        enforce_behavior_descriptors=False,
    )
    archive = StrategyArchive(
        config=config,
        conn=db_conn,
        guide_llm=None,
        experiment_id=1,
        problem_id="test-prob",
    )

    selected = select_lineages(archive, k=3)
    # Under identical score, tie-break chooses lexicographically ascending SHAs.
    assert selected == ["shaA", "shaB", "shaC"]


def test_descriptor_enforcement_raises_for_descriptorless_candidate(
    db_conn: sqlite3.Connection,
) -> None:
    """Descriptor enforcement rejects non-empty archives with missing descriptors."""
    cursor = db_conn.cursor()
    cursor.execute("INSERT INTO experiments (id, constellaration_sha) VALUES (1, 'const-1')")
    cursor.execute(
        """
        INSERT INTO strategies (
            sha, experiment_id, reward_ema, feasibility_distance_ema,
            feasible_count, surprise_ema, visits, behavior_descriptor_json
        )
        VALUES ('shaA', 1, 0.5, 0.5, 1, 0.5, 1, NULL)
        """
    )
    db_conn.commit()

    archive = StrategyArchive(
        config=StrategyArchiveConfig(
            reward_alpha=0.5,
            surprise_beta=0.5,
            enforce_behavior_descriptors=True,
        ),
        conn=db_conn,
        guide_llm=None,
        experiment_id=1,
        problem_id="test-prob",
    )

    with pytest.raises(BehaviorDescriptorMissing, match="shaA"):
        select_lineages(archive, k=1)


def test_set_and_get_behavior_descriptor(db_conn: sqlite3.Connection) -> None:
    """Verify set_behavior_descriptor and get_occupied_cells works."""
    cursor = db_conn.cursor()
    cursor.execute("INSERT INTO experiments (id, constellaration_sha) VALUES (1, 'const-1')")
    cursor.execute(
        """
        INSERT INTO strategies (
            sha, experiment_id, reward_ema, feasibility_distance_ema,
            feasible_count, surprise_ema, visits, behavior_descriptor_json
        )
        VALUES ('shaA', 1, 0.5, 0.5, 1, 0.5, 1, NULL)
        """
    )
    db_conn.commit()

    config = StrategyArchiveConfig(reward_alpha=0.5, surprise_beta=0.5)
    archive = StrategyArchive(
        config=config,
        conn=db_conn,
        guide_llm=None,
        experiment_id=1,
        problem_id="test-prob",
    )

    # Initial state: empty occupied cells
    assert archive.get_occupied_cells() == set()

    # Set behavior descriptor
    bd = BehaviorDescriptor(vector=(0.5, -0.5), cell_id="cell-A")
    archive.set_behavior_descriptor("shaA", bd)

    # Verify set and get
    assert archive.get_occupied_cells() == {"cell-A"}
