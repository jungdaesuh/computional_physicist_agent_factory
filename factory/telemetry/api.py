# api.py — Telemetry module interface
#
# This file implements the structured event logging system (telemetry) for the factory.
# All modules emit events here, which are validated against event namespaces and schemas
# registered in each module's events.py.
#
# Use cases:
# 1. Logging structured cycle events to runs/<cycle_id>/cycle.jsonl.
# 2. Emitting events using module-global entry point (emit).
# 3. Querying audit trails across cycles and hypotheses.
# 4. Running program-level metrics aggregation.

from __future__ import annotations

import datetime
import fcntl
import importlib
import json
import logging
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from factory.artifacts.api import HypothesisId
from factory.telemetry.aggregator import (
    ModuleCostRow,
    TelemetryAggregateSnapshot,
    aggregate_jsonl_events,
)
from factory.telemetry.errors import (
    EventTaxonomyViolation,
    JSONLineCorrupted,
    LogFileLocked,
    TelemetryError,
)

logger = logging.getLogger("factory.telemetry.api")

EventLevel = Literal["debug", "info", "warn", "error"]

# Closed set of MODULE NAMESPACES (the only closed dimension of the taxonomy).
# Event names are extensible per-namespace via each module's events.py.
KNOWN_NAMESPACES: frozenset[str] = frozenset(
    {
        "factory.council",
        "factory.catalog",
        "factory.selector",
        "factory.adapter",
        "factory.literature",
        "factory.genver",
        "factory.validation",
        "factory.surrogate",
        "factory.writer",
        "factory.ledger",
        "factory.budget",
        "factory.telemetry",
        "factory.operator",
        "factory.state_machine",
        "factory.artifacts",
        "factory.strategy",
    }
)


class EventRegistry:
    """In-memory registry of {namespace -> frozenset[event_name]}.

    Built once at telemetry startup by importing each module in KNOWN_NAMESPACES
    and reading its events.py REGISTERED_EVENTS constant.
    Immutable after build(); emit() does an O(1) lookup against it.
    """

    def __init__(
        self,
        registered_events: frozenset[str],
        namespaces: frozenset[str],
        payload_schemas: dict[str, type[BaseModel]],
    ) -> None:
        """Initializes the EventRegistry.

        Args:
            registered_events: FQNs of all registered events.
            namespaces: FQNs of all namespaces.
            payload_schemas: FQNs mapped to validation model classes.
        """
        self._registered_events = registered_events
        self._namespaces = namespaces
        self._payload_schemas = payload_schemas

    @classmethod
    def build(cls, known: frozenset[str] = KNOWN_NAMESPACES) -> EventRegistry:
        """Dynamically imports and aggregates event definitions from all modules.

        Returns:
            The assembled EventRegistry instance.
        """
        logger.info("EventRegistry.build called with known namespaces: %s", known)
        registered_events: set[str] = set()
        payload_schemas: dict[str, type[BaseModel]] = {}

        for ns in known:
            if not ns.startswith("factory."):
                raise ImportError(f"Namespace {ns} must start with 'factory.'")
            suffix = ns[8:]  # e.g., "council"
            module_name = f"factory.{suffix}.events"
            try:
                ev_mod = importlib.import_module(module_name)
            except ImportError as e:
                logger.error("Failed to import events module %s: %s", module_name, e)
                raise

            # Verify namespace match
            ns_val = getattr(ev_mod, "NAMESPACE", None)
            if ns_val != ns:
                raise ImportError(
                    f"Module {module_name} does not define NAMESPACE = '{ns}' (got '{ns_val}')"
                )

            # Collect REGISTERED_EVENTS
            events_tuple = getattr(ev_mod, "REGISTERED_EVENTS", None)
            if not isinstance(events_tuple, tuple):
                raise ImportError(
                    f"Module {module_name} must define REGISTERED_EVENTS as a tuple of strings"
                )

            for ev_suffix in events_tuple:
                fqn = f"{ns}.{ev_suffix}"
                registered_events.add(fqn)

            # Collect PAYLOAD_SCHEMAS if any
            schemas_dict = getattr(ev_mod, "PAYLOAD_SCHEMAS", {})
            if isinstance(schemas_dict, dict):
                for ev_suffix, schema_type in schemas_dict.items():
                    fqn = f"{ns}.{ev_suffix}"
                    payload_schemas[fqn] = schema_type

        return cls(
            registered_events=frozenset(registered_events),
            namespaces=frozenset(known),
            payload_schemas=payload_schemas,
        )

    def contains(self, event_name: str) -> bool:
        """Checks if a fully qualified event name is registered."""
        return event_name in self._registered_events

    def namespaces(self) -> frozenset[str]:
        """Returns the registered namespaces."""
        return self._namespaces

    def events_for(self, namespace: str) -> frozenset[str]:
        """Returns all registered events for a given namespace."""
        return frozenset(ev for ev in self._registered_events if ev.startswith(f"{namespace}."))


