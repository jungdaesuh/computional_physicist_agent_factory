"""Evidence ledger command line interface."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from factory.ledger.api import Ledger

logger = logging.getLogger("factory.ledger.cli")


def _check_strategy_surprise(args: argparse.Namespace) -> None:
    db_path = Path(args.db) if args.db is not None else None
    if db_path is None:
        ledger = Ledger(mock_mode=True, verify_on_read=False)
    else:
        ledger = Ledger(db_path=db_path, verify_on_read=False)
    with ledger:
        rows = ledger.top_high_surprise_with_dependents(k=args.limit)
        print(
            json.dumps(
                {
                    "check": "strategy-surprise",
                    "status": "ok",
                    "row_count": len(rows),
                },
                sort_keys=True,
            )
        )


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point for the ledger module."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
    logger.info("main() called with args=%s", raw_args)
    parser = argparse.ArgumentParser(description="Ledger CLI")
    parser.add_argument("--mock-mode", action="store_true", help="Run in mock mode")
    subparsers = parser.add_subparsers(dest="command")

    queries_parser = subparsers.add_parser("queries", help="Run audit query checks")
    query_subparsers = queries_parser.add_subparsers(dest="query")
    surprise_parser = query_subparsers.add_parser(
        "check-strategy-surprise",
        help="Verify the strategy-surprise audit query can execute",
    )
    surprise_parser.add_argument("--db", help="Ledger SQLite database path")
    surprise_parser.add_argument("--limit", type=int, default=20, help="Maximum rows to read")

    args = parser.parse_args(raw_args)

    if args.command == "queries" and args.query == "check-strategy-surprise":
        _check_strategy_surprise(args)
        return
    if args.command is not None:
        parser.error(f"unsupported command: {args.command}")

    if args.mock_mode:
        print("Running ledger in mock mode.")
    else:
        print("Running ledger in live mode.")


if __name__ == "__main__":
    main()
