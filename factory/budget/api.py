# api.py — Budget Tracker Logic and Cap Enforcement
#
# This file implements the BudgetTracker cost governor, checking caps,
# recording spend, managing active reservations, and driving resets.
#
# Use cases:
# 1. Opening a hypothesis run and allocating its budget caps.
# 2. Reserving tokens and USD before executing LLM completion calls or simulations.
# 3. Recording actual spending after completion, updating totals.
# 4. Enforcing program-wide aggregate dollar caps via a hard stop sentinel.

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from factory.artifacts.api import (
    Budget,
    BudgetLedgerEntry,
    FactoryError,
    HypothesisId,
)
from factory.budget.types import (
    CostBreakdown,
    HypothesisCaps,
    RemainingBudget,
    Reservation,
    TimeWindowCaps,
)

logger = logging.getLogger("factory.budget.api")

# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------


class BudgetError(FactoryError):
    """Base exception for budget errors."""

    pass


class BudgetExhausted(BudgetError):
    """Per-hypothesis or per-day cap breached."""

    def __init__(
        self,
        tier: Literal["hypothesis", "day"],
        surface: Literal["dollars", "tokens", "wall_clock", "iterations"],
        requested: float,
        remaining: float,
    ) -> None:
        super().__init__(
            f"Budget exhausted at tier {tier} for {surface}: "
            f"requested {requested}, remaining {remaining}"
        )
        self.tier = tier
        self.surface = surface
        self.requested = requested
        self.remaining = remaining


class AggregateCapTriggered(BudgetError):
    """Program-wide hard halt triggered."""

    pass


class BudgetTokenUsageMissing(BudgetError):
    """Raised when an LLM response does not report token counts."""

    def __init__(self, module: str, model_id: str, description: str) -> None:
        super().__init__(f"Token usage missing from {model_id} call in {module}: {description}")
        self.module = module
        self.model_id = model_id
        self.description = description


class BudgetLedgerCorrupted(BudgetError):
    """Raised when ledger integrity checks fail."""

    pass


class ReservationExpired(BudgetError):
    """Raised when a reservation is no longer valid."""

    pass


# --------------------------------------------------------------------------
# Clock Helper
# --------------------------------------------------------------------------


class Clock:
    """Standard UTC Clock for lazy day resets."""

    def now(self) -> datetime:
        """Returns current datetime in UTC timezone."""
        return datetime.now(UTC)


# --------------------------------------------------------------------------
# BudgetTracker Class
# --------------------------------------------------------------------------


