# test_selector_typical_usage.py — Integration test showing typical usage
#
# This test acts as live documentation for the module's public API.

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

import yaml

from factory.artifacts import HypothesisId, HypothesisSpec
from factory.catalog import Catalog
from factory.selector.api import Selector, TelemetryStub
from factory.selector.cli import main as cli_main

logger = logging.getLogger("factory.selector.tests")


# Helper to construct a valid manifest structure
def make_manifest_dict(
    simulator_id: str,
    computed_observables: list[str],
    license_name: str = "MIT",
    last_commit: str = "2026-05-23T12:00:00Z",
    unmaintained: bool = False,
    equivalence_map: list[dict[str, Any]] | None = None,
    per_second_cost_usd: float = 0.01,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "simulator_id": simulator_id,
        "display_name": f"Test Solver {simulator_id}",
        "domain": "stellarator-mhd",
        "license": license_name,
        "license_notice_path": "LICENSE",
        "capabilities": {
            "computed_observables": computed_observables,
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
                    "license": license_name,
                    "license_text": "Verbatim license text.",
                    "source_url": "https://github.com/example/dep",
                    "is_data_file": False,
                    "redistributable_in_container": True,
                }
            ],
            "edges": [],
        },
        "maintenance_signal": {
            "upstream_repo_url": "https://github.com/example/repo",
            "last_commit_date": last_commit,
            "latest_stable_tag": "v1.0.0",
            "last_observed_at": "2026-05-23T12:00:00Z",
        },
        "known_pathologies": [],
        "cross_simulator_equivalence_map": equivalence_map or [],
        "expected_runtime_seconds_default": 10.0,
        "per_second_cost_usd": per_second_cost_usd,
        "unmaintained_flag": unmaintained,
    }


def create_and_onboard_sim(
    catalog: Catalog,
    tmp_path: Path,
    sim_id: str,
    computed_observables: list[str],
    license_name: str = "MIT",
    last_commit: str = "2026-05-23T12:00:00Z",
    unmaintained: bool = False,
    equivalence_map: list[dict[str, Any]] | None = None,
    per_second_cost_usd: float = 0.01,
) -> None:
    manifest_dir = tmp_path / "source_manifests" / sim_id
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "Dockerfile").write_text("")

    manifest_dict_clean = make_manifest_dict(
        sim_id,
        computed_observables,
        license_name,
        last_commit,
        False,
        equivalence_map,
        per_second_cost_usd,
    )
    manifest_dict_clean.pop("expected_runtime_seconds_default", None)
    manifest_dict_clean.pop("per_second_cost_usd", None)
    manifest_dict_clean.pop("unmaintained_flag", None)

    with open(manifest_dir / "manifest.yaml", "w") as f:
        yaml.dump(manifest_dict_clean, f)

    entry = catalog.onboard(manifest_dir / "manifest.yaml")

    manifest_dict_full = make_manifest_dict(
        sim_id,
        computed_observables,
        license_name,
        last_commit,
        unmaintained,
        equivalence_map,
        per_second_cost_usd,
    )
    manifest_dict_full["manifest_hash"] = entry.manifest_hash
    with open(entry.manifest_path, "w") as f:
        yaml.dump(manifest_dict_full, f)


