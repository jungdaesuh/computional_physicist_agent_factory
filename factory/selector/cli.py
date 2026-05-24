# cli.py — Command Line Interface for selector
#
# Exposes subcommands for deterministic simulator selection, ranking explanation,
# and compatibility listing.
#
# Use cases:
# 1. Running selection on a hypothesis spec:
#    python -m factory.selector select --hypothesis-fixture typical \
#      --catalog-fixture phase_a --mock-mode
# 2. Explaining candidate selection rationale:
#    python -m factory.selector explain \
#      --trace-path runs/default_cycle/artifacts/xxxx.trace.json \
#      --candidate-id mock_solver_a
# 3. Listing compatible simulators for an observable:
#    python -m factory.selector list-compatible \
#      --hypothesis-fixture typical --catalog-fixture phase_a --mock-mode

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from factory.artifacts import HypothesisSpec
from factory.catalog import Catalog, EntryStatus
from factory.selector.api import Selector, TelemetryStub

logger = logging.getLogger("factory.selector.cli")


def main(argv: Sequence[str] = sys.argv[1:]) -> None:
    """CLI entry point for the selector module."""
    logger.info("main() called with args=%s", argv)
    parser = argparse.ArgumentParser(description="Selector CLI")

    # Global options
    parser.add_argument(
        "--registry-path",
        default="runs/catalog/registry.sqlite",
        help="Path to registry database",
    )
    parser.add_argument(
        "--manifest-root",
        default="runs/catalog/manifests",
        help="Root directory holding manifests",
    )
    parser.add_argument(
        "--license-db",
        default="factory/catalog/data",
        help="Directory containing OSI and carveout files",
    )
    parser.add_argument(
        "--weights-path",
        default="config/selector/weights.yaml",
        help="Path to selector weights configuration",
    )
    parser.add_argument(
        "--mock-mode", action="store_true", help="Force mock mode with mock builders"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # select subcommand
    select_parser = subparsers.add_parser(
        "select",
        help="Deterministically select the best simulator for a hypothesis",
    )
    # Supports both custom path and fixtures
    select_parser.add_argument("--hypothesis-path", help="Path to HypothesisSpec JSON file")
    select_parser.add_argument(
        "--hypothesis-fixture",
        default="typical",
        help="Fixture name of HypothesisSpec (e.g. typical, edge)",
    )
    select_parser.add_argument(
        "--catalog-fixture",
        default="phase_a",
        help="Fixture name of Catalog (e.g. phase_a)",
    )
    select_parser.add_argument("--budget-cap", type=float, help="Optional budget dollar cap")

    # explain subcommand
    explain_parser = subparsers.add_parser(
        "explain",
        help="Show scoring breakdown and explanation for a candidate",
    )
    explain_parser.add_argument(
        "--trace-path", required=True, help="Path to selection trace JSON file"
    )
    explain_parser.add_argument("--candidate-id", required=True, help="Simulator ID to explain")

    # list-compatible subcommand
    list_parser = subparsers.add_parser(
        "list-compatible",
        help="List all compatible simulators for a hypothesis metric",
    )
    list_parser.add_argument("--hypothesis-path", help="Path to HypothesisSpec JSON file")
    list_parser.add_argument(
        "--hypothesis-fixture",
        default="typical",
        help="Fixture name of HypothesisSpec",
    )
    list_parser.add_argument(
        "--catalog-fixture",
        default="phase_a",
        help="Fixture name of Catalog",
    )

    args = parser.parse_args(argv)

    # 1. Initialize Catalog
    if args.mock_mode or args.command in ["select", "list-compatible"]:
        # If fixture is requested, or in mock-mode, retrieve Catalog from fixture
        catalog_fixture = getattr(args, "catalog_fixture", "phase_a")
        # Map generic fixture name 'phase_a' or custom ones
        try:
            catalog = Catalog.from_fixture(catalog_fixture)
        except Exception:
            # Fallback to local init if fixture not found
            catalog = Catalog(
                registry_path=Path(args.registry_path),
                manifest_root=Path(args.manifest_root),
                license_db_path=Path(args.license_db),
                mock_mode=True,
            )
    else:
        catalog = Catalog(
            registry_path=Path(args.registry_path),
            manifest_root=Path(args.manifest_root),
            license_db_path=Path(args.license_db),
            mock_mode=False,
        )

    # 2. Execute Command
    try:
        if args.command == "select":
            # Load hypothesis spec
            if args.hypothesis_path:
                with open(args.hypothesis_path, encoding="utf-8") as f:
                    hyp = HypothesisSpec.model_validate_json(f.read())
            else:
                fixture_name = args.hypothesis_fixture
                if fixture_name == "sample":
                    fixture_name = "typical"
                hyp_fixture = HypothesisSpec.from_fixture(fixture_name)
                assert isinstance(hyp_fixture, HypothesisSpec)
                hyp = hyp_fixture

            selector = Selector(
                catalog=catalog,
                telemetry=TelemetryStub.no_history(),
                weights_path=Path(args.weights_path),
                mock_mode=args.mock_mode or (args.catalog_fixture is not None),
            )

            result = selector.select(
                hypothesis_spec=hyp,
                budget_dollar_cap=args.budget_cap,
            )

            print(f"Selection run for hypothesis: {result.hypothesis_id}")
            print(f"Catalog version hash: {result.catalog_version_hash}")
            print(f"Failure mode: {result.failure_mode}")
            print(f"Ambiguous: {result.ambiguous}")
            print(f"Trace saved to: {result.trace_path}")
            print("\nRanked Candidates:")
            for idx, cand in enumerate(result.candidates, 1):
                over_budget_str = " (OVER BUDGET)" if cand.over_budget else ""
                print(f"  {idx}. {cand.simulator_id} (Score: {cand.score:.4f}){over_budget_str}")
                print(
                    f"     Cost: {cand.cost.expected_cost_usd:.4f} USD, "
                    f"Freshness: {cand.maintenance_freshness:.4f}"
                )
                print(f"     Partners: {cand.cross_simulator_partners}")

        elif args.command == "explain":
            trace_file = Path(args.trace_path)
            if not trace_file.exists():
                print(f"Error: Trace file not found at {trace_file}")
                sys.exit(1)
            with open(trace_file, encoding="utf-8") as f:
                trace_data = json.load(f)

            candidates = trace_data.get("candidates_scored", [])
            matched = None
            for c in candidates:
                if c.get("simulator_id") == args.candidate_id:
                    matched = c
                    break

            if not matched:
                print(f"Candidate {args.candidate_id} not found in the selection trace.")
                sys.exit(1)

            print(f"Explanation for Candidate: {args.candidate_id}")
            print(f"Score: {matched.get('score'):.4f}")
            print("\nRationale Breakdown:")
            for line in matched.get("rationale", []):
                print(f"  - {line}")

        elif args.command == "list-compatible":
            # Load hypothesis spec
            if args.hypothesis_path:
                with open(args.hypothesis_path, encoding="utf-8") as f:
                    hyp = HypothesisSpec.model_validate_json(f.read())
            else:
                fixture_name = args.hypothesis_fixture
                if fixture_name == "sample":
                    fixture_name = "typical"
                hyp_fixture = HypothesisSpec.from_fixture(fixture_name)
                assert isinstance(hyp_fixture, HypothesisSpec)
                hyp = hyp_fixture

            # Retrieve active simulators from catalog
            from factory.selector.api import check_compatibility, is_license_ok

            print(f"Checking compatibility for metric '{hyp.measurable_metric}':")
            active_entries = catalog.list_entries(status=EntryStatus.ACTIVE)

            compatible_count = 0
            for entry in active_entries:
                if not is_license_ok(entry, catalog):
                    print(f"  - {entry.simulator_id}: IGNORED (Failed license check)")
                    continue
                comp = check_compatibility(entry, hyp, catalog)
                if comp is not None:
                    score, desc = comp
                    print(f"  - {entry.simulator_id}: COMPATIBLE (Score: {score:.2f}) -> {desc}")
                    compatible_count += 1
                else:
                    print(f"  - {entry.simulator_id}: INCOMPATIBLE")

            print(f"\nTotal compatible simulators found: {compatible_count}")

    except Exception as e:
        print(f"Error executing command: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
