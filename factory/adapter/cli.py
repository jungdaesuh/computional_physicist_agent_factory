"""Command line interface for registered simulator adapters."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from factory.adapter.api import load, registered_ids
from factory.artifacts import ExperimentSpec, SimulatorId


def main(argv: list[str] | None = None) -> None:
    """Run adapter maintenance and mock execution commands."""
    parser = argparse.ArgumentParser(description="Adapter CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List registered simulator adapters")

    inspect_parser = subparsers.add_parser("inspect", help="Print an adapter output schema")
    inspect_parser.add_argument("simulator_id")
    inspect_parser.add_argument("--mock-mode", action="store_true")

    run_parser = subparsers.add_parser(
        "run",
        help="Run an adapter against an ExperimentSpec fixture",
    )
    run_parser.add_argument("--simulator-id", required=True)
    run_parser.add_argument("--experiment-fixture", default="typical")
    run_parser.add_argument(
        "--sandbox-dir",
        type=Path,
        default=Path("runs/adapter-cli/sandbox/000"),
    )
    run_parser.add_argument("--mock-mode", action="store_true")

    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "list":
        for simulator_id in registered_ids(mock_mode=False):
            print(simulator_id)
    elif args.command == "inspect":
        adapter = load(args.simulator_id, mock_mode=args.mock_mode)
        print(adapter.output_schema().model_dump_json(indent=2))
    elif args.command == "run":
        adapter = load(args.simulator_id, mock_mode=args.mock_mode)
        spec = _experiment_fixture(args.experiment_fixture, args.simulator_id)
        artifacts = adapter.run(spec, args.sandbox_dir)
        print(json.dumps(artifacts.model_dump(mode="json"), indent=2, sort_keys=True))


def _experiment_fixture(name: str, simulator_id: str) -> ExperimentSpec:
    fixture = ExperimentSpec.from_fixture(name)
    return fixture.model_copy(update={"simulator_id": SimulatorId(simulator_id)})


if __name__ == "__main__":
    main()
