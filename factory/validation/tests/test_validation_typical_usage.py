"""Typical usage tests for the validation module public contract."""

from factory.validation.api import describe_contract


def test_validation_typical_usage() -> None:
    """Documents the module boundary consumed by orchestration code."""
    contract = describe_contract()

    assert contract.module_name == "validation"
    assert contract.spec_id == "009"
    assert contract.requires("RunOutputs")
    assert contract.produces("ValidationResult")
