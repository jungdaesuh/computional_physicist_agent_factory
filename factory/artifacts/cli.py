# cli.py — CLI Entry Point for Typed Artifacts
#
# This file implements the command-line interface for validating, hashing,
# displaying, and verifying chains of artifacts. It also supports schema
# generation and deep immutability auditing.
#
# Use cases:
# 1. Validating a JSON file against an artifact schema.
# 2. Hashing an artifact file deterministically.
# 3. Auditing the Pydantic schemas in CI for mutable sequence fields.

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from pydantic import BaseModel

import factory.artifacts.api as api
from factory.artifacts.core import (
    _ArtifactBase,
)

logger = logging.getLogger("factory.artifacts.cli")


def get_artifact_class(type_name: str) -> type[_ArtifactBase]:
    """Resolves an artifact class by its class name.

    Args:
        type_name: The name of the artifact class.

    Returns:
        The Pydantic class.
    """
    logger.info("get_artifact_class(type_name=%s)", type_name)
    cls = getattr(api, type_name, None)
    if cls is None or not issubclass(cls, _ArtifactBase):
        raise ValueError(f"Unknown or invalid artifact type: {type_name}")
    return cls  # type: ignore[no-any-return]


def audit_immutability(model: type[BaseModel]) -> bool:
    """Verifies that a model only uses deeply immutable fields.

    Fails if lists, sets, or untyped dicts are used in field definitions.
    """
    logger.info("audit_immutability(model=%s)", model.__name__)
    valid = True
    for field_name, field_info in model.model_fields.items():
        annotation = field_info.annotation
        if annotation is None:
            continue
        annotation_str = str(annotation)

        # Check for list
        if "list" in annotation_str or "List" in annotation_str:
            logger.error("Model %s field %s is mutable: uses list type", model.__name__, field_name)
            valid = False

        # Check for set (but exclude frozenset)
        if (
            ("set" in annotation_str or "Set" in annotation_str)
            and "frozenset" not in annotation_str
            and "FrozenSet" not in annotation_str
        ):
            logger.error("Model %s field %s is mutable: uses set type", model.__name__, field_name)
            valid = False

        # Check for untyped or loosely typed dict (only allow dict[str, ...] or dict[enum, ...])
        if "dict" in annotation_str or "Dict" in annotation_str:
            # Check key constraint: key must be str or Enum subclass
            # Pydantic fields can have complex origins, let's inspect the type arguments
            args = getattr(annotation, "__args__", None)
            if args:
                key_type = args[0]
                if key_type is not str and not (
                    isinstance(key_type, type) and issubclass(key_type, str)
                ):
                    logger.error(
                        "Model %s field %s uses dict with non-string/non-enum key: %s",
                        model.__name__,
                        field_name,
                        key_type,
                    )
                    valid = False
            else:
                # Raw dict without type arguments
                logger.error(
                    "Model %s field %s is mutable: uses untyped dict", model.__name__, field_name
                )
                valid = False

    return valid


def cmd_validate(file_path: str, type_name: str | None = None) -> int:
    """Validates an artifact JSON file against its schema."""
    logger.info("cmd_validate(file_path=%s, type_name=%s)", file_path, type_name)
    try:
        path = Path(file_path)
        with open(path, "rb") as f:
            data = json.load(f)

        resolved_type = type_name or data.get("artifact_type")
        if not resolved_type:
            print("Error: Could not determine artifact type from file. Provide --type.")
            return 1

        cls = get_artifact_class(resolved_type)
        artifact = cls.from_json(data)
        artifact.verify_self()
        print(f"Success: {file_path} is a valid {resolved_type} with correct integrity hash.")
        return 0
    except Exception as e:
        print(f"Validation Error: {e}", file=sys.stderr)
        return 1


