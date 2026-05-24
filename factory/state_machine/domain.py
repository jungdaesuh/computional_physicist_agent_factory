"""DomainScope migration parsing for state-machine scope updates."""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence

from factory.artifacts import DomainScope, SimulatorId

_ZERO_HASH = "0" * 64


def parse_domain_scope_config(raw: DomainScope | Mapping[str, object]) -> DomainScope:
    """Parse current or legacy config/artifact payloads into a DomainScope."""

    if isinstance(raw, DomainScope):
        return raw

    created_at = _parse_created_at(raw.get("created_at"))
    parent_hashes = _string_tuple(raw.get("parent_hashes"))
    domains = _unique_strings(
        (
            *_string_tuple(raw.get("allowed_domains")),
            *_string_tuple(raw.get("domains")),
            *_string_tuple(raw.get("allowed_simulator_families")),
            *_string_tuple(raw.get("simulator_families")),
        )
    )
    simulator_ids = _simulator_id_tuple(
        _unique_strings(
            (
                *_string_tuple(raw.get("allowed_simulator_ids")),
                *_string_tuple(raw.get("simulator_ids")),
                *_string_tuple(raw.get("simulators")),
            )
        )
    )
    expansion_criteria = _unique_strings(_string_tuple(raw.get("expansion_criteria")))

    scope = DomainScope(
        artifact_type=str(raw.get("artifact_type") or "DomainScope"),
        created_at=created_at,
        provenance_hash=_ZERO_HASH,
        parent_hashes=parent_hashes,
        allowed_domains=domains,
        allowed_simulator_ids=simulator_ids,
        expansion_criteria=expansion_criteria,
    )
    return scope.model_copy(update={"provenance_hash": scope.compute_hash()})


def update_domain_scope(
    current_scope: DomainScope,
    update: Mapping[str, object],
) -> DomainScope:
    """Apply additive/removal domain and simulator changes to a DomainScope."""

    remove_domains = frozenset(_string_tuple(update.get("remove_domains")))
    add_domains = _string_tuple(update.get("add_domains"))
    remove_simulator_ids = frozenset(_string_tuple(update.get("remove_simulator_ids")))
    add_simulator_ids = _string_tuple(update.get("add_simulator_ids"))
    add_criteria = _string_tuple(update.get("add_expansion_criteria"))

    domains = _unique_strings(
        (
            *[domain for domain in current_scope.allowed_domains if domain not in remove_domains],
            *add_domains,
        )
    )
    simulator_ids = _simulator_id_tuple(
        _unique_strings(
            (
                *[
                    str(simulator_id)
                    for simulator_id in current_scope.allowed_simulator_ids
                    if str(simulator_id) not in remove_simulator_ids
                ],
                *add_simulator_ids,
            )
        )
    )
    expansion_criteria = _unique_strings((*current_scope.expansion_criteria, *add_criteria))

    scope = current_scope.model_copy(
        update={
            "provenance_hash": _ZERO_HASH,
            "allowed_domains": domains,
            "allowed_simulator_ids": simulator_ids,
            "expansion_criteria": expansion_criteria,
        }
    )
    return scope.model_copy(update={"provenance_hash": scope.compute_hash()})


def _parse_created_at(value: object) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return datetime.datetime.now(datetime.UTC)


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        strings: list[str] = []
        for item in value:
            if isinstance(item, str):
                strings.append(item)
            else:
                raise ValueError(f"Expected string sequence item, got {item!r}")
        return tuple(strings)
    raise ValueError(f"Expected string or string sequence, got {value!r}")


def _unique_strings(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return tuple(unique)


def _simulator_id_tuple(values: Sequence[str]) -> tuple[SimulatorId, ...]:
    return tuple(SimulatorId(value) for value in values)