def test_selector_typical_usage(tmp_path: Path) -> None:
    """Demonstrates typical usage of the selector module."""
    logger.info("Running typical usage test for selector")

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

    # Initialize Catalog
    catalog = Catalog(
        registry_path=registry_path,
        manifest_root=manifest_root,
        license_db_path=license_db,
        builder_backend="mock",
        mock_mode=True,
    )

    # Onboard two compatible simulators
    # mock_solver_a (fresh, cost = 10 * 0.01 = 0.10)
    create_and_onboard_sim(
        catalog=catalog,
        tmp_path=tmp_path,
        sim_id="mock_solver_a",
        computed_observables=["mean_observable"],
        last_commit="2026-05-13T12:00:00Z",
        per_second_cost_usd=0.01,
    )

    # mock_solver_b (older, cost = 10 * 0.02 = 0.20)
    # Equivalence mapping set up between them
    create_and_onboard_sim(
        catalog=catalog,
        tmp_path=tmp_path,
        sim_id="mock_solver_b",
        computed_observables=["mean_observable"],
        last_commit="2025-05-13T12:00:00Z",
        per_second_cost_usd=0.02,
        equivalence_map=[
            {
                "observable": "mean_observable",
                "cross_simulator_id": "mock_solver_a",
                "tolerance": 1.0e-5,
                "tolerance_kind": "relative",
            }
        ],
    )

    # 2. Construct a HypothesisSpec
    hyp = HypothesisSpec(
        artifact_type="HypothesisSpec",
        created_at=datetime.datetime(2026, 5, 23, 12, 0, 0, tzinfo=datetime.UTC),
        provenance_hash="871f5fe3c29162b2f6896df5bf89cd044de3497bb45ef058e17a3c6a1390dcaa",
        parent_hashes=("f4c7df3f8f37eb6b892d220d61850bd1a684d68c8224b4dc01ba49e9326b421e",),
        hypothesis_id=HypothesisId("HYP-001"),
        parent_gap_hash="f4c7df3f8f37eb6b892d220d61850bd1a684d68c8224b4dc01ba49e9326b421e",
        if_then=(
            "If we use a Richardson refinement ratio of 2, then MHD force balance error decreases."
        ),
        measurable_metric="mean_observable",
        expected_effect_size=-0.2,
        expected_effect_unit="fractional change",
        confidence_interval=(-0.3, -0.1),
        kill_criteria=("mean_observable > 1e-3",),
        pre_registered_metric="mean_observable",
        qualified_track=False,
    )

    # Save hypothesis to disk for CLI test
    hyp_path = tmp_path / "hypothesis.json"
    with open(hyp_path, "w") as f:
        f.write(hyp.model_dump_json(indent=2))

    # Write weights configuration yaml
    weights_path = tmp_path / "weights.yaml"
    weights_dict = {
        "capability_match": 0.40,
        "license_compliance": 0.10,
        "cost": 0.20,
        "cross_simulator_availability": 0.20,
        "maintenance_freshness": 0.10,
        "ambiguity_epsilon": 0.05,
        "cost_estimate_missing_penalty": 0.15,
        "over_budget_penalty": 0.30,
    }
    with open(weights_path, "w") as f:
        yaml.dump(weights_dict, f)

    # 3. Instantiate selector with static mock telemetry
    telemetry = TelemetryStub(
        runs={("mock_solver_a", "mean_observable"): [5.0] * 10},
        min_runs=5,
    )

    selector = Selector(
        catalog=catalog,
        telemetry=telemetry,
        weights_path=weights_path,
        mock_mode=True,
    )

    # 4. Perform selection
    result = selector.select(hypothesis_spec=hyp)

    assert result.hypothesis_id == "HYP-001"
    assert len(result.candidates) == 2
    # mock_solver_a should rank first because it's fresher and cheaper
    assert result.candidates[0].simulator_id == "mock_solver_a"
    assert result.candidates[1].simulator_id == "mock_solver_b"
    assert result.candidates[0].score > result.candidates[1].score
    assert result.cross_simulator_available is True
    assert result.ambiguous is False
    assert result.failure_mode == "ok"
    assert result.trace_path.exists()

    # 5. Exercise CLI subcommands through cli_main
    # CLI subcommand: select
    cli_main(
        [
            "--registry-path",
            str(registry_path),
            "--manifest-root",
            str(manifest_root),
            "--license-db",
            str(license_db),
            "--weights-path",
            str(weights_path),
            "--mock-mode",
            "select",
            "--hypothesis-path",
            str(hyp_path),
        ]
    )

    # CLI subcommand: explain
    cli_main(
        [
            "explain",
            "--trace-path",
            str(result.trace_path),
            "--candidate-id",
            "mock_solver_a",
        ]
    )

    # CLI subcommand: list-compatible
    cli_main(
        [
            "--registry-path",
            str(registry_path),
            "--manifest-root",
            str(manifest_root),
            "--license-db",
            str(license_db),
            "list-compatible",
            "--hypothesis-path",
            str(hyp_path),
        ]
    )
