# api.py — Evidence Ledger CRUD and SQLite Persistence Interface
#
# This file implements the durable SQLite-backed Evidence Ledger. It handles
# database connection setup, DDL schema bootstrapping, CRUD operations for
# EvidenceLedgerEntry artifacts, and dynamic trigger evaluations.
#
# Use cases:
# 1. Storing completed experiment results with full provenance.
# 2. Re-verifying artifact integrity hashes on read.
# 3. Querying prior evidence for surrogate training.
# 4. Performing re-litigation checks across entries.

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from factory.artifacts.api import (
    ArtifactHash,
    CycleId,
    EvidenceLedgerEntry,
    EvidenceResult,
    FactoryError,
    HypothesisId,
)
from factory.ledger.queries import (
    evaluate_trigger_state,
    run_high_uncertainty_with_dependents,
    run_top_cited_entries,
    run_top_high_surprise_with_dependents,
)

logger = logging.getLogger("factory.ledger.api")

CURRENT_SCHEMA_VERSION = "2"

# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------


class LedgerError(FactoryError):
    """Base exception for the ledger module."""

    pass


class LedgerWriteFailed(LedgerError):
    """Raised when SQLite insert/update operations fail."""

    pass


class LedgerCorruption(LedgerError):
    """Raised when stored provenance_hash doesn't match recomputed file hash."""

    pass


class EntryNotFound(LedgerError):
    """Raised when a queried hash has no record."""

    pass


class RelitigateCheckFailed(LedgerError):
    """Raised when a trigger condition check raises an exception."""

    pass


class DowngradedDueToStaleness(LedgerError):
    """Raised when trying to read an entry that has been marked stale."""

    pass


class LedgerSchemaMismatch(LedgerError):
    """Raised when DB schema version differs from code."""

    pass


# --------------------------------------------------------------------------
# Dataclasses
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerQuery:
    """Filter set for queries."""

    hypothesis_id: HypothesisId | None = None
    result: EvidenceResult | None = None
    simulator_id: str | None = None
    cycle_id: CycleId | None = None
    has_dissent: bool | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    include_stale: bool = False
    limit: int = 100
    order_by: Literal["created_at_desc", "created_at_asc", "citation_count_desc"] = (
        "created_at_desc"
    )


@dataclass(frozen=True)
class AuditTopCited:
    """Citation audit result row."""

    entry_hash: ArtifactHash
    hypothesis_id: HypothesisId
    citation_count: int
    max_downstream_uncertainty: float
    is_stale: bool


@dataclass(frozen=True)
class AuditHighUncertainty:
    """Uncertainty audit result row."""

    entry_hash: ArtifactHash
    hypothesis_id: HypothesisId
    primary_uncertainty: float
    downstream_dependent_count: int
    is_stale: bool


@dataclass(frozen=True)
class AuditHighSurprise:
    """Surprise audit result row."""

    entry_hash: ArtifactHash
    hypothesis_id: HypothesisId
    surprise_bits: float | None
    downstream_citation_count: int
    composite_score: float
    is_stale: bool


@dataclass(frozen=True)
class TriggerEvaluationReport:
    """Result of running a trigger evaluation."""

    entry_hash: ArtifactHash
    trigger_index: int
    condition: str
    previous_state: bool
    new_state: bool
    error: str | None = None


@dataclass(frozen=True)
class TrainingDataQuery:
    """Filter query for surrogate model training data."""

    observable: str
    simulator_id: str | None = None
    min_seeds: int = 1
    include_stale: bool = False
    created_after: datetime | None = None
    limit: int = 10_000


@dataclass(frozen=True)
class LedgerTrainingRow:
    """Minimal record for surrogate model consumption."""

    hypothesis_id: HypothesisId
    feature_vector: Sequence[float]
    true_value: float
    uncertainty: float
    provenance_hash: ArtifactHash


# --------------------------------------------------------------------------
# EvidenceLedgerReader
# --------------------------------------------------------------------------


