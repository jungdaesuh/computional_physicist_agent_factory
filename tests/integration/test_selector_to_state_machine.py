# test_selector_to_state_machine.py — Integration test for selector to state machine
#
# This file validates the integration contract between the Simulator Selector (Spec 005)
# and the State Machine (Spec 003). It defines a reference routing function mapping the
# Selector's failure modes to State Machine destination states/actions, and asserts the
# correct transition mapping for various selection scenarios.
#
# Use cases:
# 1. Selection result with "ok" -> routes to G2.
# 2. Selection result with "no_suitable_simulator" -> routes to lack of tooling.
# 3. Selection result with "all_over_budget" -> routes to lack of tooling.
# 4. Selection result with "cross_simulator_map_empty" -> routes to G2.

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest
import yaml

from factory.artifacts import HypothesisId, HypothesisSpec
from factory.catalog import Catalog
from factory.selector.api import SelectionResult, Selector
from factory.selector.tests.test_api import create_and_onboard_sim


def route_selection_result(result: SelectionResult) -> str:
    """Mock state machine routing logic mapping SelectionResult to next state.

    Args:
        result: The output from the Selector.

    Returns:
        The state or action string matching Spec 005 §5.8.
    """
    if result.failure_mode in ("ok", "cross_simulator_map_empty"):
        return "G2"
    elif result.failure_mode in ("no_suitable_simulator", "all_over_budget"):
        return "terminate_parked_for_lack_of_tooling"
    else:
        raise ValueError(f"Unknown failure mode: {result.failure_mode}")


@pytest.fixture
def populated_catalog(tmp_path: Path) -> tuple[Catalog, Path]:
    """Prepares a clean Catalog with one onboarded simulator computing 'mean_observable'."""
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

    create_and_onboard_sim(
        catalog=catalog,
        tmp_path=tmp_path,
        sim_id="mock_solver_a",
        computed_observables=["mean_observable"],
        per_second_cost_usd=0.01,
        equivalence_map=[
            {
                "observable": "mean_observable",
                "cross_simulator_id": "mock_solver_b",
                "tolerance": 1e-5,
                "tolerance_kind": "absolute",
                "notes": "Direct comparison",
            }
        ],
    )
    create_and_onboard_sim(
        catalog=catalog,
        tmp_path=tmp_path,
        sim_id="mock_solver_b",
        computed_observables=["mean_observable"],
        per_second_cost_usd=0.02,
    )

    # Create weights config
    weights_path = tmp_path / "weights.yaml"
    weights_dict = {
        "capability_match": 0.40,
        "license_compliance": 0.10,
        "cost": 0.20,
        "cross_simulator_availability": 0.20,
        "maintenance_freshness": 0.10,
        "ambiguity_epsilon": 0.03,
        "cost_estimate_missing_penalty": 0.15,
        "over_budget_penalty": 0.30,
    }
    with open(weights_path, "w") as f:
        yaml.dump(weights_dict, f)

    return catalog, weights_path


def make_test_hypothesis(metric: str) -> HypothesisSpec:
    """Helper to build a basic HypothesisSpec for testing."""
    return HypothesisSpec(
        artifact_type="HypothesisSpec",
        created_at=datetime.datetime(2026, 5, 23, 12, 0, 0, tzinfo=datetime.UTC),
        provenance_hash="871f5fe3c29162b2f6896df5bf89cd044de3497bb45ef058e17a3c6a1390dcaa",
        parent_hashes=("f4c7df3f8f37eb6b892d220d61850bd1a684d68c8224b4dc01ba49e9326b421e",),
        hypothesis_id=HypothesisId("hyp-integration-123"),
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


def test_routing_ok(populated_catalog: tuple[Catalog, Path]) -> None:
    """Verifies that an 'ok' selection result routes correctly to G2."""
    catalog, weights_path = populated_catalog
    selector = Selector(
        catalog=catalog,
        telemetry=None,
        weights_path=weights_path,
        mock_mode=True,
    )
    hyp = make_test_hypothesis("mean_observable")
    result = selector.select(hyp)

    assert result.failure_mode == "ok"
    assert route_selection_result(result) == "G2"


def test_routing_no_suitable_simulator(populated_catalog: tuple[Catalog, Path]) -> None:
    """Verifies that a selection result with no simulators routes to lack of tooling."""
    catalog, weights_path = populated_catalog
    selector = Selector(
        catalog=catalog,
        telemetry=None,
        weights_path=weights_path,
        mock_mode=True,
    )
    hyp = make_test_hypothesis("unsupported_metric")
    result = selector.select(hyp)

    assert result.failure_mode == "no_suitable_simulator"
    assert route_selection_result(result) == "terminate_parked_for_lack_of_tooling"


def test_routing_all_over_budget(populated_catalog: tuple[Catalog, Path]) -> None:
    """Verifies that a result where all candidates exceed budget routes to lack of tooling."""
    catalog, weights_path = populated_catalog
    selector = Selector(
        catalog=catalog,
        telemetry=None,
        weights_path=weights_path,
        mock_mode=True,
    )
    hyp = make_test_hypothesis("mean_observable")
    # All candidates in the mock catalog cost more than $0.01 (runtime 10.0 * 0.01 = 0.10)
    result = selector.select(hyp, budget_dollar_cap=0.01)

    assert result.failure_mode == "all_over_budget"
    assert route_selection_result(result) == "terminate_parked_for_lack_of_tooling"
