"""Typical usage tests for the fidelity module public contract."""

from factory.fidelity.api import describe_contract


def test_fidelity_typical_usage() -> None:
    """Documents the module boundary consumed by orchestration code."""
    contract = describe_contract()

    assert contract.module_name == "fidelity"
    assert contract.spec_id == "017"
    assert contract.requires("ExperimentSpec")
    assert contract.produces("FidelityTierDecision")
