from __future__ import annotations

from factory.state_machine.domain import parse_domain_scope_config, update_domain_scope


def test_domain_scope_parser_migrates_legacy_family_fields() -> None:
    scope = parse_domain_scope_config(
        {
            "created_at": "2026-05-23T12:00:00Z",
            "domains": ["stellarator-mhd"],
            "allowed_simulator_families": ["cfd", "md"],
            "simulators": ["vmec", "su2"],
            "expansion_criteria": ["cross-domain validation available"],
        }
    )

    assert scope.allowed_domains == ("stellarator-mhd", "cfd", "md")
    assert scope.allowed_simulator_ids == ("vmec", "su2")
    assert scope.expansion_criteria == ("cross-domain validation available",)
    assert scope.provenance_hash != "0" * 64


def test_domain_scope_update_adds_and_removes_domains_and_simulators() -> None:
    scope = parse_domain_scope_config(
        {
            "created_at": "2026-05-23T12:00:00Z",
            "allowed_domains": ["stellarator-mhd", "cfd"],
            "allowed_simulator_ids": ["vmec", "su2"],
            "expansion_criteria": ["initial"],
        }
    )
    updated = update_domain_scope(
        scope,
        {
            "remove_domains": ["cfd"],
            "add_domains": ["dft"],
            "remove_simulator_ids": ["su2"],
            "add_simulator_ids": ["qe"],
            "add_expansion_criteria": ["license approved"],
        },
    )

    assert updated.allowed_domains == ("stellarator-mhd", "dft")
    assert updated.allowed_simulator_ids == ("vmec", "qe")
    assert updated.expansion_criteria == ("initial", "license approved")
    assert updated.provenance_hash != scope.provenance_hash
