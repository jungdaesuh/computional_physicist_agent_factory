"""SPDX-oriented license audit helpers for catalog manifests."""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError

from factory.catalog.api import (
    CarveOutLicense,
    LicenseAuditReport,
    LicenseFinding,
    SimulatorId,
    SimulatorManifest,
)
from factory.catalog.errors import ManifestValidationError


@dataclass(frozen=True)
class LicensePolicy:
    """License allow-list and data-file carve-outs used for one audit run."""

    osi_licenses: frozenset[str]
    carveouts: tuple[Mapping[str, object], ...]
    snapshot_hash: str


_NON_REDISTRIBUTABLE_PHRASES = (
    "academic use only",
    "non-commercial",
    "noncommercial",
    "registration required",
    "redistribution prohibited",
    "research only",
    "personal use only",
    "evaluation only",
    "no commercial use",
    "not for commercial",
)


def audit_manifest_path(manifest_path: Path, policy: LicensePolicy) -> LicenseAuditReport:
    """Load a manifest and audit all declared transitive dependency licenses."""

    raw = yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ManifestValidationError(f"Manifest must be a YAML object: {manifest_path}")
    if "manifest_hash" not in raw:
        raw["manifest_hash"] = "temp"
    try:
        manifest = SimulatorManifest(**raw)
    except ValidationError as exc:
        raise ManifestValidationError(f"Manifest schema mismatch: {exc}") from exc
    return audit_manifest_dependencies(manifest, policy)


def audit_manifest_dependencies(
    manifest: SimulatorManifest,
    policy: LicensePolicy,
    audited_at: datetime.datetime | None = None,
) -> LicenseAuditReport:
    """Audit SPDX identifiers and redistributability for manifest dependencies."""

    findings: list[LicenseFinding] = []
    overall_verdict: Literal["allow", "deny"] = "allow"
    for node in manifest.dependency_graph.nodes:
        verdict: Literal["allow", "deny"] = "allow"
        deny_reason: str | None = None
        osi_approved = node.license in policy.osi_licenses

        if not osi_approved and not _has_data_file_carveout(
            simulator_id=manifest.simulator_id,
            package_name=node.name,
            license_id=node.license,
            is_data_file=node.is_data_file,
            carveouts=policy.carveouts,
        ):
            verdict = "deny"
            deny_reason = f"License {node.license} is not OSI-approved and no carve-out matches"

        phrase = _first_non_redistributable_phrase(node.license_text)
        if phrase is not None:
            verdict = "deny"
            deny_reason = f"non-redistributable phrase in LICENSE text: '{phrase}'"

        if not node.redistributable_in_container:
            verdict = "deny"
            deny_reason = "Dependency marked as not redistributable in container"

        if verdict == "deny":
            overall_verdict = "deny"

        findings.append(
            LicenseFinding(
                node_name=node.name,
                node_version=node.version,
                declared_license=node.license,
                osi_approved=osi_approved,
                redistributable_in_container=node.redistributable_in_container,
                is_data_file=node.is_data_file,
                verdict=verdict,
                deny_reason=deny_reason,
            )
        )

    return LicenseAuditReport(
        simulator_id=manifest.simulator_id,
        audited_at=audited_at or datetime.datetime.now(datetime.UTC),
        nodes_checked=len(manifest.dependency_graph.nodes),
        findings=tuple(findings),
        overall_verdict=overall_verdict,
        osi_db_snapshot_hash=policy.snapshot_hash,
    )


def _has_data_file_carveout(
    simulator_id: SimulatorId,
    package_name: str,
    license_id: str,
    is_data_file: bool,
    carveouts: tuple[Mapping[str, object], ...],
) -> bool:
    if not is_data_file or license_id not in {item.value for item in CarveOutLicense}:
        return False
    for carveout in carveouts:
        package_matches = carveout.get("package") == package_name
        simulator_matches = carveout.get("simulator_id") in {None, simulator_id}
        license_matches = carveout.get("license") in {None, license_id}
        if package_matches and simulator_matches and license_matches:
            return True
    return False


def _first_non_redistributable_phrase(license_text: str) -> str | None:
    text = license_text.lower()
    for phrase in _NON_REDISTRIBUTABLE_PHRASES:
        if phrase in text:
            return phrase
    return None
