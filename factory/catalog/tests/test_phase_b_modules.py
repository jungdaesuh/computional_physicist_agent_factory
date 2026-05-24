from __future__ import annotations

import json
from pathlib import Path

import yaml

from factory.catalog.api import Catalog, SimulatorManifest
from factory.catalog.build import BuildManager, MockContainerRuntime
from factory.catalog.gate import approve_onboarding, reject_onboarding
from factory.catalog.license import LicensePolicy, audit_manifest_path
from factory.catalog.onboard import propose_manifest_from_repo
from factory.catalog.smoke import SmokeBaseline, StaticSmokeRuntime, run_smoke_against_baseline
from factory.catalog.tests.test_catalog_typical_usage import make_valid_manifest_dict


def test_manifest_proposal_extraction_from_repo_files(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("numpy==2.0.0\npyyaml>=6\n", encoding="utf-8")

    proposal = propose_manifest_from_repo(
        tmp_path,
        simulator_id="stellarator-solver",
        domain="stellarator-mhd",
        computed_observables=("iota", "volume"),
    )

    assert proposal.dockerfile_path == "Dockerfile"
    assert proposal.license_path == "LICENSE"
    assert proposal.dependency_files == ("requirements.txt",)
    assert tuple(dep.name for dep in proposal.dependencies) == ("numpy", "pyyaml")
    assert len(proposal.proposal_hash) == 64


def test_build_manager_uses_mock_runtime_without_docker(tmp_path: Path) -> None:
    manifest = make_valid_manifest_dict("solver-build")
    manifest_dir = tmp_path / "solver-build"
    manifest_dir.mkdir()
    (manifest_dir / "Dockerfile").write_text("", encoding="utf-8")
    manifest_path = manifest_dir / "manifest.yaml"
    manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

    result = BuildManager(MockContainerRuntime()).build(manifest_path, attempt_id="attempt-1")

    assert result.image_sha.startswith("sha256:")


def test_license_auditor_allow_and_deny(tmp_path: Path) -> None:
    allow_manifest = make_valid_manifest_dict("solver-license-allow")
    deny_manifest = make_valid_manifest_dict("solver-license-deny")
    deny_manifest["dependency_graph"]["nodes"][0]["license"] = "LicenseRef-Proprietary"

    allow_path = tmp_path / "allow.yaml"
    deny_path = tmp_path / "deny.yaml"
    allow_path.write_text(yaml.dump(allow_manifest), encoding="utf-8")
    deny_path.write_text(yaml.dump(deny_manifest), encoding="utf-8")
    policy = LicensePolicy(
        osi_licenses=frozenset({"MIT", "Apache-2.0"}),
        carveouts=(),
        snapshot_hash="test-snapshot",
    )

    assert audit_manifest_path(allow_path, policy).overall_verdict == "allow"
    deny_report = audit_manifest_path(deny_path, policy)
    assert deny_report.overall_verdict == "deny"
    assert deny_report.findings[0].declared_license == "LicenseRef-Proprietary"


def test_smoke_runner_passes_and_fails_from_baseline_diff(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.json"
    reference_path.write_text(json.dumps({"residual": 1.0, "status": "ok"}), encoding="utf-8")
    baseline = SmokeBaseline(reference_path=reference_path, residual_tolerance=0.05)

    passed = run_smoke_against_baseline(
        StaticSmokeRuntime({"residual": 1.02, "status": "ok"}),
        image_sha="sha256:test",
        smoke_test_target="/smoke.sh",
        baseline=baseline,
        actual_output_path=tmp_path / "pass" / "actual.json",
        diff_path=tmp_path / "pass" / "diff.json",
    )
    failed = run_smoke_against_baseline(
        StaticSmokeRuntime({"residual": 1.20, "status": "ok"}),
        image_sha="sha256:test",
        smoke_test_target="/smoke.sh",
        baseline=baseline,
        actual_output_path=tmp_path / "fail" / "actual.json",
        diff_path=tmp_path / "fail" / "diff.json",
    )

    assert passed.passed is True
    assert passed.diff_path is None
    assert failed.passed is False
    assert failed.diff_path is not None


def test_human_gate_approve_and_reject_records() -> None:
    approved = approve_onboarding("a" * 64, "solver-a", "reviewer-1")
    rejected = reject_onboarding("b" * 64, "solver-b", "reviewer-1", "missing license proof")

    assert approved.decision == "approve"
    assert rejected.decision == "reject"
    assert rejected.reason == "missing license proof"


def test_phase_b_mock_catalog_scales_to_thirty_entries_across_six_domains(
    tmp_path: Path,
) -> None:
    license_db = tmp_path / "data"
    license_db.mkdir(parents=True)
    (license_db / "licenses-osi.json").write_text(
        json.dumps({"licenses": ["MIT", "Apache-2.0"], "snapshot_hash": "test-snapshot"}),
        encoding="utf-8",
    )
    (license_db / "redistributable-carveouts.json").write_text(
        json.dumps({"carve_outs": []}),
        encoding="utf-8",
    )
    catalog = Catalog(
        registry_path=tmp_path / "registry.sqlite",
        manifest_root=tmp_path / "manifests",
        license_db_path=license_db,
        builder_backend="mock",
        mock_mode=True,
    )
    domains = (
        "stellarator-mhd",
        "molecular-dynamics",
        "plasma-kinetics",
        "climate-fluid",
        "quantum-materials",
        "accelerator-beam",
    )

    for domain_index, domain in enumerate(domains):
        observable = f"{domain}-phase-b-observable"
        ids = tuple(f"{domain}-solver-{entry_index}" for entry_index in range(5))
        for entry_index, simulator_id in enumerate(ids):
            manifest_dir = tmp_path / "source_manifests" / simulator_id
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "Dockerfile").write_text("", encoding="utf-8")
            manifest = make_valid_manifest_dict(simulator_id)
            manifest["domain"] = domain
            manifest["display_name"] = f"Phase B {domain} Solver {entry_index}"
            manifest["capabilities"]["computed_observables"] = [observable]
            manifest["capabilities"]["supported_regimes"] = [f"domain-{domain_index}"]
            manifest["cross_simulator_equivalence_map"] = (
                []
                if entry_index == 0
                else [
                    {
                        "observable": observable,
                        "cross_simulator_id": ids[0],
                        "tolerance": 1.0e-5,
                        "tolerance_kind": "relative",
                    }
                ]
            )
            (manifest_dir / "manifest.yaml").write_text(
                yaml.dump(manifest),
                encoding="utf-8",
            )

            catalog.onboard(manifest_dir / "manifest.yaml")

    active_entries = catalog.list_entries()
    onboarded_domains = set()
    for entry in active_entries:
        raw_manifest: object = yaml.safe_load(Path(entry.manifest_path).read_text(encoding="utf-8"))
        onboarded_domains.add(SimulatorManifest.model_validate(raw_manifest).domain)

    assert len(active_entries) == 30
    assert onboarded_domains == set(domains)
    for domain in domains:
        observable = f"{domain}-phase-b-observable"
        assert len(catalog.list_for_observable(observable)) == 5
        assert len(catalog.equivalence_pairs(observable)) >= 4
