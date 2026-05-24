# test_api.py — Unit tests for the Simulator Selector public API
#
# Covers:
# 1. Weights validation (must sum to 1.0) and config loading.
# 2. Compatibility filtering (direct, equivalence-mapped, and superset matches).
# 3. Cost estimation using Telemetry vs default manifest vs static fallback.
# 4. Freshness calculation (commit date recency decay, unmaintained flag).
# 5. deterministic candidate ranking (score desc, name/id asc).
# 6. Ambiguity tie-detection within epsilon.
# 7. Budget constraint penalties and "all_over_budget" failure classification.
# 8. CatalogStaleError if the catalog drifts during selection.

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from factory.artifacts import DomainScope, HypothesisId, HypothesisSpec
from factory.catalog import Catalog, CatalogEntry
from factory.selector.api import (
    Selector,
    SelectorWeights,
    TelemetryStub,
    check_compatibility,
    is_license_ok,
)
from factory.selector.errors import (
    CatalogStaleError,
    SelectorConfigError,
)


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


@pytest.fixture
def setup_test_catalog(tmp_path: Path) -> tuple[Catalog, Path]:
    """Prepares a clean Catalog for testing."""
    registry_path = tmp_path / "registry.sqlite"
    manifest_root = tmp_path / "manifests"
    license_db = tmp_path / "data"
    license_db.mkdir(parents=True)

    with open(license_db / "licenses-osi.json", "w") as f:
        json.dump({"licenses": ["MIT", "Apache-2.0"], "snapshot_hash": "test-snapshot-hash"}, f)
    with open(license_db / "redistributable-carveouts.json", "w") as f:
        json.dump({"carve_outs": []}, f)

    catalog = Catalog(
        registry_path=registry_path,
        manifest_root=manifest_root,
        license_db_path=license_db,
        builder_backend="mock",
        mock_mode=True,
    )
    return catalog, tmp_path


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

    # 1. Clean dict (no extra fields) for onboarding validation
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


def make_hypothesis(
    metric: str,
    created_at: datetime.datetime = datetime.datetime(2026, 5, 23, 12, 0, 0, tzinfo=datetime.UTC),
) -> HypothesisSpec:
    return HypothesisSpec(
        artifact_type="HypothesisSpec",
        created_at=created_at,
        provenance_hash="871f5fe3c29162b2f6896df5bf89cd044de3497bb45ef058e17a3c6a1390dcaa",
        parent_hashes=("f4c7df3f8f37eb6b892d220d61850bd1a684d68c8224b4dc01ba49e9326b421e",),
        hypothesis_id=HypothesisId("hyp-123"),
        parent_gap_hash="f4c7df3f8f37eb6b892d220d61850bd1a684d68c8224b4dc01ba49e9326b421e",
        if_then="If we use A, then metric will improve",
        measurable_metric=metric,
        expected_effect_size=1.5,
        expected_effect_unit="percent",
        confidence_interval=(1.0, 2.0),
        kill_criteria=("metric < 0",),
        pre_registered_metric="metric",
        qualified_track=False,
    )


# --------------------------------------------------------------------------
# Test Cases
# --------------------------------------------------------------------------


def test_weights_validation_success() -> None:
    """Verifies SelectorWeights validations accept exactly 1.0 sum."""
    weights = SelectorWeights(
        capability_match=0.40,
        license_compliance=0.10,
        cost=0.20,
        cross_simulator_availability=0.20,
        maintenance_freshness=0.10,
        ambiguity_epsilon=0.03,
        cost_estimate_missing_penalty=0.15,
        over_budget_penalty=0.30,
    )
    assert weights.capability_match == 0.40


def test_weights_validation_failure() -> None:
    """Verifies SelectorWeights validations reject sums not equal to 1.0."""
    with pytest.raises(SelectorConfigError, match="Weights sum must be 1.0"):
        Selector(
            catalog=None,  # type: ignore
            weights=SelectorWeights(
                capability_match=0.50,
                license_compliance=0.10,
                cost=0.20,
                cross_simulator_availability=0.20,
                maintenance_freshness=0.10,  # Sum = 1.1
                ambiguity_epsilon=0.03,
                cost_estimate_missing_penalty=0.15,
                over_budget_penalty=0.30,
            ),
        )


