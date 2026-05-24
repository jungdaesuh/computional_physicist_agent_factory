"""Typical usage tests for the state_machine module public contract."""

from factory.state_machine.api import describe_contract


def test_state_machine_typical_usage() -> None:
    """Documents the module boundary consumed by orchestration code."""
    contract = describe_contract()

    assert contract.module_name == "state_machine"
    assert contract.spec_id == "003"
    assert contract.requires("FactoryState")
    assert contract.produces("FactoryStateTransition")
