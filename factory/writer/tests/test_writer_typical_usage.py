"""Typical usage tests for the writer module public contract."""

from factory.writer.api import describe_contract


def test_writer_typical_usage() -> None:
    """Documents the module boundary consumed by orchestration code."""
    contract = describe_contract()

    assert contract.module_name == "writer"
    assert contract.spec_id == "011"
    assert contract.requires("EvidenceLedgerEntry")
    assert contract.produces("RunReport")
