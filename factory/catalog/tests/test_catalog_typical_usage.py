# test_catalog_typical_usage.py — Integration test showing typical usage
#
# This test acts as live documentation for the module's public API.

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
import yaml

from factory.catalog.api import Catalog, EntryStatus
from factory.catalog.errors import EntryQuarantined

logger = logging.getLogger("factory.catalog.tests")


def make_valid_manifest_dict(simulator_id: str) -> dict[str, Any]:
    """Helper to construct a valid manifest structure."""
    return {
        "schema_version": "1.0",
        "simulator_id": simulator_id,
        "display_name": f"Mock Solver {simulator_id}",
        "domain": "stellarator-mhd",
        "license": "MIT",
        "license_notice_path": "LICENSE",
        "capabilities": {
            "computed_observables": ["mean_observable"],
            "supported_regimes": ["vacuum"],
            "explicit_limits": [],
            "fidelity_levels": ["dry_run", "oracle"],
        },
        "io_schema": {
            "input_format": "json",
            "input_schema_path": "schemas/input.schema.json",
            "output_format": "json",
            "output_schema_path": "schemas/output.schema.json",
        },
        "container_recipe": {
            "dockerfile_path": "Dockerfile",
            "base_image": "docker.io/library/debian",
            "base_image_sha": (
                "sha256:4a0cf8b6e0811e51f893e92cf4de6e2467d02cf691e1d2bf2467d02cf691e1d2b"
            ),
            "install_steps_hash": (
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            ),
            "smoke_test_target": "/out/smoke_test.sh",
            "expected_smoke_runtime_seconds": 1.0,
            "hermetic": True,
        },
        "dependency_graph": {
            "mpi_flavor": "none",
            "blas_variant": "none",
            "compiler": "gcc-13.2",
            "os_family": "debian",
            "nodes": [
                {
                    "name": "base-dependency",
                    "version": "1.0.0",
                    "license": "MIT",
                    "license_text": "Verbatim MIT license text goes here.",
                    "source_url": "https://github.com/example/dep",
                    "is_data_file": False,
                    "redistributable_in_container": True,
                }
            ],
            "edges": [],
        },
        "maintenance_signal": {
            "upstream_repo_url": "https://github.com/example/repo",
            "last_commit_date": "2026-05-23T12:00:00Z",
            "latest_stable_tag": "v1.0.0",
            "last_observed_at": "2026-05-23T12:00:00Z",
        },
        "known_pathologies": [],
        "cross_simulator_equivalence_map": [
            {
                "observable": "mean_observable",
                "cross_simulator_id": "solver-b",
                "tolerance": 1.0e-5,
                "tolerance_kind": "relative",
            }
        ],
    }


def test_catalog_typical_usage(tmp_path: Path) -> None:
    """Demonstrates typical usage of the catalog module."""
    logger.info("Running typical usage test for catalog")

    # 1. Setup paths
    registry_path = tmp_path / "registry.sqlite"
    manifest_root = tmp_path / "manifests"
    license_db = tmp_path / "data"
    license_db.mkdir(parents=True)

    # Write simple license database configurations
    with open(license_db / "licenses-osi.json", "w") as f:
        json.dump({"licenses": ["MIT", "Apache-2.0"], "snapshot_hash": "test-snapshot-hash"}, f)
    with open(license_db / "redistributable-carveouts.json", "w") as f:
        json.dump({"carve_outs": []}, f)

    # 2. Instantiate Catalog in mock mode
    catalog = Catalog(
        registry_path=registry_path,
        manifest_root=manifest_root,
        license_db_path=license_db,
        builder_backend="mock",
        mock_mode=True,
    )

    # 3. Write and onboard a manifest
    manifest_dir = tmp_path / "source_manifests" / "solver-a"
    manifest_dir.mkdir(parents=True)

    # We must write dummy Dockerfile to avoid path resolution errors (or mock mode handles it)
    (manifest_dir / "Dockerfile").write_text("")

    manifest_dict = make_valid_manifest_dict("solver-a")

    # Write to source directory
    with open(manifest_dir / "manifest.yaml", "w") as f:
        yaml.dump(manifest_dict, f)

    # Onboard
    entry = catalog.onboard(manifest_dir / "manifest.yaml")
    assert entry.simulator_id == "solver-a"
    assert entry.status == EntryStatus.ACTIVE
    assert entry.image_sha.startswith("sha256:")

    # 4. Get entry from catalog
    retrieved = catalog.get("solver-a")
    assert retrieved.simulator_id == "solver-a"
    assert retrieved.manifest_hash == entry.manifest_hash

    # 5. List entries
    active_entries = catalog.list_entries(EntryStatus.ACTIVE)
    assert len(active_entries) == 1
    assert active_entries[0].simulator_id == "solver-a"

    # 6. List for observable
    obs_entries = catalog.list_for_observable("mean_observable")
    assert len(obs_entries) == 1
    assert obs_entries[0].simulator_id == "solver-a"

    # 7. Check Version Hash
    v_hash = catalog.version_hash()
    assert len(v_hash) == 64

    # 8. Check Equivalence pairs
    # Wait, solver-b is not in catalog yet, but we declared equivalence.
    # In onboard, equivalence is inserted if counterparts exist. Since solver-b doesn't exist,
    # the equivalence row was skipped. Let's onboard solver-b to test it.
    solver_b_dir = tmp_path / "source_manifests" / "solver-b"
    solver_b_dir.mkdir(parents=True)
    (solver_b_dir / "Dockerfile").write_text("")
    solver_b_dict = make_valid_manifest_dict("solver-b")
    solver_b_dict["cross_simulator_equivalence_map"] = [
        {
            "observable": "mean_observable",
            "cross_simulator_id": "solver-a",
            "tolerance": 1.0e-5,
            "tolerance_kind": "relative",
        }
    ]
    with open(solver_b_dir / "manifest.yaml", "w") as f:
        yaml.dump(solver_b_dict, f)

    # Onboard B
    catalog.onboard(solver_b_dir / "manifest.yaml")

    # Check equivalence map again
    pairs = catalog.equivalence_pairs("mean_observable")
    assert len(pairs) == 2  # both directions a->b and b->a exist now

    # 9. Verify reverification and quarantine
    report = catalog.reverify_all()
    assert report.entries_checked == 2
    assert len(report.entries_passed) == 2

    # Quarantine an entry
    catalog.quarantine("solver-a", "manually triggered")
    with pytest.raises(EntryQuarantined):
        catalog.get("solver-a")