class EvidenceLedgerReader:
    """Read-only interface wrapper for spec 010 (surrogates)."""

    def __init__(self, ledger: Ledger) -> None:
        logger.info("EvidenceLedgerReader.__init__")
        self._ledger = ledger

    def query_observable(self, q: TrainingDataQuery) -> Sequence[LedgerTrainingRow]:
        """Queries training data for surrogate models."""
        logger.info("query_observable(q=%s)", q)
        # Live query execution.
        # Find entries matching the observable and constraints.
        results: list[LedgerTrainingRow] = []

        # Pull entries from the underlying SQLite.
        cursor = self._ledger._conn.cursor()
        query_sql = """
            SELECT e.entry_hash, e.hypothesis_id, e.primary_uncertainty
            FROM entries e
            WHERE e.is_stale = 0 OR ?
        """
        params: list[Any] = [int(q.include_stale)]

        if q.simulator_id:
            query_sql += " AND e.simulator_id = ?"
            params.append(q.simulator_id)

        if q.created_after:
            query_sql += " AND e.created_at >= ?"
            params.append(q.created_after.isoformat())

        query_sql += " LIMIT ?"
        params.append(q.limit)

        cursor.execute(query_sql, params)
        rows = cursor.fetchall()

        for r in rows:
            entry_hash = r[0]
            hypothesis_id = HypothesisId(r[1])
            uncertainty = r[2] or 0.0

            # Fetch the actual entry to unpack the values.
            try:
                entry = self._ledger.get_by_hash(ArtifactHash(entry_hash))
                # For Phase A, mock a mock feature vector and value
                results.append(
                    LedgerTrainingRow(
                        hypothesis_id=hypothesis_id,
                        feature_vector=(0.5, 0.2, 0.1),
                        true_value=entry.uncertainty.point_estimate,
                        uncertainty=uncertainty,
                        provenance_hash=ArtifactHash(entry_hash),
                    )
                )
            except Exception as e:
                # Fail loud per spec 012 requirement
                raise LedgerCorruption(f"Failed to read training row {entry_hash}: {e}") from e

        return results


# --------------------------------------------------------------------------
# Main Ledger Class
# --------------------------------------------------------------------------