class TelemetryEmitter:
    """Per-cycle event writer. One emitter per cycle, owned by the state machine."""

    def __init__(
        self,
        cycle_dir: Path | str,
        registry: EventRegistry,
        mock_mode: bool = False,
        flush_every_n: int = 1,
        cycle_id: str | None = None,
    ) -> None:
        """Initializes the TelemetryEmitter.

        Args:
            cycle_dir: Output log directory.
            registry: Configured event registry.
            mock_mode: True to bypass filesystem operations in memory.
            flush_every_n: Write count between fsync calls.
            cycle_id: Identifier of the cycle (defaults to cycle_dir name).
        """
        logger.info("TelemetryEmitter.__init__(cycle_dir=%s, mock_mode=%s)", cycle_dir, mock_mode)
        self.cycle_dir = Path(cycle_dir)
        self._registry = registry
        self.mock_mode = mock_mode
        self.flush_every_n = flush_every_n
        self.cycle_id = cycle_id or self.cycle_dir.name
        self._log_file = self.cycle_dir / "cycle.jsonl"
        self._is_closed = False
        self._write_count = 0

        if not self.mock_mode:
            self.cycle_dir.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, payload: dict[str, Any], level: EventLevel = "info") -> None:
        """Emits an event to the cycle log file.

        Args:
            event: Dotted event name (e.g. factory.council.deliberation_complete)
            payload: Payload dictionary.
            level: Severity level.
        """
        if self._is_closed:
            raise TelemetryError("Emitter is closed.")

        if "." not in event:
            raise EventTaxonomyViolation(f"Event name must be dotted, got: {event}")

        namespace, suffix = event.rsplit(".", 1)

        # 1. Namespace check
        if namespace not in KNOWN_NAMESPACES:
            raise EventTaxonomyViolation(f"unknown namespace: {namespace}")

        # 2. Event suffix check
        if not self._registry.contains(event):
            raise EventTaxonomyViolation(f"unregistered event in known namespace: {event}")

        # 3. Payload validation check if schema exists
        schema = self._registry._payload_schemas.get(event)
        if schema is not None:
            try:
                schema.model_validate(payload)
            except ValidationError as e:
                raise EventTaxonomyViolation(
                    f"payload schema mismatch: {event}. Details: {e}"
                ) from e

        # Construct log record
        record = {
            "ts": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
            "cycle_id": self.cycle_id,
            "module": namespace,
            "level": level,
            "event": event,
            "payload": payload,
        }

        logger.info("Telemetry event emitted: %s", record)

        if not self.mock_mode:
            self._append_record(record)

    def _append_record(self, record: dict[str, Any]) -> None:
        """Locks the log file and appends the serialized record."""
        log_line = json.dumps(record) + "\n"
        start_time = time.time()
        timeout = 5.0

        try:
            f = self._log_file.open("a", encoding="utf-8")
        except OSError as e:
            raise TelemetryError(f"Failed to open log file {self._log_file}: {e}") from e

        try:
            locked = False
            while not locked:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except OSError as e:
                    if time.time() - start_time > timeout:
                        raise LogFileLocked(
                            f"Could not acquire exclusive write lock on {self._log_file} "
                            f"within {timeout}s"
                        ) from e
                    time.sleep(0.05)

            f.write(log_line)
            self._write_count += 1

            if self.flush_every_n == 1 or self._write_count % self.flush_every_n == 0:
                f.flush()
                with suppress(OSError):
                    os.fsync(f.fileno())
        finally:
            with suppress(Exception):
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            f.close()

    def close(self) -> None:
        """Closes the emitter."""
        self._is_closed = True


# --------------------------------------------------------------------------
# Global Emitter Context Context managers
# --------------------------------------------------------------------------

_active_emitter: TelemetryEmitter | None = None


def set_active_emitter(emitter: TelemetryEmitter | None) -> None:
    """Sets the thread-global active emitter context."""
    global _active_emitter
    _active_emitter = emitter


