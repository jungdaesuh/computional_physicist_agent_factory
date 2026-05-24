"""Typical usage tests for the surrogate module public contract."""

from factory.surrogate.api import describe_contract


def test_surrogate_typical_usage() -> None:
    """Documents the module boundary consumed by orchestration code."""
    contract = describe_contract()

    assert contract.module_name == "surrogate"
    assert contract.spec_id == "010"
    assert contract.requires("CandidateFeatures")
    assert contract.produces("SurrogateProbeResult")
