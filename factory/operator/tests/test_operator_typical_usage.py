"""Typical usage tests for the operator module public contract."""

from factory.operator.api import describe_contract


def test_operator_typical_usage() -> None:
    """Documents the module boundary consumed by orchestration code."""
    contract = describe_contract()

    assert contract.module_name == "operator"
    assert contract.spec_id == "015"
    assert contract.requires("FactoryControlCommand")
    assert contract.produces("FactoryControlEvent")