class BudgetTracker:
    """The central governor of budget limits and cost records."""

    def __init__(
        self,
        config_path: Path = Path("config/budget.yaml"),
        state_path: Path = Path("runs/_budget/state.json"),
        ledger_path: Path = Path("runs/_budget/ledger.jsonl"),
        clock: Clock | None = None,
        mock_mode: bool = False,
    ) -> None:
        logger.info("BudgetTracker.__init__")
        self._config_path = config_path
        self._state_path = state_path
        self._ledger_path = ledger_path
        self._clock = clock or Clock()
        self._mock_mode = mock_mode
        self._lock = threading.Lock()

        # Derive control directory relative to state_path to isolate tests
        self._control_dir = self._state_path.parent.parent / "_control"
        self._halt_sentinel = self._control_dir / "HALT_AGGREGATE_CAP"

        # Defaults in memory
        self._aggregate_dollar_cap = 500.0
        self._aggregate_used_dollars = 0.0
        self._program_halted = False

        # Daily caps
        self._day_cap_dollars = 100.0
        self._day_cap_tokens = 10_000_000
        self._day_cap_wall_clock = 86_400.0

        self._day_used_dollars = 0.0
        self._day_used_tokens = 0
        self._day_used_wall_clock = 0.0
        self._day_window_start = self._clock.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self._day_window_end = self._day_window_start + (
            self._clock.now() - self._clock.now()
        )  # placeholder timedelta placeholder

        # Default hypothesis cap configs
        self._default_hyp_dollars = 100.0
        self._default_hyp_tokens = 2_000_000
        self._default_hyp_wall_clock = 7_200.0
        self._default_hyp_iterations = 10

        # In-memory hypothesis tracking
        self._hypotheses_caps: dict[HypothesisId, HypothesisCaps] = {}
        self._hypotheses_used_dollars: dict[HypothesisId, float] = {}
        self._hypotheses_used_tokens: dict[HypothesisId, int] = {}
        self._hypotheses_used_wall_clock: dict[HypothesisId, float] = {}
        self._hypotheses_used_iterations: dict[HypothesisId, int] = {}

        # Active Reservations
        self._reservations: dict[str, Reservation] = {}

        self._load_config()
        self._load_state()

    def _load_config(self) -> None:
        """Loads configuration from YAML."""
        logger.info("_load_config() called")
        if not self._config_path.exists():
            return
        try:
            with open(self._config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            p = data.get("program", {})
            self._aggregate_dollar_cap = p.get("aggregate_dollar_cap", 500.0)

            d = data.get("day", {})
            self._day_cap_dollars = d.get("dollars", 100.0)
            self._day_cap_tokens = d.get("tokens", 10_000_000)
            self._day_cap_wall_clock = d.get("wall_clock_seconds", 86_400.0)

            dh = data.get("default_hypothesis", {})
            self._default_hyp_dollars = dh.get("dollars", 100.0)
            self._default_hyp_tokens = dh.get("tokens", 2_000_000)
            self._default_hyp_wall_clock = dh.get("wall_clock_seconds", 7200.0)
            self._default_hyp_iterations = dh.get("iterations", 10)
        except Exception as e:
            logger.error("Failed to load config: %s", e)

    def _load_state(self) -> None:
        """Loads tracker state and verifies ledger integrity."""
        logger.info("_load_state() called")
        if self._mock_mode:
            return

        # Check sentinel
        if self._halt_sentinel.exists():
            self._program_halted = True

        if self._state_path.exists():
            # Load state JSON
            try:
                with open(self._state_path, encoding="utf-8") as f:
                    state = json.load(f)

                self._program_halted = state.get("halted", False) or self._program_halted

                agg = state.get("aggregate", {})
                self._aggregate_used_dollars = agg.get("used", {}).get("dollars", 0.0)

                day_data = state.get("day", {})
                self._day_window_start = datetime.fromisoformat(day_data.get("window_start"))
                self._day_used_dollars = day_data.get("used", {}).get("dollars", 0.0)
                self._day_used_tokens = day_data.get("used", {}).get("tokens", 0)
                self._day_used_wall_clock = day_data.get("used", {}).get("wall_clock_seconds", 0.0)

                hyps = state.get("hypotheses", {})
                for h_id_str, h_data in hyps.items():
                    h_id = HypothesisId(h_id_str)
                    cap_data = h_data.get("cap", {})
                    self._hypotheses_caps[h_id] = HypothesisCaps(
                        dollars=cap_data.get("dollars", self._default_hyp_dollars),
                        tokens=cap_data.get("tokens", self._default_hyp_tokens),
                        wall_clock_seconds=cap_data.get(
                            "wall_clock_seconds", self._default_hyp_wall_clock
                        ),
                        iterations=cap_data.get("iterations", self._default_hyp_iterations),
                    )
                    used_data = h_data.get("used", {})
                    self._hypotheses_used_dollars[h_id] = used_data.get("dollars", 0.0)
                    self._hypotheses_used_tokens[h_id] = used_data.get("tokens", 0)
                    self._hypotheses_used_wall_clock[h_id] = used_data.get(
                        "wall_clock_seconds", 0.0
                    )
                    self._hypotheses_used_iterations[h_id] = used_data.get("iterations", 0)
            except Exception as e:
                logger.error("Error reading state file: %s", e)

        # Validate ledger
        if self._ledger_path.exists():
            try:
                with open(self._ledger_path, encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        entry_dict = json.loads(line)
                        declared = entry_dict.get("checksum")
                        computed = self._compute_checksum(entry_dict)
                        if declared != computed:
                            raise BudgetLedgerCorrupted(
                                f"Checksum mismatch in ledger line: {declared} != {computed}"
                            )
            except BudgetLedgerCorrupted:
                raise
            except Exception as e:
                logger.error("Error validating ledger: %s", e)

    def _compute_checksum(self, entry_dict: dict[str, Any]) -> str:
        """Computes SHA-256 checksum of a ledger entry dict."""
        payload = {k: v for k, v in entry_dict.items() if k != "checksum"}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _save_state(self) -> None:
        """Saves current state snapshot to state_path."""
        logger.info("_save_state() called")
        if self._mock_mode:
            return

        self._state_path.parent.mkdir(parents=True, exist_ok=True)

        hyps_dump = {}
        for h_id in self._hypotheses_caps:
            caps = self._hypotheses_caps[h_id]
            hyps_dump[str(h_id)] = {
                "cap": {
                    "dollars": caps.dollars,
                    "tokens": caps.tokens,
                    "wall_clock_seconds": caps.wall_clock_seconds,
                    "iterations": caps.iterations,
                },
                "used": {
                    "dollars": self._hypotheses_used_dollars.get(h_id, 0.0),
                    "tokens": self._hypotheses_used_tokens.get(h_id, 0),
                    "wall_clock_seconds": self._hypotheses_used_wall_clock.get(h_id, 0.0),
                    "iterations": self._hypotheses_used_iterations.get(h_id, 0),
                },
            }

        payload = {
            "schema_version": 1,
            "ts": self._clock.now().isoformat(),
            "halted": self._program_halted,
            "halt_reason": "aggregate_cap_reached" if self._program_halted else None,
            "aggregate": {
                "cap": {
                    "dollars": self._aggregate_dollar_cap,
                    "tokens": 0,
                    "wall_clock_seconds": 0,
                },
                "used": {
                    "dollars": self._aggregate_used_dollars,
                    "tokens": 0,
                    "wall_clock_seconds": 0,
                },
            },
            "day": {
                "window_start": self._day_window_start.isoformat(),
                "cap": {
                    "dollars": self._day_cap_dollars,
                    "tokens": self._day_cap_tokens,
                    "wall_clock_seconds": self._day_cap_wall_clock,
                },
                "used": {
                    "dollars": self._day_used_dollars,
                    "tokens": self._day_used_tokens,
                    "wall_clock_seconds": self._day_used_wall_clock,
                },
            },
            "hypotheses": hyps_dump,
        }

        # Atomic temp-rename write
        temp_path = self._state_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(temp_path, self._state_path)

    def _lazy_reset_day(self) -> None:
        """Resets the day totals if past UTC midnight."""
        now = self._clock.now()
        # Compute today's midnight
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now.date() != self._day_window_start.date():
            logger.info("Lazy reset of daily caps triggered.")
            self._day_window_start = today_midnight
            self._day_used_dollars = 0.0
            self._day_used_tokens = 0
            self._day_used_wall_clock = 0.0

    def open_hypothesis(
        self,
        hypothesis_id: HypothesisId,
        caps: HypothesisCaps | None = None,
    ) -> Budget:
        """Allocates budget caps for a new hypothesis."""
        logger.info("open_hypothesis(id=%s)", hypothesis_id)
        with self._lock:
            resolved_caps = caps or HypothesisCaps(
                dollars=self._default_hyp_dollars,
                tokens=self._default_hyp_tokens,
                wall_clock_seconds=self._default_hyp_wall_clock,
                iterations=self._default_hyp_iterations,
            )
            self._hypotheses_caps[hypothesis_id] = resolved_caps
            self._hypotheses_used_dollars[hypothesis_id] = 0.0
            self._hypotheses_used_tokens[hypothesis_id] = 0
            self._hypotheses_used_wall_clock[hypothesis_id] = 0.0
            self._hypotheses_used_iterations[hypothesis_id] = 0
            self._save_state()

            # Create core Budget Pydantic artifact

            # Compute a dummy provenance hash to satisfy model validation
            temp_b = Budget(
                artifact_type="Budget",
                created_at=self._clock.now(),
                provenance_hash="0" * 64,
                parent_hashes=(),
                hypothesis_id=hypothesis_id,
                dollar_cap=resolved_caps.dollars,
                wall_clock_cap_seconds=resolved_caps.wall_clock_seconds,
                token_cap=resolved_caps.tokens,
                iteration_cap=resolved_caps.iterations,
                running_ledger=(),
            )
            return temp_b.model_copy(update={"provenance_hash": temp_b.compute_hash()})

    def check_and_deduct(
        self,
        hypothesis_id: HypothesisId,
        module: str,
        estimated_cost_usd: float,
        estimated_tokens: int = 0,
        estimated_wall_clock_seconds: float = 0.0,
        estimated_iterations: int = 0,
        description: str = "",
    ) -> Reservation:
        """Verifies caps and creates a Reservation."""
        logger.info(
            "check_and_deduct(hypothesis_id=%s, estimated_cost_usd=%f, description=%s)",
            hypothesis_id,
            estimated_cost_usd,
            description,
        )
        with self._lock:
            self._lazy_reset_day()

            # 1. Check aggregate halt
            if self._program_halted or self._halt_sentinel.exists():
                raise AggregateCapTriggered("Program halted: aggregate cap sentinel active.")

            # 2. Check aggregate dollar cap
            if self._aggregate_used_dollars + estimated_cost_usd > self._aggregate_dollar_cap:
                self.halt_program("aggregate_cap_reached")
                raise AggregateCapTriggered("Breached aggregate dollar cap.")

            # 3. Check daily caps
            if self._day_used_dollars + estimated_cost_usd > self._day_cap_dollars:
                raise BudgetExhausted(
                    "day",
                    "dollars",
                    estimated_cost_usd,
                    self._day_cap_dollars - self._day_used_dollars,
                )
            if self._day_used_tokens + estimated_tokens > self._day_cap_tokens:
                raise BudgetExhausted(
                    "day", "tokens", estimated_tokens, self._day_cap_tokens - self._day_used_tokens
                )
            if self._day_used_wall_clock + estimated_wall_clock_seconds > self._day_cap_wall_clock:
                raise BudgetExhausted(
                    "day",
                    "wall_clock",
                    estimated_wall_clock_seconds,
                    self._day_cap_wall_clock - self._day_used_wall_clock,
                )

            # 4. Check hypothesis caps
            h_caps = self._hypotheses_caps.get(hypothesis_id)
            if h_caps:
                h_used_dollars = self._hypotheses_used_dollars.get(hypothesis_id, 0.0)
                h_used_tokens = self._hypotheses_used_tokens.get(hypothesis_id, 0)
                h_used_wall_clock = self._hypotheses_used_wall_clock.get(hypothesis_id, 0.0)
                h_used_iterations = self._hypotheses_used_iterations.get(hypothesis_id, 0)

                if h_used_dollars + estimated_cost_usd > h_caps.dollars:
                    raise BudgetExhausted(
                        "hypothesis", "dollars", estimated_cost_usd, h_caps.dollars - h_used_dollars
                    )
                if h_used_tokens + estimated_tokens > h_caps.tokens:
                    raise BudgetExhausted(
                        "hypothesis", "tokens", estimated_tokens, h_caps.tokens - h_used_tokens
                    )
                if h_used_wall_clock + estimated_wall_clock_seconds > h_caps.wall_clock_seconds:
                    raise BudgetExhausted(
                        "hypothesis",
                        "wall_clock",
                        estimated_wall_clock_seconds,
                        h_caps.wall_clock_seconds - h_used_wall_clock,
                    )
                if h_used_iterations + estimated_iterations > h_caps.iterations:
                    raise BudgetExhausted(
                        "hypothesis",
                        "iterations",
                        estimated_iterations,
                        h_caps.iterations - h_used_iterations,
                    )

            # Create Reservation
            res_id = str(uuid.uuid4())
            res = Reservation(
                reservation_id=res_id,
                hypothesis_id=hypothesis_id,
                module=module,
                estimated_cost_usd=estimated_cost_usd,
                estimated_tokens=estimated_tokens,
                estimated_wall_clock_seconds=estimated_wall_clock_seconds,
                estimated_iterations=estimated_iterations,
                expires_at=self._clock.now(),  # ignored simple TTL for Phase A tests
                tracker=self,
            )
            self._reservations[res_id] = res
            return res

    def _release_reservation(self, reservation_id: str) -> None:
        """Releases/cancels a reservation."""
        with self._lock:
            self._reservations.pop(reservation_id, None)

    def record(
        self,
        hypothesis_id: HypothesisId,
        module: str,
        cost_usd: float,
        tokens: int,
        wall_clock_seconds: float,
        description: str,
        reservation: Reservation | None = None,
    ) -> BudgetLedgerEntry:
        """Records actual spend and flushes to disk."""
        logger.info("record(hypothesis_id=%s, cost_usd=%f)", hypothesis_id, cost_usd)
        with self._lock:
            self._lazy_reset_day()

            # If reservation exists, release it
            if reservation:
                self._reservations.pop(reservation.reservation_id, None)

            # Update running totals
            self._aggregate_used_dollars += cost_usd
            self._day_used_dollars += cost_usd
            self._day_used_tokens += tokens
            self._day_used_wall_clock += wall_clock_seconds

            if hypothesis_id in self._hypotheses_caps:
                self._hypotheses_used_dollars[hypothesis_id] = (
                    self._hypotheses_used_dollars.get(hypothesis_id, 0.0) + cost_usd
                )
                self._hypotheses_used_tokens[hypothesis_id] = (
                    self._hypotheses_used_tokens.get(hypothesis_id, 0) + tokens
                )
                self._hypotheses_used_wall_clock[hypothesis_id] = (
                    self._hypotheses_used_wall_clock.get(hypothesis_id, 0.0) + wall_clock_seconds
                )

            # Trigger aggregate halt if exceeded
            if self._aggregate_used_dollars > self._aggregate_dollar_cap:
                self.halt_program("aggregate_cap_reached")

            # Persist ledger entry
            entry_dict = {
                "ledger_entry_id": str(uuid.uuid4()),
                "ts": self._clock.now().isoformat(),
                "hypothesis_id": str(hypothesis_id),
                "module": module,
                "cost_usd": cost_usd,
                "tokens": tokens,
                "wall_clock_seconds": wall_clock_seconds,
                "description": description,
            }
            entry_dict["checksum"] = self._compute_checksum(entry_dict)

            if not self._mock_mode:
                self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._ledger_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry_dict) + "\n")
                    f.flush()

                self._save_state()

            # Return a pydantic budget ledger entry
            temp_ble = BudgetLedgerEntry(
                ts=self._clock.now(),
                module=module,
                cost_usd=cost_usd,
                tokens=tokens,
                description=description,
            )
            return temp_ble

    def record_iteration(
        self,
        hypothesis_id: HypothesisId,
        module: str = "genver",
    ) -> None:
        """Increments the iteration counter for a hypothesis."""
        logger.info("record_iteration(hypothesis_id=%s, module=%s)", hypothesis_id, module)
        with self._lock:
            h_caps = self._hypotheses_caps.get(hypothesis_id)
            if h_caps:
                used = self._hypotheses_used_iterations.get(hypothesis_id, 0)
                if used + 1 > h_caps.iterations:
                    raise BudgetExhausted("hypothesis", "iterations", 1, h_caps.iterations - used)
                self._hypotheses_used_iterations[hypothesis_id] = used + 1
                self._save_state()

    def remaining(self, hypothesis_id: HypothesisId) -> RemainingBudget:
        """Returns the remaining budget space."""
        logger.info("remaining(hypothesis_id=%s)", hypothesis_id)
        with self._lock:
            self._lazy_reset_day()

            # Hypothesis remaining
            h_caps = self._hypotheses_caps.get(
                hypothesis_id,
                HypothesisCaps(
                    self._default_hyp_dollars,
                    self._default_hyp_tokens,
                    self._default_hyp_wall_clock,
                    self._default_hyp_iterations,
                ),
            )
            h_used_dollars = self._hypotheses_used_dollars.get(hypothesis_id, 0.0)
            h_used_tokens = self._hypotheses_used_tokens.get(hypothesis_id, 0)
            h_used_wall_clock = self._hypotheses_used_wall_clock.get(hypothesis_id, 0.0)
            h_used_iterations = self._hypotheses_used_iterations.get(hypothesis_id, 0)

            hyp_rem = HypothesisCaps(
                dollars=max(0.0, h_caps.dollars - h_used_dollars),
                tokens=max(0, h_caps.tokens - h_used_tokens),
                wall_clock_seconds=max(0.0, h_caps.wall_clock_seconds - h_used_wall_clock),
                iterations=max(0, h_caps.iterations - h_used_iterations),
            )

            # Day remaining
            day_rem = TimeWindowCaps(
                dollars=max(0.0, self._day_cap_dollars - self._day_used_dollars),
                tokens=max(0, self._day_cap_tokens - self._day_used_tokens),
                wall_clock_seconds=max(0.0, self._day_cap_wall_clock - self._day_used_wall_clock),
            )

            # Aggregate remaining
            agg_rem = TimeWindowCaps(
                dollars=max(0.0, self._aggregate_dollar_cap - self._aggregate_used_dollars),
                tokens=999999999,  # no aggregate tokens cap by default
                wall_clock_seconds=999999999,
            )

            return RemainingBudget(hypothesis=hyp_rem, day=day_rem, aggregate=agg_rem)

    def set_cap(
        self,
        *,
        aggregate_usd: float | None = None,
        daily_usd: float | None = None,
        per_hypothesis_usd: float | None = None,
        hypothesis_id: HypothesisId | None = None,
        clear_halt: bool = False,
    ) -> None:
        """Modifies caps and handles program resumption."""
        logger.info("set_cap")
        with self._lock:
            if aggregate_usd is not None:
                self._aggregate_dollar_cap = aggregate_usd
            if daily_usd is not None:
                self._day_cap_dollars = daily_usd
            if per_hypothesis_usd is not None:
                self._default_hyp_dollars = per_hypothesis_usd
                if hypothesis_id and hypothesis_id in self._hypotheses_caps:
                    c = self._hypotheses_caps[hypothesis_id]
                    self._hypotheses_caps[hypothesis_id] = HypothesisCaps(
                        dollars=per_hypothesis_usd,
                        tokens=c.tokens,
                        wall_clock_seconds=c.wall_clock_seconds,
                        iterations=c.iterations,
                    )

            if clear_halt:
                self._program_halted = False
                if self._halt_sentinel.exists():
                    try:
                        self._halt_sentinel.unlink()
                    except Exception as e:
                        logger.error("Failed to delete halt sentinel file: %s", e)
            self._save_state()

    def breakdown_by_module(
        self,
        window: tuple[datetime, datetime] | None = None,
    ) -> CostBreakdown:
        """Calculates a cost breakdown by module."""
        logger.info("breakdown_by_module")
        by_module: dict[str, float] = {}
        total = 0.0

        if not self._ledger_path.exists():
            return CostBreakdown(
                window=window or (datetime.min, datetime.max), by_module=by_module, total_usd=total
            )

        with open(self._ledger_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry["ts"])
                if window and not (window[0] <= ts <= window[1]):
                    continue
                mod = entry["module"]
                cost = entry["cost_usd"]
                by_module[mod] = by_module.get(mod, 0.0) + cost
                total += cost

        return CostBreakdown(
            window=window or (datetime.min, datetime.max),
            by_module=by_module,
            total_usd=total,
        )

    def close_hypothesis(
        self,
        hypothesis_id: HypothesisId,
        terminal_status: Literal["passed", "falsified", "intractable", "inconclusive"],
    ) -> Budget:
        """Closes a hypothesis and outputs the immutable Budget artifact."""
        logger.info("close_hypothesis(id=%s, terminal_status=%s)", hypothesis_id, terminal_status)
        with self._lock:
            self._save_state()
            h_caps = self._hypotheses_caps.get(
                hypothesis_id,
                HypothesisCaps(
                    self._default_hyp_dollars,
                    self._default_hyp_tokens,
                    self._default_hyp_wall_clock,
                    self._default_hyp_iterations,
                ),
            )

            # Read relevant ledger entries
            ledger_entries = []
            if self._ledger_path.exists():
                with open(self._ledger_path, encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        e = json.loads(line)
                        if e.get("hypothesis_id") == str(hypothesis_id):
                            ledger_entries.append(
                                BudgetLedgerEntry(
                                    ts=datetime.fromisoformat(e["ts"]),
                                    module=e["module"],
                                    cost_usd=e["cost_usd"],
                                    tokens=e["tokens"],
                                    description=e["description"],
                                )
                            )

            temp_b = Budget(
                artifact_type="Budget",
                created_at=self._clock.now(),
                provenance_hash="0" * 64,
                parent_hashes=(),
                hypothesis_id=hypothesis_id,
                dollar_cap=h_caps.dollars,
                wall_clock_cap_seconds=h_caps.wall_clock_seconds,
                token_cap=h_caps.tokens,
                iteration_cap=h_caps.iterations,
                running_ledger=tuple(ledger_entries),
            )
            return temp_b.model_copy(update={"provenance_hash": temp_b.compute_hash()})

    def halt_program(self, reason: str) -> None:
        """Sets the aggregate kill switch."""
        logger.info("halt_program(reason=%s)", reason)
        self._program_halted = True
        if not self._mock_mode:
            self._control_dir.mkdir(parents=True, exist_ok=True)
            with open(self._halt_sentinel, "w", encoding="utf-8") as f:
                f.write(f"HALTED: {reason} at {self._clock.now().isoformat()}\n")
