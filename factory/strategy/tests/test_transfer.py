# test_transfer.py — Unit tests for priors transfer logic
#
# Verifies copying top-K strategies by problem ID across experiments.

from __future__ import annotations

import sqlite3
from collections.abc import Generator

import pytest

from factory.strategy.transfer import transfer_priors_from


@pytest.fixture
def db_conn() -> Generator[sqlite3.Connection, None, None]:
    """Provide a clean in-memory SQLite database connection with experiments schema."""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS experiments (id INTEGER PRIMARY KEY, problem_id TEXT)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS strategies (
            sha TEXT NOT NULL,
            experiment_id INTEGER NOT NULL,
            summary TEXT,
            summary_md TEXT,
            kind TEXT,
            provenance TEXT,
            reward_ema REAL,
            surprise_ema REAL,
            feasibility_distance_ema REAL,
            feasible_count INTEGER,
            visits INTEGER,
            behavior_descriptor_json TEXT,
            constraint_overshoot_json TEXT,
            PRIMARY KEY (sha, experiment_id)
        )
        """
    )
    conn.commit()
    yield conn
    conn.close()


def test_transfer_priors_from_success(db_conn: sqlite3.Connection) -> None:
    """Verify that strategies are copied correctly and metrics are zeroed/NULL."""
    cursor = db_conn.cursor()

    # Create source experiment and target experiment
    cursor.execute("INSERT INTO experiments (id, problem_id) VALUES (1, 'stellarator-mhd')")
    cursor.execute("INSERT INTO experiments (id, problem_id) VALUES (2, 'stellarator-quasi')")

    # Insert strategy into source experiment
    cursor.execute(
        """
        INSERT INTO strategies (
            sha, experiment_id, summary, summary_md, kind, provenance,
            reward_ema, feasible_count, visits
        )
        VALUES ('shaA', 1, 'Summary A', 'Summary MD A', 'novel', 'agent_authored', 0.9, 5, 2)
        """
    )
    db_conn.commit()

    # Transfer from problem 'stellarator-mhd' (experiment 1) to experiment 2
    transfer_priors_from(db_conn, dest_experiment_id=2, source_problem_id="stellarator-mhd", k=5)

    # Check that strategy was copied to experiment 2
    row = cursor.execute(
        "SELECT sha, experiment_id, provenance, reward_ema FROM strategies WHERE experiment_id = 2"
    ).fetchone()
    assert row is not None
    assert row[0] == "shaA"
    assert row[1] == 2
    assert row[2] == "transferred_from_exp_1"
    assert row[3] is None  # Reward EMA is zeroed/NULL
