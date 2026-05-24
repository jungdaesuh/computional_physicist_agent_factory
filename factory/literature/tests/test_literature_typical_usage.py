"""Typical usage tests for the literature module public contract."""

from factory.literature.api import describe_contract


def test_literature_typical_usage() -> None:
    """Documents the module boundary consumed by orchestration code."""
    contract = describe_contract()

    assert contract.module_name == "literature"
    assert contract.spec_id == "007"
    assert contract.requires("OpenAlexWork")
    assert contract.produces("GapCandidate")
