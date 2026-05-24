# queries.py — SQL Audit Queries and Helper functions for the Evidence Ledger
#
# This file contains the SQLite queries and database operations for auditing
# compounding internal hallucinations, evaluating triggers, and backing up the ledger.
#
# Use cases:
# 1. Ranking entries by citation count to spot high-leverage findings (top_cited_entries).
# 2. Shortlisting high-uncertainty entries with dependent child nodes.
# 3. Querying surprise-bits × citation composites (top_high_surprise_with_dependents).
# 4. Evaluating dotted-path trigger conditions.

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3


logger = logging.getLogger("factory.ledger.queries")


def run_top_cited_entries(conn: sqlite3.Connection, k: int, min_uncertainty: float) -> list[Any]:
    """Runs the top cited entries query against the DB connection."""
    logger.info("run_top_cited_entries(k=%d, min_uncertainty=%f)", k, min_uncertainty)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT e.entry_hash,
               e.hypothesis_id,
               COUNT(c.citing_hash)         AS citation_count,
               MAX(child.primary_uncertainty) AS max_downstream_uncertainty,
               e.is_stale
          FROM entries        AS e
          JOIN entry_citations AS c    ON c.cited_hash = e.entry_hash
          JOIN entries        AS child ON child.entry_hash = c.citing_hash
         WHERE e.is_stale = 0
           AND e.primary_uncertainty >= ?
         GROUP BY e.entry_hash
         ORDER BY citation_count DESC
         LIMIT ?
        """,
        (min_uncertainty, k),
    )
    return cursor.fetchall()


def run_high_uncertainty_with_dependents(
    conn: sqlite3.Connection, threshold: float, min_dependents: int
) -> list[Any]:
    """Runs the high uncertainty with dependents query."""
    logger.info(
        "run_high_uncertainty_with_dependents(threshold=%f, min_dependents=%d)",
        threshold,
        min_dependents,
    )
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT e.entry_hash,
               e.hypothesis_id,
               e.primary_uncertainty,
               COUNT(c.citing_hash) AS downstream_dependent_count,
               e.is_stale
          FROM entries        AS e
          LEFT JOIN entry_citations AS c ON c.cited_hash = e.entry_hash
         WHERE e.is_stale = 0
           AND e.primary_uncertainty >= ?
         GROUP BY e.entry_hash
        HAVING COUNT(c.citing_hash) >= ?
         ORDER BY (e.primary_uncertainty * COUNT(c.citing_hash)) DESC
        """,
        (threshold, min_dependents),
    )
    return cursor.fetchall()


def run_top_high_surprise_with_dependents(conn: sqlite3.Connection, k: int) -> list[Any]:
    """Runs the surprise x citation audit query (FIX_PLAN §26.4)."""
    logger.info("run_top_high_surprise_with_dependents(k=%d)", k)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT e.entry_hash,
               e.hypothesis_id,
               e.surprise_bits,
               COALESCE(COUNT(c.citing_hash), 0) AS downstream_citation_count,
               COALESCE(
                   e.surprise_bits * COUNT(c.citing_hash),
                   0.0
               ) AS composite_score,
               e.is_stale
          FROM entries        AS e
          LEFT JOIN entry_citations AS c ON c.cited_hash = e.entry_hash
         WHERE e.is_stale = 0
         GROUP BY e.entry_hash
         ORDER BY (e.surprise_bits IS NULL) ASC,
                  composite_score DESC
         LIMIT ?
        """,
        (k,),
    )
    return cursor.fetchall()


def resolve_dotted_path(path: str) -> Any:
    """Dynamically resolves a dotted path to a Python function/callable."""
    logger.info("resolve_dotted_path(path=%s)", path)
    try:
        module_name, func_name = path.rsplit(".", 1)
        module = importlib.import_module(module_name)
        return getattr(module, func_name)
    except Exception as e:
        logger.error("Failed to resolve dotted path %s: %s", path, e)
        raise ImportError(f"Cannot resolve path: {path}") from e


def evaluate_trigger_state(
    entry_hash: str,
    trigger_index: int,
    check_fn_path: str,
    cycle_id: str,
    artifact_root: Path,
) -> bool:
    """Resolves and evaluates a trigger check function."""
    logger.info(
        "evaluate_trigger_state(entry_hash=%s, trigger_index=%s, check_fn_path=%s)",
        entry_hash,
        trigger_index,
        check_fn_path,
    )
    # Built-in fallback implementations for Phase A
    if check_fn_path == "factory.ledger.triggers.simulator_version_changed":
        # Returns False by default in mock/Phase A
        return False
    elif (
        check_fn_path == "factory.ledger.triggers.container_sha_changed"
        or check_fn_path == "factory.ledger.triggers.surrogate_retrained_after"
        or check_fn_path == "factory.ledger.triggers.domain_scope_expanded"
    ):
        return False

    # Otherwise try dynamic import
    func = resolve_dotted_path(check_fn_path)
    return bool(func(entry_hash=entry_hash, cycle_id=cycle_id, artifact_root=artifact_root))