def test_compatibility_scoring(setup_test_catalog: tuple[Catalog, Path]) -> None:
    """Tests compatibility subscores for direct, equivalence, and superset matches."""
    catalog, tmp_path = setup_test_catalog

    # 1. Direct match (mean_observable)
    create_and_onboard_sim(catalog, tmp_path, "sim-direct", ["mean_observable"])

    # 2. Equivalence match
    create_and_onboard_sim(
        catalog,
        tmp_path,
        "sim-equiv",
        ["other_observable"],
        equivalence_map=[
            {
                "observable": "mean_observable",
                "cross_simulator_id": "sim-direct",
                "tolerance": 1.0e-5,
                "tolerance_kind": "relative",
            }
        ],
    )

    # 3. Superset match
    # mhd_equilibrium computes iota, a special case of mean_observable?
    # Let's check SUPERSET_MAP: "mhd_equilibrium" ->
    # ["force_balance_residual", "magnetic_well", "iota", "mean_observable"]
    create_and_onboard_sim(catalog, tmp_path, "sim-superset", ["mhd_equilibrium"])

    # 4. Incompatible
    create_and_onboard_sim(catalog, tmp_path, "sim-incompatible", ["unrelated_metric"])

    hyp = make_hypothesis("mean_observable")

    # Evaluate compatibility for direct
    entry_direct = catalog.get("sim-direct")
    res_direct = check_compatibility(entry_direct, hyp, catalog)
    assert res_direct is not None
    assert res_direct[0] == 1.0

    # Evaluate compatibility for equivalence
    entry_equiv = catalog.get("sim-equiv")
    res_equiv = check_compatibility(entry_equiv, hyp, catalog)
    assert res_equiv is not None
    assert res_equiv[0] == 0.85

    # Evaluate compatibility for superset
    entry_superset = catalog.get("sim-superset")
    res_superset = check_compatibility(entry_superset, hyp, catalog)
    assert res_superset is not None
    assert res_superset[0] == 0.70

    # Evaluate compatibility for incompatible
    entry_inc = catalog.get("sim-incompatible")
    assert check_compatibility(entry_inc, hyp, catalog) is None


def test_license_auditor_filter(setup_test_catalog: tuple[Catalog, Path]) -> None:
    """Verifies that is_license_ok detects license deny verdicts."""
    catalog, tmp_path = setup_test_catalog
    create_and_onboard_sim(catalog, tmp_path, "sim-good", ["mean_observable"])
    create_and_onboard_sim(catalog, tmp_path, "sim-license-deny", ["mean_observable"])

    # Mock the license audit report directory for sim-license-deny
    entry_bad = catalog.get("sim-license-deny")
    audit_dir = Path(entry_bad.license_audit_report_path)
    audit_dir.mkdir(parents=True, exist_ok=True)
    with open(audit_dir / "license_audit_report.json", "w") as f:
        json.dump({"overall_verdict": "deny"}, f)

    entry_good = catalog.get("sim-good")
    assert is_license_ok(entry_good, catalog) is True
    assert is_license_ok(entry_bad, catalog) is False


def test_cost_estimation(setup_test_catalog: tuple[Catalog, Path]) -> None:
    """Tests telemetry-based vs manifest default vs fallback cost estimation."""
    catalog, tmp_path = setup_test_catalog

    # Onboard sim with expected_runtime_seconds_default = 10,
    # per_second_cost_usd = 0.01 (cost = 0.10)
    create_and_onboard_sim(catalog, tmp_path, "sim-cost", ["mean_observable"])
    entry = catalog.get("sim-cost")

    hyp = make_hypothesis("mean_observable")

    # 1. No Telemetry (Fallback to manifest)
    selector_no_tel = Selector(catalog=catalog, telemetry=None, weights=None, mock_mode=True)
    ce_manifest = selector_no_tel._estimate_cost(entry, hyp)
    assert ce_manifest.source == "manifest"
    assert ce_manifest.expected_runtime_seconds == 10.0
    assert ce_manifest.expected_cost_usd == 0.10
    assert ce_manifest.confidence == "low"

    # 2. Telemetry with high confidence (12 runs)
    tel_high = TelemetryStub(
        runs={("sim-cost", "mean_observable"): [5.0] * 12},
        min_runs=5,
    )
    selector_high = Selector(catalog=catalog, telemetry=tel_high, weights=None, mock_mode=True)
    ce_high = selector_high._estimate_cost(entry, hyp)
    assert ce_high.source == "telemetry"
    assert ce_high.expected_runtime_seconds == 5.0
    assert ce_high.expected_cost_usd == 0.05
    assert ce_high.confidence == "high"

    # 3. Telemetry with low confidence (3 runs, min_runs=5)
    tel_low = TelemetryStub(
        runs={("sim-cost", "mean_observable"): [4.0, 5.0, 6.0]},
        min_runs=5,
    )
    selector_low = Selector(catalog=catalog, telemetry=tel_low, weights=None, mock_mode=True)
    ce_low = selector_low._estimate_cost(entry, hyp)
    # Since run count 3 < min_runs 5, telemetry falls back to manifest
    assert ce_low.source == "manifest"
    assert ce_low.expected_runtime_seconds == 10.0


