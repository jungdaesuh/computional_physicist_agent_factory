# transfer.py — Priors Transfer between Strategy Archives
#
# This file implements the priors transfer logic, enabling cross-run transfer
# of successful strategies from previous problem runs into a new archive.
#
# Use cases:
# 1. Loading top strategies from a historical problem_id to seed a new experiment.

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger("factory.strategy.transfer")


def transfer_priors_from(
    conn: sqlite3.Connection,
    dest_experiment_id: int,
    source_problem_id: str,
    k: int,
) -> None:
    """Import the top-K strategies from another sibling experiment by problem ID.

    Args:
        conn: SQLite connection to the strategy archive database.
        dest_experiment_id: The target experiment ID to copy strategies to.
        source_problem_id: The problem ID of the source experiment to copy from.
        k: The maximum number of top strategies to transfer.
    """
    logger.info(
        "transfer_priors_from(dest_experiment_id=%d, source_problem_id=%s, k=%d)",
        dest_experiment_id,
        source_problem_id,
        k,
    )

    cursor = conn.cursor()

    source_rows = cursor.execute(
        "SELECT id FROM experiments WHERE problem_id = ? ORDER BY id DESC",
        (source_problem_id,),
    ).fetchall()

    if not source_rows:
        logger.warning("No historical experiments found with problem_id %s", source_problem_id)
        return

    source_experiment_ids = [row[0] for row in source_rows]

    placeholders = ",".join("?" for _ in source_experiment_ids)
    query = f"""
        SELECT sha, summary_md, kind, summary, experiment_id
          FROM strategies
         WHERE experiment_id IN ({placeholders})
           AND reward_ema IS NOT NULL
         ORDER BY reward_ema DESC, feasible_count DESC, sha ASC
         LIMIT ?
    """
    params = source_experiment_ids + [k]
    rows = cursor.execute(query, params).fetchall()

    for sha, summary_md, kind, summary, source_experiment_id in rows:
        cursor.execute(
            """
            INSERT OR IGNORE INTO strategies (
                sha, experiment_id, summary, summary_md, kind, provenance,
                reward_ema, surprise_ema, feasibility_distance_ema,
                feasible_count, visits, behavior_descriptor_json,
                constraint_overshoot_json
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, 0, NULL, NULL)
            """,
            (
                sha,
                dest_experiment_id,
                summary,
                summary_md,
                kind,
                f"transferred_from_exp_{source_experiment_id}",
            ),
        )
    conn.commit()
    logger.info("Transferred %d strategies successfully", len(rows))