class Ledger:
    """The Evidence Ledger store class."""

    def __init__(
        self,
        db_path: Path | str = Path("runs/ledger.db"),
        cycle_id: CycleId | None = None,
        artifact_root: Path = Path("runs"),
        mock_mode: bool = False,
        verify_on_read: bool = True,
    ) -> None:
        logger.info(
            "Ledger.__init__(db_path=%s, cycle_id=%s, mock_mode=%s)",
            db_path,
            cycle_id,
            mock_mode,
        )
        self._db_path = ":memory:" if mock_mode else db_path
        self._cycle_id = cycle_id or CycleId("cycle-default")
        self._artifact_root = artifact_root
        self._verify_on_read = verify_on_read
        self._allow_stale = False

        # Setup connection
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row

        # Apply Pragmas
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._conn.execute("PRAGMA synchronous = NORMAL;")
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA busy_timeout = 5000;")

        self._bootstrap_schema()

    def _bootstrap_schema(self) -> None:
        """Bootstraps the database tables and metadata version checks."""
        logger.info("_bootstrap_schema() called")
        cursor = self._conn.cursor()

        # Create schema_meta
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

        # Check version
        cursor.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'")
        row = cursor.fetchone()
        if row:
            version = row[0]
            if version == "1":
                from factory.ledger.migration import migrate_evidence_ledger

                migrate_evidence_ledger(self._conn)
            elif version != CURRENT_SCHEMA_VERSION:
                raise LedgerSchemaMismatch(
                    f"Expected schema version {CURRENT_SCHEMA_VERSION}, found {version}"
                )
        else:
            cursor.execute(
                "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?)",
                (CURRENT_SCHEMA_VERSION,),
            )
            cursor.execute("INSERT INTO schema_meta (key, value) VALUES ('phase', 'A')")

        # Create entries
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                entry_hash         TEXT PRIMARY KEY,
                hypothesis_id      TEXT NOT NULL,
                result             TEXT NOT NULL CHECK (
                    result IN ('passed','falsified','intractable','inconclusive')
                ),
                simulator_id       TEXT,
                cycle_id           TEXT NOT NULL,
                has_dissent_flag   INTEGER NOT NULL DEFAULT 0,
                primary_uncertainty REAL,
                surprise_bits      REAL,
                run_report_hash    TEXT,
                is_stale           INTEGER NOT NULL DEFAULT 0,
                stale_reason       TEXT,
                stale_marked_by    TEXT,
                stale_marked_at    TEXT,
                created_at         TEXT NOT NULL,
                json_path          TEXT NOT NULL
            );
            """
        )

        # Create indexes
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_entries_hypothesis ON entries (hypothesis_id);"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_result     ON entries (result);")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_entries_simulator  ON entries (simulator_id);"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_created    ON entries (created_at);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_stale      ON entries (is_stale);")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_entries_surprise   ON entries (surprise_bits);"
        )

        # Create provenance_blocks
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS provenance_blocks (
                entry_hash         TEXT PRIMARY KEY
                    REFERENCES entries(entry_hash) ON DELETE CASCADE,
                code_hash          TEXT NOT NULL,
                env_hash           TEXT NOT NULL,
                input_hash         TEXT NOT NULL,
                seed               INTEGER,
                simulator_version  TEXT,
                container_sha      TEXT
            );
            """
        )

        # Create relitigate_triggers
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS relitigate_triggers (
                entry_hash             TEXT NOT NULL
                    REFERENCES entries(entry_hash) ON DELETE CASCADE,
                trigger_index          INTEGER NOT NULL,
                condition              TEXT NOT NULL,
                check_fn               TEXT NOT NULL,
                last_evaluated_at      TEXT,
                currently_satisfied    INTEGER NOT NULL DEFAULT 0,
                last_error             TEXT,
                PRIMARY KEY (entry_hash, trigger_index)
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_triggers_satisfied
            ON relitigate_triggers (currently_satisfied);
            """
        )

        # Create council_verdict_refs
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS council_verdict_refs (
                entry_hash       TEXT NOT NULL
                    REFERENCES entries(entry_hash) ON DELETE CASCADE,
                verdict_hash     TEXT NOT NULL,
                council_id       TEXT NOT NULL,
                PRIMARY KEY (entry_hash, verdict_hash)
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_verdict_refs_verdict
            ON council_verdict_refs (verdict_hash);
            """
        )

        # Create run_report_refs
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS run_report_refs (
                entry_hash       TEXT PRIMARY KEY
                    REFERENCES entries(entry_hash) ON DELETE CASCADE,
                run_report_hash  TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_run_report_refs_report
            ON run_report_refs (run_report_hash);
            """
        )

        # Create entry_citations
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS entry_citations (
                cited_hash       TEXT NOT NULL,
                citing_hash      TEXT NOT NULL REFERENCES entries(entry_hash) ON DELETE CASCADE,
                PRIMARY KEY (cited_hash, citing_hash)
            );
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_citations_cited  ON entry_citations (cited_hash);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_citations_citing ON entry_citations (citing_hash);"
        )

        self._conn.commit()

    # ------------- CRUD -------------

    def insert_entry(self, entry: EvidenceLedgerEntry) -> ArtifactHash:
        """Inserts a new EvidenceLedgerEntry into the ledger DB and writes JSON."""
        logger.info("insert_entry(hypothesis_id=%s)", entry.hypothesis_id)
        entry.verify_self()

        # Idempotency
        cursor = self._conn.cursor()
        cursor.execute("SELECT 1 FROM entries WHERE entry_hash = ?", (entry.provenance_hash,))
        if cursor.fetchone():
            return entry.provenance_hash

        # Compute uncertainty summary
        primary_uncertainty = abs(entry.uncertainty.ci_upper - entry.uncertainty.ci_lower) / 2.0

        # Construct path
        json_rel_path = f"{self._cycle_id}/artifacts/{entry.provenance_hash}.json"
        full_json_path = self._artifact_root / json_rel_path

        # Write JSON file first (source of truth)
        full_json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_json_path, "w", encoding="utf-8") as f:
            f.write(entry.model_dump_json(indent=2))

        try:
            with self._conn:
                # Main entries row
                self._conn.execute(
                    """
                    INSERT INTO entries (
                        entry_hash, hypothesis_id, result, simulator_id, cycle_id,
                        has_dissent_flag, primary_uncertainty, surprise_bits, run_report_hash,
                        is_stale, created_at, json_path
                    ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        entry.provenance_hash,
                        entry.hypothesis_id,
                        entry.result.value,
                        entry.provenance.simulator_id,
                        self._cycle_id,
                        primary_uncertainty,
                        entry.surprise_bits,
                        entry.run_report_hash,
                        entry.created_at.isoformat(),
                        json_rel_path,
                    ),
                )

                # Provenance row
                self._conn.execute(
                    """
                    INSERT INTO provenance_blocks (
                        entry_hash, code_hash, env_hash, input_hash, seed,
                        simulator_version, container_sha
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.provenance_hash,
                        entry.provenance.code_hash,
                        entry.provenance.env_hash,
                        entry.provenance.input_hash,
                        entry.provenance.seed,
                        entry.provenance.simulator_version,
                        entry.provenance.container_sha,
                    ),
                )

                # Triggers
                for idx, trigger in enumerate(entry.relitigate_if):
                    self._conn.execute(
                        """
                        INSERT INTO relitigate_triggers (
                            entry_hash, trigger_index, condition, check_fn,
                            last_evaluated_at, currently_satisfied
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            entry.provenance_hash,
                            idx,
                            trigger.condition,
                            trigger.check_fn,
                            trigger.last_evaluated_at.isoformat()
                            if trigger.last_evaluated_at
                            else None,
                            int(trigger.currently_satisfied),
                        ),
                    )

                # Verdict references
                for v_hash in entry.council_verdict_hashes:
                    self._conn.execute(
                        """
                        INSERT INTO council_verdict_refs
                            (entry_hash, verdict_hash, council_id)
                        VALUES (?, ?, ?)
                        """,
                        (entry.provenance_hash, v_hash, "C1"),
                    )

                # Run report references
                if entry.run_report_hash:
                    self._conn.execute(
                        "INSERT INTO run_report_refs (entry_hash, run_report_hash) VALUES (?, ?)",
                        (entry.provenance_hash, entry.run_report_hash),
                    )

                # Citations
                for parent_hash in entry.parent_hashes:
                    cursor.execute("SELECT 1 FROM entries WHERE entry_hash = ?", (parent_hash,))
                    if cursor.fetchone():
                        self._conn.execute(
                            "INSERT INTO entry_citations (cited_hash, citing_hash) VALUES (?, ?)",
                            (parent_hash, entry.provenance_hash),
                        )
        except sqlite3.OperationalError as e:
            logger.error("Ledger write failed: %s", e)
            raise LedgerWriteFailed(f"Database write failed: {e}") from e

        return entry.provenance_hash

    def get_by_hash(self, entry_hash: ArtifactHash) -> EvidenceLedgerEntry:
        """Retrieves and verifies a ledger entry."""
        logger.info("get_by_hash(entry_hash=%s)", entry_hash)
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT json_path, is_stale FROM entries WHERE entry_hash = ?", (entry_hash,)
        )
        row = cursor.fetchone()
        if not row:
            raise EntryNotFound(f"No entry found for hash: {entry_hash}")
        if row["is_stale"] and not self._allow_stale:
            raise DowngradedDueToStaleness(f"Entry {entry_hash} is stale.")

        path = self._artifact_root / row["json_path"]
        if not path.exists():
            raise EntryNotFound(f"JSON artifact file missing at: {path}")

        try:
            with open(path, "rb") as f:
                entry = EvidenceLedgerEntry.from_json(json.load(f))
        except Exception as e:
            raise LedgerCorruption(f"Artifact JSON is corrupt or invalid: {e}") from e

        if self._verify_on_read:
            entry.verify_self()
            if entry.provenance_hash != entry_hash:
                raise LedgerCorruption("Hash verification failed.")

        return entry

    def get_by_id(self, hypothesis_id: HypothesisId) -> list[EvidenceLedgerEntry]:
        """Gets all entries for a given hypothesis ID, sorted newest first."""
        logger.info("get_by_id(hypothesis_id=%s)", hypothesis_id)
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT entry_hash FROM entries WHERE hypothesis_id = ? ORDER BY created_at DESC",
            (hypothesis_id,),
        )
        rows = cursor.fetchall()
        entries = []
        for r in rows:
            try:
                entries.append(self.get_by_hash(ArtifactHash(r[0])))
            except DowngradedDueToStaleness:
                continue
        return entries

    def query(self, q: LedgerQuery) -> list[EvidenceLedgerEntry]:
        """Performs a filtered query of ledger entries."""
        logger.info("query(q=%s)", q)
        cursor = self._conn.cursor()

        sql = "SELECT entry_hash FROM entries WHERE 1=1"
        params: list[Any] = []

        if not q.include_stale:
            sql += " AND is_stale = 0"
        if q.hypothesis_id:
            sql += " AND hypothesis_id = ?"
            params.append(q.hypothesis_id)
        if q.result:
            sql += " AND result = ?"
            params.append(q.result.value)
        if q.simulator_id:
            sql += " AND simulator_id = ?"
            params.append(q.simulator_id)
        if q.cycle_id:
            sql += " AND cycle_id = ?"
            params.append(q.cycle_id)
        if q.created_after:
            sql += " AND created_at >= ?"
            params.append(q.created_after.isoformat())
        if q.created_before:
            sql += " AND created_at <= ?"
            params.append(q.created_before.isoformat())

        if q.order_by == "created_at_desc":
            sql += " ORDER BY created_at DESC"
        elif q.order_by == "created_at_asc":
            sql += " ORDER BY created_at ASC"

        sql += " LIMIT ?"
        params.append(q.limit)

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        entries = []
        for r in rows:
            try:
                entries.append(self.get_by_hash(ArtifactHash(r[0])))
            except DowngradedDueToStaleness:
                continue
        return entries

    def update_relitigate_status(
        self,
        entry_hash: ArtifactHash,
        trigger_index: int,
        currently_satisfied: bool,
    ) -> None:
        """Updates the satisfaction status of a specific trigger index."""
        logger.info(
            "update_relitigate_status(entry_hash=%s, idx=%d, satisfied=%s)",
            entry_hash,
            trigger_index,
            currently_satisfied,
        )
        with self._conn:
            self._conn.execute(
                """
                UPDATE relitigate_triggers
                SET currently_satisfied = ?, last_evaluated_at = ?
                WHERE entry_hash = ? AND trigger_index = ?
                """,
                (
                    int(currently_satisfied),
                    datetime.now(UTC).isoformat(),
                    entry_hash,
                    trigger_index,
                ),
            )

    def mark_stale(self, entry_hash: ArtifactHash, reason: str, marked_by: str) -> None:
        """Flags an entry as stale, excluding it from default queries."""
        logger.info("mark_stale(entry_hash=%s)", entry_hash)
        with self._conn:
            self._conn.execute(
                """
                UPDATE entries
                SET is_stale = 1, stale_reason = ?, stale_marked_by = ?, stale_marked_at = ?
                WHERE entry_hash = ?
                """,
                (reason, marked_by, datetime.now(UTC).isoformat(), entry_hash),
            )

    def update_surprise(self, entry_hash: ArtifactHash, bits: float) -> None:
        """Writes/updates the surprise bits index on an entry."""
        logger.info("update_surprise(entry_hash=%s, bits=%f)", entry_hash, bits)
        cursor = self._conn.cursor()
        cursor.execute("SELECT 1 FROM entries WHERE entry_hash = ?", (entry_hash,))
        if not cursor.fetchone():
            raise EntryNotFound(f"No entry found for hash: {entry_hash}")

        with self._conn:
            self._conn.execute(
                "UPDATE entries SET surprise_bits = ? WHERE entry_hash = ?",
                (bits, entry_hash),
            )

    # ------------- Audit (C5 surface) -------------

    def top_cited_entries(self, k: int = 20, min_uncertainty: float = 0.0) -> list[AuditTopCited]:
        """Retrieves top cited entries for audit."""
        logger.info("top_cited_entries(k=%d)", k)
        rows = run_top_cited_entries(self._conn, k, min_uncertainty)
        return [
            AuditTopCited(
                entry_hash=ArtifactHash(r[0]),
                hypothesis_id=HypothesisId(r[1]),
                citation_count=r[2],
                max_downstream_uncertainty=r[3] or 0.0,
                is_stale=bool(r[4]),
            )
            for r in rows
        ]

    def high_uncertainty_with_dependents(
        self,
        uncertainty_threshold: float,
        min_dependents: int = 1,
    ) -> list[AuditHighUncertainty]:
        """Retrieves high uncertainty entries with dependents."""
        logger.info("high_uncertainty_with_dependents")
        rows = run_high_uncertainty_with_dependents(
            self._conn, uncertainty_threshold, min_dependents
        )
        return [
            AuditHighUncertainty(
                entry_hash=ArtifactHash(r[0]),
                hypothesis_id=HypothesisId(r[1]),
                primary_uncertainty=r[2],
                downstream_dependent_count=r[3],
                is_stale=bool(r[4]),
            )
            for r in rows
        ]

    def top_high_surprise_with_dependents(self, k: int) -> list[AuditHighSurprise]:
        """Retrieves surprise × citation composite ranking list."""
        logger.info("top_high_surprise_with_dependents(k=%d)", k)
        rows = run_top_high_surprise_with_dependents(self._conn, k)
        return [
            AuditHighSurprise(
                entry_hash=ArtifactHash(r[0]),
                hypothesis_id=HypothesisId(r[1]),
                surprise_bits=r[2],
                downstream_citation_count=r[3],
                composite_score=r[4],
                is_stale=bool(r[5]),
            )
            for r in rows
        ]

    def flagged_stale_entries(self) -> list[EvidenceLedgerEntry]:
        """Gets all stale entries."""
        logger.info("flagged_stale_entries")
        self._allow_stale = True
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT entry_hash FROM entries WHERE is_stale = 1")
            rows = cursor.fetchall()
            return [self.get_by_hash(ArtifactHash(r[0])) for r in rows]
        finally:
            self._allow_stale = False

    # ------------- Verification -------------

    def verify(self, entry_hash: ArtifactHash, deep: bool = False) -> None:
        """Verifies the integrity of a stored entry."""
        logger.info("verify(entry_hash=%s, deep=%s)", entry_hash, deep)
        # Fetching executes verify_self
        self.get_by_hash(entry_hash)

    # ------------- Re-litigation -------------

    def evaluate_triggers(
        self,
        entry_hashes: Sequence[ArtifactHash] | None = None,
    ) -> list[TriggerEvaluationReport]:
        """Evaluates triggers for given entries and updates DB."""
        logger.info("evaluate_triggers(entry_hashes=%s)", entry_hashes)
        reports = []
        cursor = self._conn.cursor()

        sql = (
            "SELECT entry_hash, trigger_index, condition, check_fn, currently_satisfied "
            "FROM relitigate_triggers"
        )
        params: list[Any] = []
        if entry_hashes:
            placeholders = ",".join("?" for _ in entry_hashes)
            sql += f" WHERE entry_hash IN ({placeholders})"
            params.extend(entry_hashes)

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        for r in rows:
            e_hash = r[0]
            idx = r[1]
            cond = r[2]
            check_fn = r[3]
            curr_sat = bool(r[4])

            try:
                new_state = evaluate_trigger_state(
                    e_hash, idx, check_fn, self._cycle_id, self._artifact_root
                )
                err = None
            except Exception as e:
                new_state = curr_sat
                err = str(e)

            self.update_relitigate_status(ArtifactHash(e_hash), idx, new_state)
            reports.append(
                TriggerEvaluationReport(
                    entry_hash=ArtifactHash(e_hash),
                    trigger_index=idx,
                    condition=cond,
                    previous_state=curr_sat,
                    new_state=new_state,
                    error=err,
                )
            )

        return reports

    # ------------- Backup / Export -------------

    def export(self, dst: Path, output_format: Literal["jsonl"] = "jsonl") -> int:
        """Exports ledger entries to a JSONL file."""
        logger.info("export(dst=%s)", dst)
        if output_format != "jsonl":
            raise LedgerError(f"Unsupported export format: {output_format}")
        cursor = self._conn.cursor()
        cursor.execute("SELECT entry_hash, is_stale, surprise_bits FROM entries")
        rows = cursor.fetchall()

        count = 0
        with open(dst, "w", encoding="utf-8") as f:
            for r in rows:
                entry = self.get_by_hash(ArtifactHash(r[0]))
                payload = entry.model_dump(mode="json")
                # Add private sidecar state
                payload["_ledger_state"] = {
                    "is_stale": bool(r[1]),
                    "surprise_bits": r[2],
                }
                f.write(json.dumps(payload) + "\n")
                count += 1
        return count

    def restore(self, src: Path, input_format: Literal["jsonl"] = "jsonl") -> int:
        """Restores ledger entries from a JSONL file."""
        logger.info("restore(src=%s)", src)
        if input_format != "jsonl":
            raise LedgerError(f"Unsupported restore format: {input_format}")
        # Refuse non-empty
        cursor = self._conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM entries")
        if cursor.fetchone()[0] > 0:
            raise LedgerError("Cannot restore onto a non-empty database.")

        count = 0
        with open(src, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                sidecar = data.pop("_ledger_state", {})
                entry = EvidenceLedgerEntry.from_json(data)

                # Insert entry
                self.insert_entry(entry)

                # Restore mutable sidecar state
                if sidecar.get("is_stale"):
                    self.mark_stale(entry.provenance_hash, "Restored stale status", "restore_op")
                if sidecar.get("surprise_bits") is not None:
                    self.update_surprise(entry.provenance_hash, sidecar["surprise_bits"])
                count += 1
        return count

    def close(self) -> None:
        """Closes connection."""
        logger.info("close() called")
        self._conn.close()

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()