def test_freshness_decay(setup_test_catalog: tuple[Catalog, Path]) -> None:
    """Tests recency freshness soft decay calculation."""
    catalog, tmp_path = setup_test_catalog

    # Created date: 2026-05-23T12:00:00Z
    # Commit dates:
    # 1. 100 days ago (freshness = 1.0)
    create_and_onboard_sim(
        catalog,
        tmp_path,
        "sim-fresh",
        ["mean_observable"],
        last_commit="2026-02-12T12:00:00Z",
    )

    # 2. 455 days ago (freshness decay from 180 to 730 days)
    # (455 - 180) / (730 - 180) = 275 / 550 = 0.5 -> freshness should be 1.0 - 0.5 = 0.5
    create_and_onboard_sim(
        catalog,
        tmp_path,
        "sim-decay",
        ["mean_observable"],
        last_commit="2025-02-22T12:00:00Z",
    )

    # 3. 800 days ago (freshness = 0.0)
    create_and_onboard_sim(
        catalog,
        tmp_path,
        "sim-stale",
        ["mean_observable"],
        last_commit="2024-03-15T12:00:00Z",
    )

    # 4. Unmaintained flag set (freshness = 0.0)
    create_and_onboard_sim(
        catalog,
        tmp_path,
        "sim-unmaintained",
        ["mean_observable"],
        last_commit="2026-05-01T12:00:00Z",
        unmaintained=True,
    )

    hyp = make_hypothesis(
        "mean_observable",
        created_at=datetime.datetime(2026, 5, 23, 12, 0, 0, tzinfo=datetime.UTC),
    )
    selector = Selector(catalog=catalog, telemetry=None, weights=None, mock_mode=True)

    assert selector._calculate_freshness(catalog.get("sim-fresh"), hyp) == 1.0
    assert (
        pytest.approx(selector._calculate_freshness(catalog.get("sim-decay"), hyp), abs=1e-3) == 0.5
    )
    assert selector._calculate_freshness(catalog.get("sim-stale"), hyp) == 0.0
    assert selector._calculate_freshness(catalog.get("sim-unmaintained"), hyp) == 0.0


def test_ranking_determinism(setup_test_catalog: tuple[Catalog, Path]) -> None:
    """Verifies that candidate sorting ranks by score desc, then simulator_id asc."""
    catalog, tmp_path = setup_test_catalog

    # Create two simulators with identical capabilities and costs
    create_and_onboard_sim(catalog, tmp_path, "sim-beta", ["mean_observable"])
    create_and_onboard_sim(catalog, tmp_path, "sim-alpha", ["mean_observable"])

    hyp = make_hypothesis("mean_observable")
    selector = Selector(catalog=catalog, telemetry=None, weights=None, mock_mode=True)

    result = selector.select(hyp)
    # Scores are identical, so they should be sorted lexicographically: sim-alpha then sim-beta
    assert len(result.candidates) == 2
    assert result.candidates[0].simulator_id == "sim-alpha"
    assert result.candidates[1].simulator_id == "sim-beta"


def test_ambiguity_tie_flagging(setup_test_catalog: tuple[Catalog, Path]) -> None:
    """Tests that ambiguous = True is returned if top two candidates are within epsilon."""
    catalog, tmp_path = setup_test_catalog

    # Two similar simulators, one slightly older (commit 10 days ago vs 12 days ago)
    create_and_onboard_sim(
        catalog,
        tmp_path,
        "sim-x",
        ["mean_observable"],
        last_commit="2026-05-13T12:00:00Z",
    )
    create_and_onboard_sim(
        catalog,
        tmp_path,
        "sim-y",
        ["mean_observable"],
        last_commit="2026-05-11T12:00:00Z",
    )

    hyp = make_hypothesis("mean_observable")

    weights = SelectorWeights(
        capability_match=0.40,
        license_compliance=0.10,
        cost=0.20,
        cross_simulator_availability=0.20,
        maintenance_freshness=0.10,
        ambiguity_epsilon=0.05,  # Epsilon larger than the freshness difference
        cost_estimate_missing_penalty=0.15,
        over_budget_penalty=0.30,
    )
    selector = Selector(catalog=catalog, telemetry=None, weights=weights, mock_mode=True)
    result = selector.select(hyp)
    assert result.ambiguous is True


