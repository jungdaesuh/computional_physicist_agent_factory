"""SQLite cache for OpenAlex works, citation edges, and traversal runs."""

from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path

from factory.literature.client import OpenAlexWork
from factory.literature.errors import GraphStoreCorruption

_EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "meta": ("key", "value"),
    "works": ("work_id", "payload_json", "payload_sha256", "cached_at"),
    "edges": ("source_work_id", "target_work_id", "edge_kind", "traversal_run_id"),
    "traversal_runs": (
        "run_id",
        "seed_ids_json",
        "policy_json",
        "started_at",
        "completed_at",
        "visited_count",
        "accepted_count",
    ),
    "ranking_scores": ("run_id", "work_id", "score", "rank"),
}
_SCHEMA_HASH = hashlib.sha256(
    json.dumps(_EXPECTED_COLUMNS, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


class OpenAlexGraphStore:
    """Local OpenAlex graph cache kept separate from EvidenceLedger."""

    def __init__(self, db_path: Path, *, rebuild: bool = False) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if rebuild and self.db_path.exists():
            self.db_path.unlink()
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._bootstrap()

    def close(self) -> None:
        self._conn.close()

    def _bootstrap(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS works (
                work_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                cached_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS edges (
                source_work_id TEXT NOT NULL,
                target_work_id TEXT NOT NULL,
                edge_kind TEXT NOT NULL CHECK (edge_kind IN ('backward','forward','related')),
                traversal_run_id TEXT NOT NULL,
                PRIMARY KEY (source_work_id, target_work_id, edge_kind, traversal_run_id)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS traversal_runs (
                run_id TEXT PRIMARY KEY,
                seed_ids_json TEXT NOT NULL,
                policy_json TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                visited_count INTEGER NOT NULL,
                accepted_count INTEGER NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ranking_scores (
                run_id TEXT NOT NULL,
                work_id TEXT NOT NULL,
                score REAL NOT NULL,
                rank INTEGER NOT NULL,
                PRIMARY KEY (run_id, work_id)
            )
            """
        )
        cursor.execute("SELECT value FROM meta WHERE key = 'schema_hash'")
        row = cursor.fetchone()
        if row is None:
            cursor.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_hash', ?)",
                (_SCHEMA_HASH,),
            )
        elif row["value"] != _SCHEMA_HASH:
            raise GraphStoreCorruption(
                f"OpenAlexGraphStore schema hash mismatch at {self.db_path}"
            )
        self._validate_schema()
        self._conn.commit()

    def _validate_schema(self) -> None:
        for table_name, expected_columns in _EXPECTED_COLUMNS.items():
            observed_columns = tuple(
                str(row["name"])
                for row in self._conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            )
            if observed_columns != expected_columns:
                raise GraphStoreCorruption(
                    f"OpenAlexGraphStore table {table_name} schema mismatch at {self.db_path}"
                )

    def upsert_work(self, work: OpenAlexWork) -> None:
        payload = work.to_json_object()
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO works (work_id, payload_json, payload_sha256, cached_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(work_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    payload_sha256=excluded.payload_sha256,
                    cached_at=excluded.cached_at
                """,
                (
                    work.work_id,
                    payload_json,
                    payload_hash,
                    datetime.datetime.now(datetime.UTC).isoformat(),
                ),
            )

    def get_work(self, work_id: str) -> OpenAlexWork | None:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT payload_json, payload_sha256 FROM works WHERE work_id = ?",
            (work_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        payload_json = str(row["payload_json"])
        observed_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if observed_hash != row["payload_sha256"]:
            raise GraphStoreCorruption(f"Cached OpenAlex work hash mismatch: {work_id}")
        payload: object = json.loads(payload_json)
        if not isinstance(payload, dict):
            raise GraphStoreCorruption(f"Cached OpenAlex work is not an object: {work_id}")
        return OpenAlexWork.from_json_object(payload)

    def add_edge(
        self,
        source_work_id: str,
        target_work_id: str,
        edge_kind: str,
        traversal_run_id: str | None = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO edges (
                    source_work_id, target_work_id, edge_kind, traversal_run_id
                ) VALUES (?, ?, ?, ?)
                """,
                (source_work_id, target_work_id, edge_kind, traversal_run_id or ""),
            )

    def edge_targets(self, source_work_id: str, edge_kind: str) -> tuple[str, ...]:
        cursor = self._conn.cursor()
        rows = cursor.execute(
            """
            SELECT target_work_id
            FROM edges
            WHERE source_work_id = ? AND edge_kind = ?
            ORDER BY target_work_id
            """,
            (source_work_id, edge_kind),
        ).fetchall()
        return tuple(str(row["target_work_id"]) for row in rows)

    def edge_count(self, run_id: str | None = None) -> int:
        cursor = self._conn.cursor()
        if run_id is None:
            row = cursor.execute("SELECT COUNT(*) AS n FROM edges").fetchone()
        else:
            row = cursor.execute(
                "SELECT COUNT(*) AS n FROM edges WHERE traversal_run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row["n"])

    def ranking_count(self, run_id: str) -> int:
        cursor = self._conn.cursor()
        row = cursor.execute(
            "SELECT COUNT(*) AS n FROM ranking_scores WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row["n"])

    def start_run(self, seed_ids: tuple[str, ...], policy: Mapping[str, object]) -> str:
        policy_json = json.dumps(dict(policy), sort_keys=True, separators=(",", ":"))
        seed_json = json.dumps(list(seed_ids), sort_keys=True, separators=(",", ":"))
        started_at = datetime.datetime.now(datetime.UTC).isoformat()
        run_id = hashlib.sha256(f"{seed_json}|{policy_json}|{started_at}".encode()).hexdigest()[:16]
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO traversal_runs (
                    run_id, seed_ids_json, policy_json, started_at,
                    completed_at, visited_count, accepted_count
                ) VALUES (?, ?, ?, ?, NULL, 0, 0)
                """,
                (run_id, seed_json, policy_json, started_at),
            )
        return run_id

    def finish_run(self, run_id: str, *, visited_count: int, accepted_count: int) -> None:
        with self._conn:
            self._conn.execute(
                """
                UPDATE traversal_runs
                SET completed_at = ?, visited_count = ?, accepted_count = ?
                WHERE run_id = ?
                """,
                (
                    datetime.datetime.now(datetime.UTC).isoformat(),
                    visited_count,
                    accepted_count,
                    run_id,
                ),
            )

    def store_ranking(self, run_id: str, ranked_works: tuple[OpenAlexWork, ...]) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM ranking_scores WHERE run_id = ?", (run_id,))
            for rank, work in enumerate(ranked_works, start=1):
                self._conn.execute(
                    """
                    INSERT INTO ranking_scores (run_id, work_id, score, rank)
                    VALUES (?, ?, ?, ?)
                    """,
                    (run_id, work.work_id, _ranking_score(work), rank),
                )

    def summary(self, run_id: str | None = None) -> dict[str, int | str]:
        cursor = self._conn.cursor()
        works_count = cursor.execute("SELECT COUNT(*) AS n FROM works").fetchone()["n"]
        edges_count = cursor.execute("SELECT COUNT(*) AS n FROM edges").fetchone()["n"]
        runs_count = cursor.execute("SELECT COUNT(*) AS n FROM traversal_runs").fetchone()["n"]
        summary: dict[str, int | str] = {
            "works": int(works_count),
            "edges": int(edges_count),
            "traversal_runs": int(runs_count),
        }
        if run_id is not None:
            row = cursor.execute(
                """
                SELECT visited_count, accepted_count
                FROM traversal_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is not None:
                summary["run_id"] = run_id
                summary["visited_count"] = int(row["visited_count"])
                summary["accepted_count"] = int(row["accepted_count"])
        return summary


def _ranking_score(work: OpenAlexWork) -> float:
    return float(work.citation_count + (10 if work.is_open_access else 0))


__all__ = ["OpenAlexGraphStore"]
