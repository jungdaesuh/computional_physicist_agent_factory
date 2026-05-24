# cli.py — Command Line Interface for catalog
#
# Exposes subcommands for onboarding, building, smoke testing, and querying catalog entries.
#
# Use cases:
# 1. Onboarding a manifest: catalog onboard manifests/sim-a/manifest.yaml --mock-mode
# 2. Auditing licenses of a manifest: catalog audit-license manifests/sim-a/manifest.yaml
# 3. Listing active entries: catalog list

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from factory.catalog.api import Catalog, EntryStatus

logger = logging.getLogger("factory.catalog.cli")


def main(argv: Sequence[str] = sys.argv[1:]) -> None:
    """CLI entry point for the catalog module."""
    logger.info("main() called with args=%s", argv)
    parser = argparse.ArgumentParser(description="Catalog CLI")

    # Global options
    parser.add_argument(
        "--registry-path", default="runs/catalog/registry.sqlite", help="Path to registry database"
    )
    parser.add_argument(
        "--manifest-root", default="runs/catalog/manifests", help="Root directory holding manifests"
    )
    parser.add_argument(
        "--license-db",
        default="factory/catalog/data",
        help="Directory containing OSI and carveout files",
    )
    parser.add_argument("--mock-mode", action="store_true", help="Run catalog in mock mode")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # onboard subcommand
    onboard_parser = subparsers.add_parser("onboard", help="Onboard a new simulator manifest")
    onboard_parser.add_argument("manifest", help="Path to manifest YAML file")
    onboard_parser.add_argument("--attempt-id", help="Optional attempt identifier")

    # audit-license subcommand
    audit_parser = subparsers.add_parser("audit-license", help="Run license audit on a manifest")
    audit_parser.add_argument("manifest", help="Path to manifest YAML file")

    # build subcommand
    build_parser = subparsers.add_parser("build", help="Run container build for a manifest")
    build_parser.add_argument("manifest", help="Path to manifest YAML file")
    build_parser.add_argument("--attempt-id", help="Optional attempt identifier")

    # smoke subcommand
    smoke_parser = subparsers.add_parser("smoke", help="Run smoke test for a simulator")
    smoke_parser.add_argument("simulator_id", help="Simulator ID")
    smoke_parser.add_argument("--attempt-id", help="Optional attempt identifier")

    # list subcommand
    list_parser = subparsers.add_parser("list", help="List catalog entries")
    list_parser.add_argument(
        "--status",
        default="active",
        choices=["active", "quarantined", "deprecated"],
        help="Filter by entry status",
    )

    # show subcommand
    show_parser = subparsers.add_parser("show", help="Show details of a simulator entry")
    show_parser.add_argument("simulator_id", help="Simulator ID")

    # equivalence-map subcommand
    eq_parser = subparsers.add_parser(
        "equivalence-map", help="Show equivalence map for an observable"
    )
    eq_parser.add_argument("observable", help="Observable name")

    # quarantine subcommand
    quarantine_parser = subparsers.add_parser("quarantine", help="Quarantine a simulator entry")
    quarantine_parser.add_argument("simulator_id", help="Simulator ID")
    quarantine_parser.add_argument("reason", help="Reason for quarantine")

    args = parser.parse_args(argv)

    # Initialize Catalog
    catalog = Catalog(
        registry_path=Path(args.registry_path),
        manifest_root=Path(args.manifest_root),
        license_db_path=Path(args.license_db),
        mock_mode=args.mock_mode,
    )

    try:
        if args.command == "onboard":
            entry = catalog.onboard(Path(args.manifest), attempt_id=args.attempt_id)
            print(f"Successfully onboarded: {entry.simulator_id} (Image SHA: {entry.image_sha})")

        elif args.command == "audit-license":
            report = catalog.audit_license(Path(args.manifest))
            print(
                f"License audit result for {report.simulator_id}: {report.overall_verdict.upper()}"
            )
            for finding in report.findings:
                print(
                    f"  - {finding.node_name} ({finding.node_version}): "
                    f"{finding.declared_license} -> {finding.verdict.upper()}"
                )

        elif args.command == "build":
            sha = catalog.build(Path(args.manifest), attempt_id=args.attempt_id)
            print(f"Built image SHA: {sha}")

        elif args.command == "smoke":
            record = catalog.smoke(args.simulator_id, attempt_id=args.attempt_id)
            smoke_status = "PASSED" if record.passed else "FAILED"
            print(f"Smoke test result for {args.simulator_id}: {smoke_status}")
            print(f"  Residual: {record.max_field_residual}")

        elif args.command == "list":
            status_enum = EntryStatus(args.status)
            entries = catalog.list_entries(status_enum)
            print(f"Catalog entries ({status_enum.value}):")
            for entry in entries:
                print(f"  - {entry.simulator_id} (Manifest: {entry.manifest_hash[:8]})")

        elif args.command == "show":
            entry = catalog.get(args.simulator_id)
            print(f"Simulator: {entry.simulator_id}")
            print(f"  Status: {entry.status.value}")
            print(f"  Manifest Hash: {entry.manifest_hash}")
            print(f"  Image SHA: {entry.image_sha}")
            print(f"  Onboarded At: {entry.onboarded_at}")

        elif args.command == "equivalence-map":
            pairs = catalog.equivalence_pairs(args.observable)
            print(f"Equivalence map for observable '{args.observable}':")
            for pair in pairs:
                print(
                    f"  - {pair.cross_simulator_id}: tolerance={pair.tolerance} "
                    f"({pair.tolerance_kind})"
                )

        elif args.command == "quarantine":
            catalog.quarantine(args.simulator_id, args.reason)
            print(f"Quarantined: {args.simulator_id} (Reason: {args.reason})")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
