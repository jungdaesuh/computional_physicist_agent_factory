# test_offline.py — Unit tests for offline strategy distillation
#
# Verifies periodic database distillation into static JSON files.

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from factory.strategy.offline import distill_offline_strategies


def test_distill_offline_strategies(tmp_path: Path) -> None:
    """Verify that strategies are queried and written to library JSON."""
    db_file = tmp_path / "strategies.db"
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE strategies (
            sha TEXT PRIMARY KEY,
            experiment_id INTEGER,
            summary TEXT,
            summary_md TEXT,
            kind TEXT,
            provenance TEXT,
            reward_ema REAL,
            feasible_count INTEGER,
            visits INTEGER
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO strategies (
            sha, experiment_id, summary, summary_md, kind, provenance,
            reward_ema, feasible_count, visits
        )
        VALUES ('shaX', 1, 'Summary X', 'Summary MD X', 'novel', 'agent_authored', 0.95, 10, 3)
        """
    )
    conn.commit()
    conn.close()

    lib_file = tmp_path / "library.json"
    count = distill_offline_strategies(db_file, lib_file, k=5)
    assert count == 1
    assert lib_file.exists()

    with open(lib_file) as f:
        data = json.load(f)

    assert "distilled_strategies" in data
    assert len(data["distilled_strategies"]) == 1
    item = data["distilled_strategies"][0]
    assert item["sha"] == "shaX"
    assert item["reward_ema"] == 0.95


def test_distill_offline_strategies_fails_loudly_on_missing_schema(tmp_path: Path) -> None:
    """A malformed archive DB must not look like a successful empty distillation."""
    db_file = tmp_path / "missing-schema.db"
    sqlite3.connect(db_file).close()
    lib_file = tmp_path / "library.json"

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        distill_offline_strategies(db_file, lib_file, k=5)

    assert not lib_file.exists()
