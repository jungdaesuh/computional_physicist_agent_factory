# cli.py — Command Line Interface for telemetry
#
# Exposes subcommands for internal debugging, querying, tailing, and metrics aggregation.
#
# Use cases:
# 1. Emitting test events manually with `telemetry emit`.
# 2. Exporting cycle logs: telemetry export --cycle cycle-default
# 3. Tailing logs in real-time: telemetry tail --cycle cycle-default
# 4. Running metrics aggregator: telemetry aggregate

import argparse
import json
import logging
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from factory.artifacts.api import HypothesisId
from factory.telemetry.api import (
    Aggregator,
    AuditQuery,
    EventRegistry,
    TelemetryEmitter,
)

logger = logging.getLogger("factory.telemetry.cli")


def main(argv: Sequence[str] = sys.argv[1:]) -> None:
    """CLI entry point for the telemetry module."""
    logger.info("main() called with args=%s", argv)

    parser = argparse.ArgumentParser(description="Telemetry CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # emit subcommand
    emit_parser = subparsers.add_parser("emit", help="Emit a telemetry event")
    emit_parser.add_argument("--event", required=True, help="Dotted event name")
    emit_parser.add_argument("--payload", default="{}", help="JSON payload string")
    emit_parser.add_argument(
        "--level", default="info", choices=["debug", "info", "warn", "error"], help="Severity level"
    )
    emit_parser.add_argument("--cycle-id", default="cycle-default", help="Cycle ID")
    emit_parser.add_argument("--runs-dir", default="runs", help="Runs directory")

    # export subcommand
    export_parser = subparsers.add_parser("export", help="Export events from a cycle log")
    export_parser.add_argument("--cycle", required=True, help="Cycle ID")
    export_parser.add_argument("--runs-dir", default="runs", help="Runs directory")

    # query subcommand
    query_parser = subparsers.add_parser("query", help="Query events from audit trail")
    query_group = query_parser.add_mutually_exclusive_group(required=True)
    query_group.add_argument("--hypothesis", help="Query by hypothesis ID")
    query_group.add_argument("--event", help="Query by event name")
    query_parser.add_argument("--since", help="Start timestamp filter")
    query_parser.add_argument("--until", help="End timestamp filter")
    query_parser.add_argument("--runs-dir", default="runs", help="Runs directory")
    query_parser.add_argument(
        "--ledger-db", default="runs/ledger.db", help="Ledger SQLite database path"
    )

    # tail subcommand
    tail_parser = subparsers.add_parser("tail", help="Tail a cycle log in real-time")
    tail_parser.add_argument("--cycle", required=True, help="Cycle ID")
    tail_parser.add_argument("--mock-mode", action="store_true", help="Run tail in mock mode")
    tail_parser.add_argument("--runs-dir", default="runs", help="Runs directory")

    # aggregate subcommand
    subparsers.add_parser("aggregate", help="Run metrics aggregator process")

    args = parser.parse_args(argv)

    if args.command == "emit":
        try:
            payload_dict = json.loads(args.payload)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON payload: {e}")
            sys.exit(1)

        registry = EventRegistry.build()
        cycle_path = Path(args.runs_dir) / args.cycle_id
        emitter = TelemetryEmitter(cycle_path, registry, cycle_id=args.cycle_id)
        try:
            emitter.emit(args.event, payload_dict, level=args.level)
            print(f"Emitted: {args.event}")
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)

    elif args.command == "export":
        query = AuditQuery(runs_dir=args.runs_dir)
        for record in query.by_cycle(args.cycle):
            print(json.dumps(record))

    elif args.command == "query":
        query = AuditQuery(runs_dir=args.runs_dir, ledger_db_path=args.ledger_db)
        if args.hypothesis:
            records = query.by_hypothesis(HypothesisId(args.hypothesis))
        else:
            records = query.by_event_name(args.event, since=args.since, until=args.until)

        for record in records:
            print(json.dumps(record))

    elif args.command == "tail":
        log_file = Path(args.runs_dir) / args.cycle / "cycle.jsonl"
        print(f"Tailing {log_file}...")

        if args.mock_mode:
            print("Mock mode: tailing dummy log stream")
            for i in range(5):
                print(
                    json.dumps(
                        {"ts": "2026-05-23T00:00:00Z", "event": "mock.event", "payload": {"idx": i}}
                    )
                )
                time.sleep(0.5)
            return

        if not log_file.exists():
            print(f"Waiting for log file to be created at {log_file}...")
            while not log_file.exists():
                time.sleep(0.5)

        # Tail implementation
        with open(log_file, encoding="utf-8") as f:
            # Go to end of file
            f.seek(0, 2)
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                print(line.strip())

    elif args.command == "aggregate":
        print("Starting metrics aggregator...")
        agg = Aggregator()
        try:
            # Run once to process existing logs, or continuously
            agg.run(once=True)
            snap = agg.snapshot()
            print("Aggregation complete. Snapshot:")
            print(f"  Sycophancy rate: {snap.sycophancy_rate:.4f}")
            print(f"  OOD escalation rate: {snap.ood_escalation_rate:.4f}")
            print(f"  Dollar burn by module: {snap.dollar_burn_by_module}")
        except KeyboardInterrupt:
            print("Aggregator stopped.")


if __name__ == "__main__":
    main()
