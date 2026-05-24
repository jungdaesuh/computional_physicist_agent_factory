"""In-process adapter registry keyed by simulator_id."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import overload

from factory.adapter.abstract import Adapter
from factory.adapter.errors import AdapterContractViolation, AdapterNotRegistered

_ADAPTERS: dict[str, type[Adapter]] = {}
_MOCK_ADAPTERS: dict[str, type[Adapter]] = {}


def register(adapter_cls: type[Adapter]) -> type[Adapter]:
    """Register one concrete adapter class by its simulator_id."""
    simulator_id = adapter_cls.simulator_id
    if simulator_id in _ADAPTERS:
        raise AdapterContractViolation(f"duplicate adapter registration for {simulator_id}")
    _ADAPTERS[simulator_id] = adapter_cls
    return adapter_cls


@overload
def register_mock(simulator_id: str) -> Callable[[type[Adapter]], type[Adapter]]: ...


@overload
def register_mock(simulator_id: str, adapter_cls: type[Adapter]) -> type[Adapter]: ...


def register_mock(
    simulator_id: str,
    adapter_cls: type[Adapter] | None = None,
) -> Callable[[type[Adapter]], type[Adapter]] | type[Adapter]:
    """Register the mock adapter paired with one simulator_id."""

    def _register(candidate_cls: type[Adapter]) -> type[Adapter]:
        if simulator_id in _MOCK_ADAPTERS:
            raise AdapterContractViolation(
                f"duplicate mock adapter registration for {simulator_id}"
            )
        _MOCK_ADAPTERS[simulator_id] = candidate_cls
        return candidate_cls

    if adapter_cls is None:
        return _register
    return _register(adapter_cls)


def load(simulator_id: str, *, mock_mode: bool = False) -> Adapter:
    """Return a fresh registered adapter instance."""
    registry = _MOCK_ADAPTERS if mock_mode else _ADAPTERS
    adapter_cls = registry.get(simulator_id)
    if adapter_cls is None:
        raise AdapterNotRegistered(f"no adapter registered for simulator_id={simulator_id!r}")
    adapter = adapter_cls()
    _validate_adapter_schema(adapter)
    return adapter


def registered_ids(*, mock_mode: bool = False) -> tuple[str, ...]:
    """Return registered simulator ids in deterministic order."""
    registry = _MOCK_ADAPTERS if mock_mode else _ADAPTERS
    return tuple(sorted(registry))


def load_all(*, mock_mode: bool = False) -> tuple[Adapter, ...]:
    """Return every registered adapter in deterministic order."""
    return tuple(
        load(simulator_id, mock_mode=mock_mode)
        for simulator_id in registered_ids(mock_mode=mock_mode)
    )


def validate_catalog_parity(catalog_simulator_ids: Iterable[str]) -> None:
    """Verify registered adapters and catalog ids match exactly."""
    catalog_ids = set(catalog_simulator_ids)
    adapter_ids = set(_ADAPTERS)
    if catalog_ids != adapter_ids:
        missing = sorted(catalog_ids - adapter_ids)
        extra = sorted(adapter_ids - catalog_ids)
        raise AdapterContractViolation(
            f"adapter/catalog mismatch: missing_adapters={missing}, extra_adapters={extra}"
        )


def _validate_adapter_schema(adapter: Adapter) -> None:
    schema = adapter.output_schema()
    if schema.simulator_id != adapter.simulator_id:
        raise AdapterContractViolation(
            f"schema simulator_id {schema.simulator_id!r} does not match adapter "
            f"{adapter.simulator_id!r}"
        )


__all__ = [
    "load",
    "load_all",
    "register",
    "register_mock",
    "registered_ids",
    "validate_catalog_parity",
]
