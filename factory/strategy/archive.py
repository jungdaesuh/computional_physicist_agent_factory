# archive.py — Strategy Archive Stateful sqlite3 Persistence Engine
#
# This file implements the StrategyArchive class, which persists strategies,
# parent-child lineages, and performance/surprise historical EMAs.
#
# Supported Workflows:
# 1. Strategy persistence and kind invariant validation (add_strategy).
# 2. Bayesian surprise updates via GuideLLM elicitation (attribute_surprise).
# 3. Objective and constraint-overshoot reward updates (attribute_reward).
# 4. Selection of productive parents using UCT scoring (select_lineages).
# 5. Retrieval of top-K strategies ranked by productivity (top_k).
# 6. Prior transfer from sibling experiments (transfer_priors_from).

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from factory.artifacts.strategies import (
    BehaviorDescriptor,
    Strategy,
    StrategyCycleEvidence,
    StrategyKind,
)
from factory.budget.api import BudgetTracker
from factory.llm_client.api import OpenRouterClient
from factory.strategy.beliefs import (
    FeasibilityBucket,
    GuideLLM,
    binary_bayesian_surprise,
    graded_bayesian_surprise,
)
from factory.strategy.errors import (
    GuideLLMRefusal,
    StrategyArchiveError,
)
from factory.strategy.strategy_config import StrategyArchiveConfig as StrategyArchiveConfig

logger = logging.getLogger("factory.strategy.archive")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _update_ema(old_ema: float | None, observed: float, alpha: float) -> float:
    """EMA update rule supporting cold start (first observation is old_ema=None)."""
    if old_ema is None:
        return observed
    return alpha * observed + (1.0 - alpha) * old_ema


def _compute_reward(evidence: StrategyCycleEvidence) -> float:
    """Canonical per-cycle reward calculation from evidence.

    Feasible candidates are the load-bearing signal. Once feasible, reward is
    the negated best objective. If not yet feasible, reward is the negated
    distance-to-feasible.
    """
    if evidence.feasible_count > 0:
        if evidence.best_objective is not None:
            return -float(evidence.best_objective)
        return 0.0

    if evidence.best_feasibility_distance is not None:
        return -float(evidence.best_feasibility_distance)
    return -1.0


