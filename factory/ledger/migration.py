# migration.py — SQLite database schema migrations for Ledger and Strategy Archive
#
# This file implements the DDL migrations to transition the database schemas
# from version 1 to version 2, supporting multi-experiment strategy mapping.
#
# Use cases:
# 1. Migrating StrategyArchive schema to PRIMARY KEY (sha, experiment_id)
#    and adding problem_id column to experiments table.
# 2. Migrating Evidence Ledger schema to version 2.

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger("factory.ledger.migration")


def migrate_strategy_archive(conn: sqlite3.Connection) -> None:
    """Migrate the Strategy Archive database schema to support multi-experiment keys.

    Updates the strategies table primary key to (sha, experiment_id) and adds
    problem_id to experiments table if not present.
    """
    logger.info("migrate_strategy_archive called")
    cursor = conn.cursor()

    # 1. Migrate experiments table (add problem_id)
    try:
        cursor.execute("ALTER TABLE experiments ADD COLUMN problem_id TEXT;")
        conn.commit()
        logger.info("Added problem_id column to experiments table.")
    except sqlite3.OperationalError:
        # Already exists
        pass

    # 2. Check if strategies primary key is only 'sha'
    # In SQLite, we can inspect table_info
    table_info = cursor.execute("PRAGMA table_info(strategies);").fetchall()
    # Find columns that are part of the primary key
    pk_cols = [row[1] for row in table_info if row[5] > 0]

    if len(pk_cols) == 1 and pk_cols[0] == "sha":
        logger.info("Migrating strategies table primary key to (sha, experiment_id)")

        # We need to recreate the table.
        # Rename old table
        cursor.execute("ALTER TABLE strategies RENAME TO strategies_old;")

        # Create new strategies table with compound primary key
        cursor.execute("""
            CREATE TABLE strategies (
                sha                         TEXT NOT NULL,
                experiment_id               INTEGER NOT NULL REFERENCES experiments(id),
                summary                     TEXT NOT NULL,
                summary_md                  TEXT NOT NULL,
                kind                        TEXT NOT NULL,
                provenance                  TEXT NOT NULL,
                reward_ema                  REAL,
                surprise_ema                REAL,
                feasibility_distance_ema    REAL,
                feasible_count              INTEGER NOT NULL DEFAULT 0,
                visits                      INTEGER NOT NULL DEFAULT 0,
                behavior_descriptor_json    TEXT,
                constraint_overshoot_json   TEXT,
                summary_evidence_version    INTEGER NOT NULL DEFAULT 0,
                summary_at_version          INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (sha, experiment_id)
            );
        """)

        # Get columns of strategies_old
        cursor.execute("PRAGMA table_info(strategies_old);")
        old_cols = {row[1] for row in cursor.fetchall()}

        col_selects = []
        col_selects.append("sha")
        col_selects.append("experiment_id" if "experiment_id" in old_cols else "1 AS experiment_id")
        col_selects.append("summary" if "summary" in old_cols else "'Legacy Strategy' AS summary")
        col_selects.append(
            "summary_md"
            if "summary_md" in old_cols
            else "'Legacy Strategy Description' AS summary_md"
        )
        col_selects.append("kind" if "kind" in old_cols else "'novel' AS kind")
        col_selects.append("provenance" if "provenance" in old_cols else "'legacy' AS provenance")

        for col in ["reward_ema", "surprise_ema", "feasibility_distance_ema"]:
            col_selects.append(col if col in old_cols else f"NULL AS {col}")
        for col in ["feasible_count", "visits"]:
            col_selects.append(col if col in old_cols else f"0 AS {col}")
        for col in ["behavior_descriptor_json", "constraint_overshoot_json"]:
            col_selects.append(col if col in old_cols else f"NULL AS {col}")

        select_clause = ", ".join(col_selects)

        cursor.execute(f"""
            INSERT INTO strategies (
                sha, experiment_id, summary, summary_md, kind, provenance,
                reward_ema, surprise_ema, feasibility_distance_ema,
                feasible_count, visits, behavior_descriptor_json, constraint_overshoot_json
            )
            SELECT {select_clause}
            FROM strategies_old;
        """)

        # Drop old table
        cursor.execute("DROP TABLE strategies_old;")
        conn.commit()
        logger.info("Successfully migrated strategies table primary key.")


def migrate_evidence_ledger(conn: sqlite3.Connection) -> None:
    """Migrate the Evidence Ledger schema to version 2."""
    logger.info("migrate_evidence_ledger called")
    cursor = conn.cursor()

    # Check current version
    cursor.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'")
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO schema_meta (key, value) VALUES ('schema_version', '1')")
        version = 1
    else:
        version = int(row[0])

    if version < 2:
        logger.info("Migrating Evidence Ledger schema from version 1 to 2")
        # In version 2, we update version in schema_meta
        cursor.execute("UPDATE schema_meta SET value = '2' WHERE key = 'schema_version'")
        conn.commit()
        logger.info("Evidence Ledger schema version updated to 2.")
