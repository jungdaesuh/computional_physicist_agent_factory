# offline.py — Offline Off-Path Strategy Distillation Cron Job
#
# This file implements the offline strategy distillation logic that runs
# during low-compute cycles. It analyzes the strategy archive database
# and distills top performing strategies to update a static strategy library.
#
# Use cases:
# 1. Distilling active strategies to update config/strategy_library.json.
# 2. Pruning or archiving historical low-performing strategies to optimize query speeds.

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("factory.strategy.offline")

JsonScalar = str | int | float | None


@dataclass(frozen=True, slots=True)
class DistilledStrategy:
    """Stable JSON shape for one distilled strategy-library row."""

    sha: str
    summary: str
    summary_md: str
    kind: str
    reward_ema: float | None
    feasible_count: int
    visits: int

    def as_json_object(self) -> dict[str, JsonScalar]:
        return {
            "sha": self.sha,
            "summary": self.summary,
            "summary_md": self.summary_md,
            "kind": self.kind,
            "reward_ema": self.reward_ema,
            "feasible_count": self.feasible_count,
            "visits": self.visits,
        }


def distill_offline_strategies(
    db_path: Path | str,
    library_output_path: Path | str,
    k: int = 10,
) -> int:
    """Analyze the strategy archive database and distill the top-K productive strategies.

    Saves the distilled strategy metadata to a strategy library JSON.

    Args:
        db_path: Path to the SQLite strategy archive database.
        library_output_path: Path where the compiled JSON library will be saved.
        k: Maximum number of strategies to distill.

    Returns:
        The number of strategies distilled and written to the library.
    """
    logger.info("distill_offline_strategies(db_path=%s, k=%d)", db_path, k)
    with closing(sqlite3.connect(db_path)) as conn:
        cursor = conn.cursor()
        rows = cursor.execute(
            """
            SELECT sha, summary, summary_md, kind, reward_ema, feasible_count, visits
              FROM strategies
             WHERE reward_ema IS NOT NULL
             ORDER BY reward_ema DESC, feasible_count DESC, sha ASC
             LIMIT ?
            """,
            (k,),
        ).fetchall()

    distilled = tuple(
        DistilledStrategy(
            sha=row[0],
            summary=row[1],
            summary_md=row[2],
            kind=row[3],
            reward_ema=row[4],
            feasible_count=row[5],
            visits=row[6],
        )
        for row in rows
    )

    # Write output JSON library
    out_path = Path(library_output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {"distilled_strategies": [item.as_json_object() for item in distilled]},
            f,
            indent=2,
        )

    logger.info("Successfully distilled %d strategies to %s", len(distilled), out_path)
    return len(distilled)
