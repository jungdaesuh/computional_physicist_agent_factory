from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from factory.literature.api import OpenAlexGraphStore, OpenAlexWork, TraversalPolicy
from factory.literature.errors import GraphStoreCorruption


def test_graph_store_caches_work_edges_runs_rankings_and_detects_corruption(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = OpenAlexGraphStore(db_path)
    work = OpenAlexWork(
        work_id="W1",
        title="Root",
        abstract="root",
        referenced_work_ids=("W2",),
        related_work_ids=(),
        is_open_access=True,
        doi=None,
        citation_count=10,
    )
    run_id = store.start_run(("W1",), TraversalPolicy(1, 2, True).to_json_object())

    store.upsert_work(work)
    store.add_edge("W1", "W2", "backward", run_id)
    store.store_ranking(run_id, (work,))
    store.finish_run(run_id, visited_count=1, accepted_count=1)

    assert store.get_work("W1") == work
    assert store.edge_targets("W1", "backward") == ("W2",)
    assert store.edge_count(run_id) == 1
    assert store.ranking_count(run_id) == 1
    assert store.summary(run_id)["accepted_count"] == 1

    second_run_id = store.start_run(("W1",), TraversalPolicy(1, 2, True).to_json_object())
    store.add_edge("W1", "W2", "backward", second_run_id)
    assert store.edge_count() == 2
    store.close()

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE meta SET value = 'bad' WHERE key = 'schema_hash'")
    conn.commit()
    conn.close()

    with pytest.raises(GraphStoreCorruption):
        OpenAlexGraphStore(db_path)

    rebuilt = OpenAlexGraphStore(db_path, rebuild=True)
    assert rebuilt.summary() == {"works": 0, "edges": 0, "traversal_runs": 0}


def test_graph_store_validates_table_shape_even_when_hash_matches(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    store = OpenAlexGraphStore(db_path)
    store.close()

    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE edges")
    conn.execute(
        """
        CREATE TABLE edges (
            source_work_id TEXT NOT NULL,
            target_work_id TEXT NOT NULL,
            edge_kind TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(GraphStoreCorruption, match="edges"):
        OpenAlexGraphStore(db_path)