def _load_parents(conn: sqlite3.Connection, child_sha: str) -> tuple[str, ...]:
    """Retrieve parents of a strategy child SHA."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT parent_sha FROM strategy_edges WHERE child_sha = ? ORDER BY parent_sha ASC",
        (child_sha,),
    )
    return tuple(row[0] for row in cursor.fetchall())


def _load_behavior_descriptor(bd_json: str | None) -> BehaviorDescriptor:
    """Safely deserialize a BehaviorDescriptor from DB JSON, defaulting to empty."""
    if bd_json is not None:
        try:
            data = json.loads(bd_json)
            if isinstance(data, dict):
                return BehaviorDescriptor.model_validate(data)
        except Exception:
            pass
    return BehaviorDescriptor(vector=(), cell_id=None)


def extract_json(text: str) -> dict[str, Any] | None:
    """Extract a dictionary from JSON block or raw text."""
    text = text.strip()
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        json_str = text[start : end + 1]
        try:
            val = json.loads(json_str)
            if isinstance(val, dict):
                return val
        except Exception:
            pass
    try:
        val = json.loads(text)
        if isinstance(val, dict):
            return val
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------
# Concrete & Mock LLM Clients
# --------------------------------------------------------------------------


class MockGuideLLM:
    """Mock GuideLLM client returning canned predictions for testing."""

    def __init__(
        self,
        bool_responses: list[bool] | None = None,
        bucket_responses: list[FeasibilityBucket] | None = None,
    ) -> None:
        self.bool_responses = bool_responses or [False] * 5 + [True] * 5
        default_buckets: list[FeasibilityBucket] = [
            "lt_10",
            "lt_10",
            "lt_10",
            "lt_10",
            "lt_10",
            "10_50",
            "10_50",
            "10_50",
            "10_50",
            "10_50",
        ]
        self.bucket_responses: list[FeasibilityBucket] = bucket_responses or default_buckets
        self._bool_idx = 0
        self._bucket_idx = 0

    async def boolean(self, prompt: str) -> bool:
        del prompt
        val = self.bool_responses[self._bool_idx % len(self.bool_responses)]
        self._bool_idx += 1
        return val

    async def feasibility_bucket(self, prompt: str) -> FeasibilityBucket:
        del prompt
        val = self.bucket_responses[self._bucket_idx % len(self.bucket_responses)]
        self._bucket_idx += 1
        return val


class GeminiFlashGuideLLM:
    """GuideLLM implementation routing to google/gemini-3.5-flash via OpenRouterClient."""

    def __init__(
        self,
        openrouter_client: OpenRouterClient,
        cycle_id: str,
        budget_tracker: BudgetTracker | None = None,
        experiment_id: int | None = None,
    ) -> None:
        self.client = openrouter_client
        self.cycle_id = cycle_id
        self.budget_tracker = budget_tracker
        self.experiment_id = experiment_id

    async def boolean(self, prompt: str) -> bool:
        logger.info("GeminiFlashGuideLLM.boolean prompt length=%d", len(prompt))
        last_err: Exception | None = None
        for attempt in (1, 2):
            start_time = time.time()
            try:
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: self.client.invoke(
                        messages=[{"role": "user", "content": prompt}],
                        model="google/gemini-3.5-flash",
                        response_format={"type": "json_object"},
                    ),
                )
                elapsed = time.time() - start_time
                if self.budget_tracker is not None:
                    from factory.artifacts.api import HypothesisId

                    self.budget_tracker.record(
                        hypothesis_id=HypothesisId(str(self.experiment_id or "default")),
                        module="factory.strategy",
                        cost_usd=response.cost_usd,
                        tokens=response.input_tokens + response.output_tokens,
                        wall_clock_seconds=elapsed,
                        description="GuideLLM elicitation call (boolean)",
                    )
                res_val = self._parse_boolean(response.text)
                self._write_trace(prompt, response.text, response.cost_usd, "success", None)
                return res_val
            except Exception as e:
                logger.warning("GeminiFlashGuideLLM.boolean attempt %d failed: %s", attempt, e)
                last_err = e
                self._write_trace(prompt, "", 0.0, "failure", str(e))
        raise GuideLLMRefusal("GuideLLM refused or failed twice on boolean prompt.") from last_err

    async def feasibility_bucket(self, prompt: str) -> FeasibilityBucket:
        logger.info("GeminiFlashGuideLLM.feasibility_bucket prompt length=%d", len(prompt))
        last_err: Exception | None = None
        for attempt in (1, 2):
            start_time = time.time()
            try:
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: self.client.invoke(
                        messages=[{"role": "user", "content": prompt}],
                        model="google/gemini-3.5-flash",
                        response_format={"type": "json_object"},
                    ),
                )
                elapsed = time.time() - start_time
                if self.budget_tracker is not None:
                    from factory.artifacts.api import HypothesisId

                    self.budget_tracker.record(
                        hypothesis_id=HypothesisId(str(self.experiment_id or "default")),
                        module="factory.strategy",
                        cost_usd=response.cost_usd,
                        tokens=response.input_tokens + response.output_tokens,
                        wall_clock_seconds=elapsed,
                        description="GuideLLM elicitation call (feasibility_bucket)",
                    )
                res_val = self._parse_bucket(response.text)
                self._write_trace(prompt, response.text, response.cost_usd, "success", None)
                return res_val
            except Exception as e:
                logger.warning(
                    "GeminiFlashGuideLLM.feasibility_bucket attempt %d failed: %s", attempt, e
                )
                last_err = e
                self._write_trace(prompt, "", 0.0, "failure", str(e))
        raise GuideLLMRefusal(
            "GuideLLM refused or failed twice on feasibility_bucket prompt."
        ) from last_err

    def _parse_boolean(self, text: str) -> bool:
        data = extract_json(text)
        if data is not None:
            for k, v in data.items():
                if k.lower() == "promising" and isinstance(v, bool):
                    return v
        raise ValueError(f"No valid boolean field 'promising' found in output: {text}")

    def _parse_bucket(self, text: str) -> FeasibilityBucket:
        data = extract_json(text)
        if data is not None:
            for k, v in data.items():
                if k.lower() == "feasibility_bucket" and v in ("lt_10", "10_50", "gt_50"):
                    return v  # type: ignore
        raise ValueError(f"No valid field 'feasibility_bucket' found in output: {text}")

    def _write_trace(
        self, prompt: str, response: str, cost: float, status: str, error: str | None
    ) -> None:
        try:
            trace_dir = Path("runs") / self.cycle_id / "strategy"
            trace_dir.mkdir(parents=True, exist_ok=True)
            trace_file = trace_dir / "guide_llm.jsonl"
            record = {
                "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "prompt": prompt,
                "response": response,
                "cost_usd": cost,
                "status": status,
                "error": error,
            }
            with open(trace_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.error("Failed to write GuideLLM trace: %s", e)


# --------------------------------------------------------------------------
# Main Archive Class
# --------------------------------------------------------------------------


class StrategyArchive:
    """BFTS + UCT + Bayesian-surprise + MAP-Elites sqlite3-based Strategy Archive."""

    def __init__(
        self,
        config: StrategyArchiveConfig,
        conn: sqlite3.Connection,
        guide_llm: GuideLLM | None,
        *,
        experiment_id: int,
        problem_id: str,
    ) -> None:
        logger.info(
            "StrategyArchive.__init__(experiment_id=%d, problem_id=%s)",
            experiment_id,
            problem_id,
        )
        self.config = config
        self.conn = conn
        self.guide_llm = guide_llm
        self.experiment_id = experiment_id
        self.problem_id = problem_id

        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite schema, tables, views, and indexes."""
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("CREATE TABLE IF NOT EXISTS experiments (id INTEGER PRIMARY KEY);")
        with suppress(sqlite3.OperationalError):
            self.conn.execute("ALTER TABLE experiments ADD COLUMN problem_id TEXT;")
        self.conn.execute(
            "INSERT OR IGNORE INTO experiments (id) VALUES (?);", (self.experiment_id,)
        )
        self.conn.execute(
            "UPDATE experiments SET problem_id = ? WHERE id = ?;",
            (self.problem_id, self.experiment_id),
        )

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
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

        from factory.ledger.migration import migrate_strategy_archive

        migrate_strategy_archive(self.conn)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_edges (
                parent_sha  TEXT NOT NULL REFERENCES strategies(sha),
                child_sha   TEXT NOT NULL REFERENCES strategies(sha),
                PRIMARY KEY (parent_sha, child_sha)
            );
        """)

        self.conn.execute("""
            CREATE VIEW IF NOT EXISTS strategy_subtree AS
            WITH RECURSIVE descent(root, sha, depth) AS (
                SELECT sha, sha, 0 FROM strategies
                UNION ALL
                SELECT d.root, e.child_sha, d.depth + 1
                  FROM descent d JOIN strategy_edges e ON e.parent_sha = d.sha
                 WHERE d.depth < 6
            )
            SELECT * FROM descent;
        """)

        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS strategies_experiment_id_idx ON strategies(experiment_id);"
        )
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS strategy_edges_parent_sha_idx
            ON strategy_edges(parent_sha);
            """
        )
        self.conn.commit()

    def add_strategy(
        self,
        summary_md: str,
        parents: tuple[str, ...],
        kind: StrategyKind,
    ) -> str:
        """Validate, canonicalize, and insert a new strategy node and its parent edges."""
        logger.info("add_strategy(parents=%s, kind=%s)", parents, kind)

        # Inferred kind invariants validation
        if kind == StrategyKind.MUTATE:
            if len(parents) != 1:
                raise StrategyArchiveError(
                    f"Mutate strategy must have exactly one parent, got {len(parents)}"
                )
        elif kind == StrategyKind.CROSSOVER:
            if len(parents) < 2:
                raise StrategyArchiveError(
                    f"Crossover strategy must have at least 2 parents, got {len(parents)}"
                )
        elif kind in (StrategyKind.NOVEL, StrategyKind.LIBRARY):
            if len(parents) != 0:
                raise StrategyArchiveError(
                    f"Novel or library strategy must have zero parents, got {len(parents)}"
                )
        else:
            raise StrategyArchiveError(f"Unknown strategy kind: {kind}")

        canonical_md = summary_md.strip()
        sha = hashlib.sha256(canonical_md.encode("utf-8")).hexdigest()
        summary = canonical_md.split("\n")[0][:100]

        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO strategies (
                sha, experiment_id, summary, summary_md, kind, provenance,
                reward_ema, surprise_ema, feasibility_distance_ema,
                feasible_count, visits, behavior_descriptor_json, constraint_overshoot_json
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 0, 0, NULL, NULL)
            """,
            (sha, self.experiment_id, summary, canonical_md, kind.value, "agent_authored"),
        )

        for parent in parents:
            cursor.execute(
                """
                INSERT OR IGNORE INTO strategy_edges (parent_sha, child_sha)
                VALUES (?, ?)
                """,
                (parent, sha),
            )

        self.conn.commit()
        return sha

    async def attribute_surprise(
        self,
        strategy_sha: str,
        evidence: StrategyCycleEvidence,
    ) -> float:
        """Compute Bayesian surprise on new evidence, update surprise EMA and visit counts."""
        logger.info(
            "attribute_surprise(strategy_sha=%s, cycle_id=%s)", strategy_sha, evidence.cycle_id
        )

        cursor = self.conn.cursor()
        row = cursor.execute(
            "SELECT summary_md, surprise_ema FROM strategies WHERE sha = ?",
            (strategy_sha,),
        ).fetchone()

        if row is None:
            raise StrategyArchiveError(f"Strategy {strategy_sha} not found in archive.")

        summary_md, old_surprise_ema = row

        evidence_lines = []
        if evidence.best_objective is not None:
            evidence_lines.append(f"Best objective value achieved: {evidence.best_objective}")
        if evidence.best_feasibility_distance is not None:
            evidence_lines.append(
                f"Best feasibility distance: {evidence.best_feasibility_distance}"
            )
        evidence_lines.append(f"Feasible candidates count: {evidence.feasible_count}")
        if evidence.constraint_overshoots:
            evidence_lines.append("Constraint overshoots:")
            for name, stats in evidence.constraint_overshoots.items():
                evidence_lines.append(
                    f"  - {name}: {stats.n_violating} violations, "
                    f"mean overshoot {stats.mean_overshoot:.4f}"
                )
        evidence_str = "\n".join(evidence_lines)

        if self.guide_llm is None:
            raise StrategyArchiveError("GuideLLM is required to attribute surprise.")

        if self.config.surprise_mode == "binary":
            observed_surprise = await binary_bayesian_surprise(
                summary_md,
                evidence_str,
                self.guide_llm,
                n=self.config.surprise_n_samples,
            )
        else:
            observed_surprise = await graded_bayesian_surprise(
                summary_md,
                evidence_str,
                self.guide_llm,
                n=self.config.surprise_n_samples,
            )

        new_surprise_ema = _update_ema(
            old_surprise_ema,
            observed_surprise,
            self.config.ema_alpha,
        )

        cursor.execute(
            """
            UPDATE strategies
               SET surprise_ema = ?,
                   visits = visits + 1
             WHERE sha = ?
            """,
            (new_surprise_ema, strategy_sha),
        )
        self.conn.commit()

        from factory.telemetry import api as telemetry

        telemetry.emit(
            "factory.strategy.attribute",
            {
                "strategy_sha": strategy_sha,
                "surprise_bits": observed_surprise,
                "reward_observed": None,
                "cycle_id": str(evidence.cycle_id),
                "polarity_gated": bool(observed_surprise == 0.0),
            },
        )

        return observed_surprise

    def attribute_reward(
        self,
        strategy_sha: str,
        evidence: StrategyCycleEvidence,
    ) -> float:
        """Compute performance reward from terminal cycle evidence, update reward EMAs."""
        logger.info(
            "attribute_reward(strategy_sha=%s, cycle_id=%s)", strategy_sha, evidence.cycle_id
        )

        cursor = self.conn.cursor()
        row = cursor.execute(
            "SELECT reward_ema, feasibility_distance_ema FROM strategies WHERE sha = ?",
            (strategy_sha,),
        ).fetchone()

        if row is None:
            raise StrategyArchiveError(f"Strategy {strategy_sha} not found in archive.")

        old_reward_ema, old_distance_ema = row

        observed_reward = _compute_reward(evidence)
        new_reward_ema = _update_ema(
            old_reward_ema,
            observed_reward,
            self.config.ema_alpha,
        )

        observed_distance = evidence.best_feasibility_distance
        if observed_distance is not None:
            new_distance_ema = _update_ema(
                old_distance_ema,
                float(observed_distance),
                self.config.ema_alpha,
            )
        else:
            new_distance_ema = old_distance_ema

        cursor.execute(
            """
            UPDATE strategies
               SET reward_ema = ?,
                   feasibility_distance_ema = ?,
                   feasible_count = feasible_count + ?
             WHERE sha = ?
            """,
            (new_reward_ema, new_distance_ema, evidence.feasible_count, strategy_sha),
        )
        self.conn.commit()

        from factory.telemetry import api as telemetry

        telemetry.emit(
            "factory.strategy.attribute",
            {
                "strategy_sha": strategy_sha,
                "surprise_bits": None,
                "reward_observed": observed_reward,
                "cycle_id": str(evidence.cycle_id),
                "polarity_gated": False,
            },
        )

        return observed_reward

    def select_lineages(self, k: int) -> list[str]:
        """Select parent strategy SHAs for parallel BFTS branches."""
        logger.info("select_lineages(k=%d)", k)
        from factory.strategy.selection import select_lineages

        selected = select_lineages(self, k)

        from factory.telemetry import api as telemetry

        telemetry.emit(
            "factory.strategy.select_lineages",
            {
                "k": k,
                "selected_shas": selected,
                "base_scores": {},
                "novelty_bonuses": {},
                "map_elites_bonuses": {},
            },
        )

        return selected

    def top_k(self, k: int) -> tuple[Strategy, ...]:
        """Return the top-K productive strategies for cycle program direction."""
        logger.info("top_k(k=%d)", k)

        cursor = self.conn.cursor()
        rows = cursor.execute(
            """
            SELECT sha, summary_md, kind, reward_ema, surprise_ema,
                   feasibility_distance_ema, feasible_count, visits,
                   behavior_descriptor_json, provenance
              FROM strategies
             WHERE experiment_id = ?
             ORDER BY reward_ema DESC, feasible_count DESC, sha ASC
             LIMIT ?
            """,
            (self.experiment_id, k),
        ).fetchall()

        results = []
        for row in rows:
            sha = row[0]
            summary_md = row[1]
            kind_str = row[2]
            reward_ema = row[3]
            surprise_ema = row[4]
            distance_ema = row[5]
            feasible_count = row[6]
            visits = row[7]
            bd_json = row[8]
            provenance = row[9]

            parents = _load_parents(self.conn, sha)
            bd = _load_behavior_descriptor(bd_json)

            strat = Strategy(
                artifact_type="strategy",
                created_at=datetime.now(UTC),
                provenance_hash=sha,
                parent_hashes=parents,
                sha=sha,
                summary_md=summary_md,
                kind=StrategyKind(kind_str),
                parent_shas=parents,
                reward_ema=reward_ema,
                surprise_ema=surprise_ema,
                feasibility_distance_ema=distance_ema,
                feasible_count=feasible_count,
                visits=visits,
                behavior_descriptor=bd,
                provenance=provenance,
            )
            results.append(strat)

        return tuple(results)

    def transfer_priors_from(
        self,
        source_problem_id: str,
        k: int,
    ) -> None:
        """Import top-K strategies from a sibling experiment."""
        logger.info("transfer_priors_from(source_problem_id=%s, k=%d)", source_problem_id, k)
        from factory.strategy.transfer import transfer_priors_from as _transfer

        _transfer(self.conn, self.experiment_id, source_problem_id, k)

    def set_behavior_descriptor(self, strategy_sha: str, descriptor: BehaviorDescriptor) -> None:
        """Store the BehaviorDescriptor coordinate and cell ID for a given strategy.

        Args:
            strategy_sha: The strategy's SHA-256 identifier.
            descriptor: The BehaviorDescriptor containing vector and cell_id.
        """
        logger.info(
            "set_behavior_descriptor(strategy_sha=%s, descriptor=%s)", strategy_sha, descriptor
        )
        cursor = self.conn.cursor()
        row = cursor.execute("SELECT sha FROM strategies WHERE sha = ?", (strategy_sha,)).fetchone()
        if row is None:
            raise StrategyArchiveError(f"Strategy {strategy_sha} not found in archive.")

        cursor.execute(
            "UPDATE strategies SET behavior_descriptor_json = ? WHERE sha = ?",
            (descriptor.model_dump_json(), strategy_sha),
        )
        self.conn.commit()

    def get_occupied_cells(self) -> set[str]:
        """Get occupied archive cell IDs for this experiment."""
        logger.info("get_occupied_cells() called")
        cursor = self.conn.cursor()
        rows = cursor.execute(
            """
            SELECT behavior_descriptor_json
            FROM strategies
            WHERE experiment_id = ? AND behavior_descriptor_json IS NOT NULL
            """,
            (self.experiment_id,),
        ).fetchall()

        occupied = set()
        for row in rows:
            bd = _load_behavior_descriptor(row[0])
            if bd.cell_id is not None:
                occupied.add(bd.cell_id)
        return occupied