def emit(event: str, payload: dict[str, Any], *, level: EventLevel = "info") -> None:
    """Module-global convenience entry point.

    Soft-dependency contract: no-op if no active emitter or if FACTORY_TELEMETRY_DISABLED=1.
    """
    if os.environ.get("FACTORY_TELEMETRY_DISABLED") == "1":
        return
    if _active_emitter is None:
        logger.debug("No active telemetry emitter configured. Event '%s' dropped.", event)
        return
    try:
        _active_emitter.emit(event, payload, level=level)
    except Exception as e:
        logger.error("Telemetry emitter failed to log event '%s': %s", event, e)


# --------------------------------------------------------------------------
# Audit and Aggregation
# --------------------------------------------------------------------------


class AuditQuery:
    """Query interface over per-cycle logs + EvidenceLedger index."""

    def __init__(
        self, runs_dir: Path | str = "runs", ledger_db_path: Path | str = "runs/ledger.db"
    ) -> None:
        """Initializes the AuditQuery helper.

        Args:
            runs_dir: Runs root folder containing cycle-id/cycle.jsonl.
            ledger_db_path: SQLite DB path.
        """
        self.runs_dir = Path(runs_dir)
        self.ledger_db_path = Path(ledger_db_path)

    def by_cycle(self, cycle_id: str) -> Iterator[dict[str, Any]]:
        """Yields all valid events recorded within a specific cycle log."""
        log_file = self.runs_dir / cycle_id / "cycle.jsonl"
        if not log_file.exists():
            return

        with open(log_file, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    for k in ("ts", "cycle_id", "module", "level", "event", "payload"):
                        if k not in record:
                            raise JSONLineCorrupted(f"Missing field '{k}' in record")
                    yield record
                except (json.JSONDecodeError, JSONLineCorrupted) as e:
                    logger.warning("Corrupt JSONL line detected in cycle %s: %s", cycle_id, e)
                    # Side-log corruption write
                    side_log = self.runs_dir / cycle_id / "corrupt.jsonl"
                    try:
                        side_log.parent.mkdir(parents=True, exist_ok=True)
                        with open(side_log, "a", encoding="utf-8") as sf:
                            sf.write(
                                json.dumps(
                                    {
                                        "ts": datetime.datetime.now(datetime.UTC)
                                        .isoformat()
                                        .replace("+00:00", "Z"),
                                        "error": str(e),
                                        "raw_line": line,
                                    }
                                )
                                + "\n"
                            )
                    except Exception as le:
                        logger.error("Failed to write to side log: %s", le)

    def by_hypothesis(self, hypothesis_id: HypothesisId) -> Iterator[dict[str, Any]]:
        """Resolves cycle IDs via SQLite EvidenceLedger and returns log events."""
        if not self.ledger_db_path.exists():
            logger.warning("Ledger DB not found. Cannot query by hypothesis.")
            return

        cycle_ids: list[str] = []
        try:
            conn = sqlite3.connect(self.ledger_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT cycle_id FROM entries WHERE hypothesis_id = ?", (hypothesis_id,)
            )
            cycle_ids = [row["cycle_id"] for row in cursor.fetchall()]
            conn.close()
        except Exception as e:
            logger.error("Failed to query cycle IDs from Ledger DB: %s", e)

        for cid in sorted(cycle_ids):
            yield from self.by_cycle(cid)

    def by_event_name(
        self, event_name: str, since: str | None = None, until: str | None = None
    ) -> Iterator[dict[str, Any]]:
        """Queries events matching the given name and optional timestamps across cycles."""
        if not self.runs_dir.exists():
            return

        for p in sorted(self.runs_dir.iterdir()):
            if p.is_dir() and (p / "cycle.jsonl").exists():
                for record in self.by_cycle(p.name):
                    if record.get("event") == event_name:
                        ts = record.get("ts", "")
                        if since and ts < since:
                            continue
                        if until and ts > until:
                            continue
                        yield record


class AggregatorReport:
    """Rolled up metrics report."""

    def __init__(
        self,
        sycophancy_rate: float,
        ood_escalation_rate: float,
        dollar_burn_by_module: dict[str, float],
    ) -> None:
        """Initializes the AggregatorReport."""
        self.sycophancy_rate = sycophancy_rate
        self.ood_escalation_rate = ood_escalation_rate
        self.dollar_burn_by_module = dollar_burn_by_module


class Aggregator:
    """Optional process that tails per-cycle logs and computes program-level metrics."""

    def __init__(self, runs_dir: Path | str = "runs") -> None:
        """Initializes the Aggregator."""
        self.runs_dir = Path(runs_dir)
        self._state_file = self.runs_dir / "_aggregator" / "state.json"
        self._metrics_file = self.runs_dir / "_aggregator" / "metrics.jsonl"
        self._offsets: dict[str, int] = {}
        self._sycophancy_detected = 0
        self._deliberations_completed = 0
        self._ood_escalations = 0
        self._surrogates_evaluated = 0
        self._dollar_burn: dict[str, float] = {}

        self._load_state()

    def _load_state(self) -> None:
        if self._state_file.exists():
            try:
                with open(self._state_file) as f:
                    data = json.load(f)
                    self._offsets = data.get("offsets", {})
                    self._sycophancy_detected = data.get("sycophancy_detected", 0)
                    self._deliberations_completed = data.get("deliberations_completed", 0)
                    self._ood_escalations = data.get("ood_escalations", 0)
                    self._surrogates_evaluated = data.get("surrogates_evaluated", 0)
                    self._dollar_burn = data.get("dollar_burn", {})
            except Exception as e:
                logger.warning("Failed to load aggregator state: %s", e)

    def _save_state(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._state_file, "w") as f:
                json.dump(
                    {
                        "offsets": self._offsets,
                        "sycophancy_detected": self._sycophancy_detected,
                        "deliberations_completed": self._deliberations_completed,
                        "ood_escalations": self._ood_escalations,
                        "surrogates_evaluated": self._surrogates_evaluated,
                        "dollar_burn": self._dollar_burn,
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.error("Failed to save aggregator state: %s", e)

    def run(self, once: bool = False) -> None:
        """Tails per-cycle logs and processes new events."""
        logger.info("Aggregator.run(once=%s)", once)
        while True:
            if self.runs_dir.exists():
                for p in sorted(self.runs_dir.iterdir()):
                    if p.is_dir() and not p.name.startswith("_") and (p / "cycle.jsonl").exists():
                        self._process_cycle_log(p.name)
            self._save_state()
            self._write_metrics()

            if once:
                break
            time.sleep(5.0)

    def _process_cycle_log(self, cycle_id: str) -> None:
        log_file = self.runs_dir / cycle_id / "cycle.jsonl"
        offset = self._offsets.get(cycle_id, 0)

        try:
            file_size = log_file.stat().st_size
            if file_size < offset:
                offset = 0
            elif file_size == offset:
                return

            with open(log_file, encoding="utf-8") as f:
                f.seek(offset)
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        self._process_event(record)
                    except json.JSONDecodeError:
                        pass
                self._offsets[cycle_id] = f.tell()
        except Exception as e:
            logger.error("Failed to process cycle log %s: %s", cycle_id, e)

    def _process_event(self, event_record: dict[str, Any]) -> None:
        event = event_record.get("event")
        module = event_record.get("module")
        payload = event_record.get("payload", {})

        if event == "factory.council.sycophancy_detected":
            self._sycophancy_detected += 1
        elif event == "factory.council.deliberation_complete":
            self._deliberations_completed += 1
        elif event == "factory.surrogate.ood_escalation":
            self._ood_escalations += 1
        elif event == "factory.surrogate.evaluated":
            self._surrogates_evaluated += 1

        cost = payload.get("cost_usd") or payload.get("total_cost_usd")
        if cost is not None and module:
            with suppress(ValueError):
                self._dollar_burn[module] = self._dollar_burn.get(module, 0.0) + float(cost)

    def snapshot(self) -> AggregatorReport:
        """Returns the current metrics snapshot."""
        sycophancy_rate = 0.0
        if self._deliberations_completed > 0:
            sycophancy_rate = self._sycophancy_detected / self._deliberations_completed

        ood_escalation_rate = 0.0
        if self._surrogates_evaluated > 0:
            ood_escalation_rate = self._ood_escalations / self._surrogates_evaluated

        return AggregatorReport(
            sycophancy_rate=sycophancy_rate,
            ood_escalation_rate=ood_escalation_rate,
            dollar_burn_by_module=self._dollar_burn.copy(),
        )

    def _write_metrics(self) -> None:
        snap = self.snapshot()
        self._metrics_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._metrics_file, "a", encoding="utf-8") as f:
                record = {
                    "ts": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
                    "sycophancy_rate": snap.sycophancy_rate,
                    "ood_escalation_rate": snap.ood_escalation_rate,
                    "dollar_burn_by_module": snap.dollar_burn_by_module,
                }
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.error("Failed to write metrics output: %s", e)


__all__ = [
    "AuditQuery",
    "Aggregator",
    "AggregatorReport",
    "EventLevel",
    "EventRegistry",
    "KNOWN_NAMESPACES",
    "ModuleCostRow",
    "TelemetryAggregateSnapshot",
    "TelemetryEmitter",
    "aggregate_jsonl_events",
    "emit",
    "set_active_emitter",
]
