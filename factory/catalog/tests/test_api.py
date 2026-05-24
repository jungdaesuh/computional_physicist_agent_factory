# test_api.py — Unit tests for the public API of catalog

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from factory.catalog.api import Catalog
from factory.catalog.errors import (
    CatalogLicenseViolation,
    CatalogLookupError,
    ContainerBuildFailed,
    EntryQuarantined,
    ManifestValidationError,
    SmokeTestFailed,
)
from factory.catalog.tests.test_catalog_typical_usage import make_valid_manifest_dict


@pytest.fixture
def setup_catalog(tmp_path: Path) -> tuple[Catalog, Path, Path]:
    """Prepares a test Catalog and database paths."""
    registry_path = tmp_path / "registry.sqlite"
    manifest_root = tmp_path / "manifests"
    license_db = tmp_path / "data"
    license_db.mkdir(parents=True)

    with open(license_db / "licenses-osi.json", "w") as f:
        json.dump({"licenses": ["MIT", "Apache-2.0"], "snapshot_hash": "test-snapshot-hash"}, f)
    with open(license_db / "redistributable-carveouts.json", "w") as f:
        json.dump({"carve_outs": []}, f)

    catalog = Catalog(
        registry_path=registry_path,
        manifest_root=manifest_root,
        license_db_path=license_db,
        builder_backend="mock",
        mock_mode=True,
    )
    return catalog, tmp_path, manifest_root


def test_manifest_validation_error(setup_catalog: tuple[Catalog, Path, Path]) -> None:
    """Verifies schema validation failure on malformed manifest dicts."""
    catalog, tmp_path, _ = setup_catalog
    manifest_dir = tmp_path / "solver-invalid"
    manifest_dir.mkdir(parents=True)

    # Missing required display_name, schema_version
    manifest_dict = make_valid_manifest_dict("solver-invalid")
    del manifest_dict["display_name"]

    with open(manifest_dir / "manifest.yaml", "w") as f:
        yaml.dump(manifest_dict, f)

    with pytest.raises(ManifestValidationError):
        catalog.onboard(manifest_dir / "manifest.yaml")


def test_license_auditor_spdx_deny(setup_catalog: tuple[Catalog, Path, Path]) -> None:
    """Tests that a dependency with a non-OSI approved license fails onboarding."""
    catalog, tmp_path, _ = setup_catalog
    manifest_dir = tmp_path / "solver-bad-license"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "Dockerfile").write_text("")

    manifest_dict = make_valid_manifest_dict("solver-bad-license")
    # Proprietary license is not in our licenses-osi.json MIT/Apache list
    manifest_dict["dependency_graph"]["nodes"][0]["license"] = "Proprietary-Commercial"

    with open(manifest_dir / "manifest.yaml", "w") as f:
        yaml.dump(manifest_dict, f)

    with pytest.raises(CatalogLicenseViolation) as exc_info:
        catalog.onboard(manifest_dir / "manifest.yaml")
    assert "Proprietary-Commercial" in str(exc_info.value)


def test_license_auditor_phrase_deny(setup_catalog: tuple[Catalog, Path, Path]) -> None:
    """Tests that a dependency carrying non-redistributable phrase riders fails onboarding."""
    catalog, tmp_path, _ = setup_catalog
    manifest_dir = tmp_path / "solver-phrase-deny"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "Dockerfile").write_text("")

    manifest_dict = make_valid_manifest_dict("solver-phrase-deny")
    # License is MIT, but the text contains a non-redistributable academic-only phrase rider
    manifest_dict["dependency_graph"]["nodes"][0]["license_text"] = (
        "This software is MIT but academic use only."
    )

    with open(manifest_dir / "manifest.yaml", "w") as f:
        yaml.dump(manifest_dict, f)

    with pytest.raises(CatalogLicenseViolation) as exc_info:
        catalog.onboard(manifest_dir / "manifest.yaml")
    assert "academic use only" in str(exc_info.value)


def test_container_build_integrity_fail(setup_catalog: tuple[Catalog, Path, Path]) -> None:
    """Tests Dockerfile and manifest install-step mismatch handling."""
    catalog, tmp_path, _ = setup_catalog
    manifest_dir = tmp_path / "solver-build-fail"
    manifest_dir.mkdir(parents=True)

    # Dockerfile has active RUN command changing the actual install steps
    (manifest_dir / "Dockerfile").write_text("RUN pip install something-new")

    manifest_dict = make_valid_manifest_dict("solver-build-fail")
    # The install_steps_hash in manifest_dict is for an empty set of RUN statements
    # so it will mismatch with the RUN pip install statement.

    with open(manifest_dir / "manifest.yaml", "w") as f:
        yaml.dump(manifest_dict, f)

    with pytest.raises(ContainerBuildFailed):
        catalog.onboard(manifest_dir / "manifest.yaml")


def test_smoke_test_failure(setup_catalog: tuple[Catalog, Path, Path]) -> None:
    """Verifies that onboarding raises SmokeTestFailed when the smoke test fails."""
    catalog, tmp_path, _ = setup_catalog
    manifest_dir = tmp_path / "solver-fail-smoke"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "Dockerfile").write_text("")

    manifest_dict = make_valid_manifest_dict("solver-fail-smoke")

    with open(manifest_dir / "manifest.yaml", "w") as f:
        yaml.dump(manifest_dict, f)

    with pytest.raises(SmokeTestFailed):
        catalog.onboard(manifest_dir / "manifest.yaml")


def test_lookup_and_quarantine_error(setup_catalog: tuple[Catalog, Path, Path]) -> None:
    """Verifies CatalogLookupError and EntryQuarantined exceptions."""
    catalog, tmp_path, _ = setup_catalog
    manifest_dir = tmp_path / "solver-quarantine"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "Dockerfile").write_text("")

    manifest_dict = make_valid_manifest_dict("solver-quarantine")
    with open(manifest_dir / "manifest.yaml", "w") as f:
        yaml.dump(manifest_dict, f)

    # Onboard
    catalog.onboard(manifest_dir / "manifest.yaml")

    # Lookup non-existent
    with pytest.raises(CatalogLookupError):
        catalog.get("non-existent-solver")

    # Quarantine
    catalog.quarantine("solver-quarantine", "testing quarantine raise")

    # Get quarantined entry should raise EntryQuarantined
    with pytest.raises(EntryQuarantined):
        catalog.get("solver-quarantine")
