"""Typical usage tests for the genver module public contract."""

from factory.genver.api import describe_contract


def test_genver_typical_usage() -> None:
    """Documents the module boundary consumed by orchestration code."""
    contract = describe_contract()

    assert contract.module_name == "genver"
    assert contract.spec_id == "008"
    assert contract.requires("Budget")
    assert contract.produces("GenVerResult")