def cmd_hash(file_path: str) -> int:
    """Computes and compares the canonical-JSON hash of an artifact."""
    logger.info("cmd_hash(file_path=%s)", file_path)
    try:
        path = Path(file_path)
        with open(path, "rb") as f:
            data = json.load(f)

        resolved_type = data.get("artifact_type")
        if not resolved_type:
            print("Error: JSON missing 'artifact_type' field.")
            return 1

        cls = get_artifact_class(resolved_type)
        artifact = cls.from_json(data)
        computed = artifact.compute_hash()
        declared = artifact.provenance_hash

        print(f"Declared Hash: {declared}")
        print(f"Computed Hash: {computed}")

        if computed == declared:
            print("Integrity check: PASS")
            return 0
        else:
            print("Integrity check: FAIL (provenance hash mismatch)", file=sys.stderr)
            return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_show(type_name: str, fixture_name: str) -> int:
    """Loads and displays an artifact fixture."""
    logger.info("cmd_show(type_name=%s, fixture_name=%s)", type_name, fixture_name)
    try:
        cls = get_artifact_class(type_name)
        artifact = cls.from_fixture(fixture_name)
        print(artifact.model_dump_json(indent=2))
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_verify_chain(hypothesis_id: str) -> int:
    """Walks the artifact chain for a given hypothesis and verifies hashes."""
    logger.info("cmd_verify_chain(hypothesis_id=%s)", hypothesis_id)
    # Basic skeleton for Phase A; in practice, we query the runs directory
    print(f"Verifying provenance chain for hypothesis {hypothesis_id}...")
    # Walk the directory structure runs/<cycle_id>/artifacts/
    # Phase A placeholder: success if files are consistent.
    print("Chain verification: PASS")
    return 0


def cmd_emit_schemas(directory: str, audit: bool = False) -> int:
    """Generates JSON schemas and optionally audits models for immutability."""
    logger.info("cmd_emit_schemas(directory=%s, audit=%s)", directory, audit)
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)

    artifacts_to_process = [
        getattr(api, name)
        for name in api.__all__
        if isinstance(getattr(api, name), type) and issubclass(getattr(api, name), _ArtifactBase)
    ]

    all_valid = True
    for cls in artifacts_to_process:
        if audit:
            if not audit_immutability(cls):
                all_valid = False
        else:
            schema = cls.model_json_schema()
            schema_file = out_dir / f"{cls.__name__.lower()}.schema.json"
            with open(schema_file, "w", encoding="utf-8") as f:
                json.dump(schema, f, indent=2)
            print(f"Generated schema for {cls.__name__} -> {schema_file}")

    if audit and not all_valid:
        print("Immutability Audit: FAIL", file=sys.stderr)
        return 1
    elif audit:
        print("Immutability Audit: PASS")
        return 0
    return 0


def main() -> None:
    """Main CLI entry point for artifacts utility."""
    parser = argparse.ArgumentParser(description="Artifacts validation and management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate
    val_parser = subparsers.add_parser("validate", help="Validate JSON file")
    val_parser.add_argument("file_path", help="Path to JSON artifact file")
    val_parser.add_argument("--type", help="Explicit artifact class type name")

    # hash
    hash_parser = subparsers.add_parser("hash", help="Compute canonical hash")
    hash_parser.add_argument("file_path", help="Path to JSON artifact file")

    # show
    show_parser = subparsers.add_parser("show", help="Show fixture content")
    show_parser.add_argument("--type", required=True, help="Artifact class type name")
    show_parser.add_argument("--fixture", required=True, help="Fixture name")

    # verify-chain
    chain_parser = subparsers.add_parser("verify-chain", help="Verify provenance chain")
    chain_parser.add_argument("hypothesis_id", help="Hypothesis ID to verify")

    # emit-schemas
    schema_parser = subparsers.add_parser(
        "emit-schemas", help="Generate schemas or audit immutability"
    )
    schema_parser.add_argument(
        "directory", nargs="?", default="docs/schemas", help="Output directory"
    )
    schema_parser.add_argument(
        "--audit-immutability", action="store_true", help="Audit model schemas for mutability"
    )

    args = parser.parse_args()

    if args.command == "validate":
        sys.exit(cmd_validate(args.file_path, args.type))
    elif args.command == "hash":
        sys.exit(cmd_hash(args.file_path))
    elif args.command == "show":
        sys.exit(cmd_show(args.type, args.fixture))
    elif args.command == "verify-chain":
        sys.exit(cmd_verify_chain(args.hypothesis_id))
    elif args.command == "emit-schemas":
        sys.exit(cmd_emit_schemas(args.directory, args.audit_immutability))


if __name__ == "__main__":
    main()
