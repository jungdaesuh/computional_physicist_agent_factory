"""Public exports for the adapter module."""

from factory.adapter.api import (
    Adapter,
    AdapterOutputField,
    AdapterOutputSchema,
    RunArtifacts,
    describe_contract,
    load,
    load_all,
    register,
    register_mock,
    registered_ids,
    validate_catalog_parity,
)

__all__ = [
    "Adapter",
    "AdapterOutputField",
    "AdapterOutputSchema",
    "RunArtifacts",
    "describe_contract",
    "load",
    "load_all",
    "register",
    "register_mock",
    "registered_ids",
    "validate_catalog_parity",
]