def test_budget_cap_enforcement(setup_test_catalog: tuple[Catalog, Path]) -> None:
    """Verifies over-budget penalty application and all_over_budget failure mode."""
    catalog, tmp_path = setup_test_catalog

    create_and_onboard_sim(
        catalog,
        tmp_path,
        "sim-expensive",
        ["mean_observable"],
        per_second_cost_usd=0.05,
    )

    hyp = make_hypothesis("mean_observable")
    selector = Selector(catalog=catalog, telemetry=None, weights=None, mock_mode=True)

    # Budget cap = 0.20 USD, but candidate costs 0.50 USD
    result = selector.select(hyp, budget_dollar_cap=0.20)
    assert len(result.candidates) == 1
    assert result.candidates[0].over_budget is True
    assert "over_budget" in result.candidates[0].flags
    assert result.failure_mode == "all_over_budget"


def test_catalog_version_drift(setup_test_catalog: tuple[Catalog, Path]) -> None:
    """Tests that CatalogStaleError is raised if the catalog changes during selection."""
    catalog, tmp_path = setup_test_catalog
    create_and_onboard_sim(catalog, tmp_path, "sim-drift", ["mean_observable"])

    hyp = make_hypothesis("mean_observable")

    # We subclass Catalog to dynamically change its version hash when called
    class DriftingCatalog(Catalog):
        def __init__(self, original: Catalog) -> None:
            self._original = original
            self._version_calls = 0

        def version_hash(self) -> str:
            self._version_calls += 1
            if self._version_calls == 1:
                return "hash-version-1"
            return "hash-version-2"

        def list_entries(self, status: Any = None) -> list[CatalogEntry]:
            return self._original.list_entries(status)

        def list_for_observable(self, observable: str) -> list[CatalogEntry]:
            return self._original.list_for_observable(observable)

        def equivalence_pairs(self, observable: str) -> list[Any]:
            return self._original.equivalence_pairs(observable)

    drift_catalog = DriftingCatalog(catalog)
    selector = Selector(catalog=drift_catalog, telemetry=None, weights=None, mock_mode=True)

    with pytest.raises(CatalogStaleError, match="Catalog version changed"):
        selector.select(hyp)


def test_empty_domain_scope_allows_all_catalog_entries(
    setup_test_catalog: tuple[Catalog, Path],
) -> None:
    catalog, tmp_path = setup_test_catalog
    create_and_onboard_sim(catalog, tmp_path, "sim-alpha", ["mean_observable"])
    create_and_onboard_sim(catalog, tmp_path, "sim-beta", ["mean_observable"])

    scope = DomainScope(
        artifact_type="DomainScope",
        created_at=datetime.datetime(2026, 5, 23, 12, 0, 0, tzinfo=datetime.UTC),
        provenance_hash="0" * 64,
        parent_hashes=(),
        allowed_domains=(),
        allowed_simulator_ids=(),
        expansion_criteria=(),
    )
    selector = Selector(catalog=catalog, telemetry=None, weights=None, mock_mode=True)
    result = selector.select(make_hypothesis("mean_observable"), domain_scope=scope)

    assert tuple(candidate.simulator_id for candidate in result.candidates) == (
        "sim-alpha",
        "sim-beta",
    )


def test_domain_scope_matches_documented_domain_label_variants(
    setup_test_catalog: tuple[Catalog, Path],
) -> None:
    catalog, tmp_path = setup_test_catalog
    create_and_onboard_sim(catalog, tmp_path, "sim-stellarator", ["mean_observable"])

    scope = DomainScope(
        artifact_type="DomainScope",
        created_at=datetime.datetime(2026, 5, 23, 12, 0, 0, tzinfo=datetime.UTC),
        provenance_hash="0" * 64,
        parent_hashes=(),
        allowed_domains=("stellarator_MHD", "cfd", "md", "dft", "plasma-edge", "materials"),
        allowed_simulator_ids=(),
        expansion_criteria=(),
    )
    selector = Selector(catalog=catalog, telemetry=None, weights=None, mock_mode=True)
    result = selector.select(make_hypothesis("mean_observable"), domain_scope=scope)

    assert tuple(candidate.simulator_id for candidate in result.candidates) == ("sim-stellarator",)
