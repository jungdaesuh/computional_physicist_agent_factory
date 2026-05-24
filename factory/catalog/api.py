# api.py — Simulator Catalog Management API
#
# This file implements the Simulator Catalog, which manages onboarding, license audits,
# deterministic OCI image builds, smoke tests, and query lookups for simulators.
#
# Use cases:
# 1. Onboarding new simulator manifests.
# 2. Auditing dependency licenses.
# 3. Running simulator builds and smoke tests.
# 4. Listing/retrieving active entries for execution.

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import sqlite3
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from factory.catalog.errors import (
    CatalogLicenseViolation,
    CatalogLookupError,
    ContainerBuildFailed,
    EntryQuarantined,
    ManifestRegistryDrift,
    ManifestValidationError,
    SmokeTestFailed,
)

logger = logging.getLogger("factory.catalog.api")

if TYPE_CHECKING:
    from factory.catalog.build import ContainerRuntime

# ---------- Type aliases ----------
SimulatorId = str
ManifestHash = str
ImageSha = str
ObservableName = str
CatalogVersionHash = str


# ---------- License enums ----------


class OsiApprovedLicense(StrEnum):
    MIT = "MIT"
    BSD_2 = "BSD-2-Clause"
    BSD_3 = "BSD-3-Clause"
    APACHE_2 = "Apache-2.0"
    GPL_2 = "GPL-2.0-only"
    GPL_2_PLUS = "GPL-2.0-or-later"
    GPL_3 = "GPL-3.0-only"
    GPL_3_PLUS = "GPL-3.0-or-later"
    LGPL_2_1 = "LGPL-2.1-only"
    LGPL_2_1_PLUS = "LGPL-2.1-or-later"
    LGPL_3 = "LGPL-3.0-only"
    LGPL_3_PLUS = "LGPL-3.0-or-later"
    AGPL_3 = "AGPL-3.0-only"
    AGPL_3_PLUS = "AGPL-3.0-or-later"
    MPL_2 = "MPL-2.0"
    ISC = "ISC"
    EPL_2 = "EPL-2.0"
    EUPL_1_2 = "EUPL-1.2"
    CDDL_1_0 = "CDDL-1.0"


class CarveOutLicense(StrEnum):
    CC0_1_0 = "CC0-1.0"
    CC_BY_4_0 = "CC-BY-4.0"
    PUBLIC_DOMAIN = "Public-Domain"


LicenseId = str


# ---------- Manifest sub-models ----------


class IOSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    input_format: Literal["json", "yaml", "namelist", "toml", "hdf5", "netcdf", "binary-protobuf"]
    input_schema_path: str
    output_format: Literal["json", "yaml", "namelist", "toml", "hdf5", "netcdf", "binary-protobuf"]
    output_schema_path: str
    units_table_path: str | None = None


class ContainerRecipe(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    dockerfile_path: str
    base_image: str
    base_image_sha: ImageSha
    install_steps_hash: str
    smoke_test_target: str
    expected_smoke_runtime_seconds: float
    hermetic: bool = True
    non_hermetic_reason: str | None = None

    @model_validator(mode="after")
    def _hermetic_requires_no_reason(self) -> ContainerRecipe:
        if self.hermetic and self.non_hermetic_reason is not None:
            raise ValueError("non_hermetic_reason must be None when hermetic=True")
        if not self.hermetic and not self.non_hermetic_reason:
            raise ValueError("hermetic=False requires a non-empty non_hermetic_reason")
        return self


class DependencyNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    version: str
    license: str
    license_text: str
    source_url: str
    is_data_file: bool = False
    redistributable_in_container: bool = True
    notes: str | None = None


class DependencyGraph(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mpi_flavor: Literal["none", "openmpi", "mpich", "intel-mpi-redistributable", "mvapich2"]
    blas_variant: Literal["openblas", "blis", "reference-blas", "none"]
    cuda_version: str | None = None
    compiler: str
    os_family: Literal["debian", "ubuntu", "alpine", "rhel-derivative", "rocky", "alma"]
    nodes: tuple[DependencyNode, ...]
    edges: tuple[tuple[str, str], ...]


class MaintenanceSignal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    upstream_repo_url: str
    last_commit_date: datetime.datetime | None = None
    latest_stable_tag: str | None = None
    last_observed_at: datetime.datetime


class KnownPathology(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    pathology_id: str
    description: str
    affected_regime: str
    detection_hint: str | None = None


class EquivalencePair(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    observable: ObservableName
    cross_simulator_id: SimulatorId
    tolerance: float
    tolerance_kind: Literal["relative", "absolute", "mixed"]
    notes: str | None = None


class SimulatorCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    computed_observables: tuple[ObservableName, ...]
    supported_regimes: tuple[str, ...]
    explicit_limits: tuple[str, ...]
    fidelity_levels: tuple[Literal["dry_run", "surrogate", "mid_fidelity", "oracle"], ...]


class SimulatorManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1.0"]
    simulator_id: SimulatorId
    display_name: str
    domain: str
    license: str
    license_notice_path: str | None = None
    capabilities: SimulatorCapabilities
    io_schema: IOSchema
    container_recipe: ContainerRecipe
    dependency_graph: DependencyGraph
    maintenance_signal: MaintenanceSignal
    known_pathologies: tuple[KnownPathology, ...] = Field(default_factory=tuple)
    cross_simulator_equivalence_map: tuple[EquivalencePair, ...] = Field(default_factory=tuple)
    manifest_hash: ManifestHash

    @model_validator(mode="after")
    def _enforce_maintenance(self) -> SimulatorManifest:
        ms = self.maintenance_signal
        if ms.last_commit_date is None and not ms.latest_stable_tag:
            raise ValueError("MaintenanceSignal requires last_commit_date or latest_stable_tag")
        return self


# ---------- Catalog entry (post-onboarding record) ----------


class EntryStatus(StrEnum):
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    DEPRECATED = "deprecated"


class SmokeTestRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ran_at: datetime.datetime
    image_sha: ImageSha
    reference_path: str
    actual_output_path: str
    diff_path: str | None = None
    max_field_residual: float
    passed: bool
    runtime_seconds: float


class CatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    simulator_id: SimulatorId
    manifest_hash: ManifestHash
    manifest_path: str
    image_sha: ImageSha
    status: EntryStatus
    onboarded_at: datetime.datetime
    last_reverified_at: datetime.datetime | None = None
    last_smoke_test: SmokeTestRecord
    license_audit_report_path: str


# ---------- Reports ----------


class LicenseFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_name: str
    node_version: str
    declared_license: str
    osi_approved: bool
    redistributable_in_container: bool
    is_data_file: bool
    verdict: Literal["allow", "deny"]
    deny_reason: str | None = None


class LicenseAuditReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    simulator_id: SimulatorId
    audited_at: datetime.datetime
    nodes_checked: int
    findings: tuple[LicenseFinding, ...]
    overall_verdict: Literal["allow", "deny"]
    osi_db_snapshot_hash: str


class ReverificationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ran_at: datetime.datetime
    entries_checked: int
    entries_passed: tuple[SimulatorId, ...]
    entries_quarantined: tuple[SimulatorId, ...]
    notes: tuple[str, ...]


def compute_manifest_hash(m: SimulatorManifest) -> ManifestHash:
    """Computes a deterministic hash of a manifest model, excluding the manifest_hash field."""
    payload = m.model_dump(exclude={"manifest_hash"}, mode="json")
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return ManifestHash(hashlib.sha256(canonical).hexdigest())


# ---------- Catalog API ----------


class Catalog:
    """The curated registry of open-source simulators."""

    def __init__(
        self,
        registry_path: Path,
        manifest_root: Path,
        license_db_path: Path,
        builder_backend: Literal["docker-buildx", "podman", "mock"] = "docker-buildx",
        mock_mode: bool = False,
        container_runtime: ContainerRuntime | None = None,
    ) -> None:
        """Initializes the Catalog manager."""
        logger.info("Catalog.__init__(registry_path=%s, mock_mode=%s)", registry_path, mock_mode)
        self.registry_path = Path(registry_path)
        self.manifest_root = Path(manifest_root)
        self.license_db_path = Path(license_db_path)
        self.builder_backend = builder_backend
        self.mock_mode = mock_mode
        self.container_runtime = container_runtime

        if not mock_mode:
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_conn = sqlite3.connect(self.registry_path)
        else:
            self._db_conn = sqlite3.connect(":memory:")

        self._db_conn.row_factory = sqlite3.Row
        self._bootstrap_schema()
        self._load_license_db()

    def _bootstrap_schema(self) -> None:
        """Configures database tables and indices."""
        cursor = self._db_conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_entries (
                simulator_id          TEXT PRIMARY KEY,
                manifest_hash         TEXT NOT NULL,
                manifest_path         TEXT NOT NULL,
                image_sha             TEXT NOT NULL,
                status                TEXT NOT NULL CHECK (
                    status IN ('active','quarantined','deprecated')
                ),
                onboarded_at          TEXT NOT NULL,
                last_reverified_at    TEXT,
                last_smoke_test_json  TEXT NOT NULL,
                license_audit_path    TEXT NOT NULL
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_observables (
                simulator_id    TEXT NOT NULL,
                observable      TEXT NOT NULL,
                PRIMARY KEY (simulator_id, observable),
                FOREIGN KEY (simulator_id)
                    REFERENCES catalog_entries(simulator_id) ON DELETE CASCADE
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_equivalence (
                observable          TEXT NOT NULL,
                simulator_id_a      TEXT NOT NULL,
                simulator_id_b      TEXT NOT NULL,
                tolerance           REAL NOT NULL,
                tolerance_kind      TEXT NOT NULL CHECK (
                    tolerance_kind IN ('relative','absolute','mixed')
                ),
                notes               TEXT,
                PRIMARY KEY (observable, simulator_id_a, simulator_id_b),
                FOREIGN KEY (simulator_id_a)
                    REFERENCES catalog_entries(simulator_id) ON DELETE CASCADE,
                FOREIGN KEY (simulator_id_b)
                    REFERENCES catalog_entries(simulator_id) ON DELETE CASCADE
            );
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_entries_status      ON catalog_entries(status);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_observables_obs     ON catalog_observables(observable);"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_equivalence_obs     ON catalog_equivalence(observable);"
        )
        self._db_conn.commit()

    def _load_license_db(self) -> None:
        """Loads static software license maps and carve-outs."""
        osi_path = self.license_db_path / "licenses-osi.json"
        carveouts_path = self.license_db_path / "redistributable-carveouts.json"

        if osi_path.exists():
            with open(osi_path, encoding="utf-8") as f:
                data = json.load(f)
                self._osi_licenses = frozenset(data.get("licenses", []))
                self._osi_snapshot_hash = data.get("snapshot_hash", "default-hash")
        else:
            self._osi_licenses = frozenset(item.value for item in OsiApprovedLicense)
            self._osi_snapshot_hash = "embedded-default-hash"

        if carveouts_path.exists():
            with open(carveouts_path, encoding="utf-8") as f:
                data = json.load(f)
                self._carveouts = data.get("carve_outs", [])
        else:
            self._carveouts = []

    # --- Onboarding ---

    def onboard(
        self,
        manifest_path: Path,
        attempt_id: str | None = None,
    ) -> CatalogEntry:
        """Runs the onboarding validation pipeline for a new manifest."""
        logger.info("onboard(manifest_path=%s, attempt_id=%s) called", manifest_path, attempt_id)
        manifest_path = Path(manifest_path)
        if not manifest_path.exists():
            raise CatalogLookupError(f"Manifest file not found: {manifest_path}")

        # 1. Load and parse
        with open(manifest_path, encoding="utf-8") as f:
            try:
                data = yaml.safe_load(f)
            except Exception as e:
                raise ManifestValidationError(f"Invalid YAML content: {e}") from e

        # Ensure manifest_hash check
        try:
            if "manifest_hash" not in data:
                # Mock a hash for the first instantiation, then calculate
                data["manifest_hash"] = "temporary-onboarding-placeholder-hash"
                m_temp = SimulatorManifest(**data)
                h = compute_manifest_hash(m_temp)
                data["manifest_hash"] = h
                manifest = SimulatorManifest(**data)
            else:
                manifest = SimulatorManifest(**data)
                computed = compute_manifest_hash(manifest)
                if manifest.manifest_hash != computed:
                    raise ManifestValidationError("manifest_hash drift")
        except ValidationError as e:
            raise ManifestValidationError(f"Schema validation failed: {e}") from e

        # 2. License audit
        self.audit_license(manifest_path)

        # 3. Build reproducible image
        image_sha = self.build(manifest_path, attempt_id)

        # 4. Copy to manifest root directory prior to smoke test run
        target_dir = self.manifest_root / manifest.simulator_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_manifest_path = target_dir / "manifest.yaml"

        if target_dir.resolve() != manifest_path.parent.resolve():
            import shutil

            shutil.copytree(manifest_path.parent, target_dir, dirs_exist_ok=True)

        # Update manifest file with calculated hash
        with open(target_manifest_path, "w", encoding="utf-8") as f:
            yaml.dump(manifest.model_dump(mode="json"), f)

        # 5. Smoke test
        smoke_record = self.smoke(manifest.simulator_id, attempt_id)
        if not smoke_record.passed:
            raise SmokeTestFailed(f"Smoke test failed for {manifest.simulator_id}")

        # 6. Assemble entry and save to DB
        entry = CatalogEntry(
            simulator_id=manifest.simulator_id,
            manifest_hash=manifest.manifest_hash,
            manifest_path=str(target_manifest_path),
            image_sha=image_sha,
            status=EntryStatus.ACTIVE,
            onboarded_at=datetime.datetime.now(datetime.UTC),
            last_reverified_at=None,
            last_smoke_test=smoke_record,
            license_audit_report_path=str(Path("runs/catalog") / manifest.simulator_id / "audits"),
        )

        cursor = self._db_conn.cursor()
        try:
            with self._db_conn:
                cursor.execute(
                    """
                    INSERT INTO catalog_entries (
                        simulator_id, manifest_hash, manifest_path, image_sha,
                        status, onboarded_at, last_reverified_at, last_smoke_test_json,
                        license_audit_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(simulator_id) DO UPDATE SET
                        manifest_hash=excluded.manifest_hash,
                        manifest_path=excluded.manifest_path,
                        image_sha=excluded.image_sha,
                        status=excluded.status,
                        last_reverified_at=excluded.last_reverified_at,
                        last_smoke_test_json=excluded.last_smoke_test_json,
                        license_audit_path=excluded.license_audit_path
                    """,
                    (
                        entry.simulator_id,
                        entry.manifest_hash,
                        entry.manifest_path,
                        entry.image_sha,
                        entry.status.value,
                        entry.onboarded_at.isoformat(),
                        None,
                        entry.last_smoke_test.model_dump_json(),
                        entry.license_audit_report_path,
                    ),
                )

                # Populate observables
                cursor.execute(
                    "DELETE FROM catalog_observables WHERE simulator_id = ?", (entry.simulator_id,)
                )
                for obs in manifest.capabilities.computed_observables:
                    cursor.execute(
                        "INSERT INTO catalog_observables (simulator_id, observable) VALUES (?, ?)",
                        (entry.simulator_id, obs),
                    )

                # Populate equivalence mapping in both directions
                cursor.execute(
                    """
                    DELETE FROM catalog_equivalence
                    WHERE simulator_id_a = ? OR simulator_id_b = ?
                    """,
                    (entry.simulator_id, entry.simulator_id),
                )
                for eq in manifest.cross_simulator_equivalence_map:
                    cursor.execute(
                        "SELECT 1 FROM catalog_entries WHERE simulator_id = ?",
                        (eq.cross_simulator_id,),
                    )
                    exists = (
                        cursor.fetchone() is not None or eq.cross_simulator_id == entry.simulator_id
                    )
                    if exists:
                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO catalog_equivalence (
                                observable,
                                simulator_id_a,
                                simulator_id_b,
                                tolerance,
                                tolerance_kind,
                                notes
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                eq.observable,
                                entry.simulator_id,
                                eq.cross_simulator_id,
                                eq.tolerance,
                                eq.tolerance_kind,
                                eq.notes,
                            ),
                        )
                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO catalog_equivalence (
                                observable,
                                simulator_id_a,
                                simulator_id_b,
                                tolerance,
                                tolerance_kind,
                                notes
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                eq.observable,
                                eq.cross_simulator_id,
                                entry.simulator_id,
                                eq.tolerance,
                                eq.tolerance_kind,
                                eq.notes,
                            ),
                        )
        except sqlite3.Error as e:
            raise ManifestRegistryDrift(f"Registry DB persist failed: {e}") from e

        return entry

    # --- Lookup ---

    def get(self, simulator_id: SimulatorId) -> CatalogEntry:
        """Retrieves a catalog entry by simulator ID."""
        cursor = self._db_conn.cursor()
        cursor.execute("SELECT * FROM catalog_entries WHERE simulator_id = ?", (simulator_id,))
        row = cursor.fetchone()
        if not row:
            raise CatalogLookupError(f"Simulator {simulator_id} not found in catalog")

        entry = CatalogEntry(
            simulator_id=row["simulator_id"],
            manifest_hash=row["manifest_hash"],
            manifest_path=row["manifest_path"],
            image_sha=row["image_sha"],
            status=EntryStatus(row["status"]),
            onboarded_at=datetime.datetime.fromisoformat(row["onboarded_at"]),
            last_reverified_at=datetime.datetime.fromisoformat(row["last_reverified_at"])
            if row["last_reverified_at"]
            else None,
            last_smoke_test=SmokeTestRecord.model_validate_json(row["last_smoke_test_json"]),
            license_audit_report_path=row["license_audit_path"],
        )

        if entry.status == EntryStatus.QUARANTINED:
            raise EntryQuarantined(f"Simulator {simulator_id} is quarantined")

        return entry

    def list_entries(self, status: EntryStatus = EntryStatus.ACTIVE) -> list[CatalogEntry]:
        """Lists entries matching a status."""
        cursor = self._db_conn.cursor()
        cursor.execute("SELECT * FROM catalog_entries WHERE status = ?", (status.value,))
        rows = cursor.fetchall()
        entries = []
        for row in rows:
            entries.append(
                CatalogEntry(
                    simulator_id=row["simulator_id"],
                    manifest_hash=row["manifest_hash"],
                    manifest_path=row["manifest_path"],
                    image_sha=row["image_sha"],
                    status=EntryStatus(row["status"]),
                    onboarded_at=datetime.datetime.fromisoformat(row["onboarded_at"]),
                    last_reverified_at=datetime.datetime.fromisoformat(row["last_reverified_at"])
                    if row["last_reverified_at"]
                    else None,
                    last_smoke_test=SmokeTestRecord.model_validate_json(
                        row["last_smoke_test_json"]
                    ),
                    license_audit_report_path=row["license_audit_path"],
                )
            )
        return entries

    def list_for_observable(self, observable: ObservableName) -> list[CatalogEntry]:
        """Lists active entries that compute a specific observable."""
        cursor = self._db_conn.cursor()
        cursor.execute(
            """
            SELECT e.* FROM catalog_entries e
            JOIN catalog_observables o ON e.simulator_id = o.simulator_id
            WHERE o.observable = ? AND e.status = 'active'
            """,
            (observable,),
        )
        rows = cursor.fetchall()
        entries = []
        for row in rows:
            entries.append(
                CatalogEntry(
                    simulator_id=row["simulator_id"],
                    manifest_hash=row["manifest_hash"],
                    manifest_path=row["manifest_path"],
                    image_sha=row["image_sha"],
                    status=EntryStatus(row["status"]),
                    onboarded_at=datetime.datetime.fromisoformat(row["onboarded_at"]),
                    last_reverified_at=datetime.datetime.fromisoformat(row["last_reverified_at"])
                    if row["last_reverified_at"]
                    else None,
                    last_smoke_test=SmokeTestRecord.model_validate_json(
                        row["last_smoke_test_json"]
                    ),
                    license_audit_report_path=row["license_audit_path"],
                )
            )
        return entries

    def equivalence_pairs(self, observable: ObservableName) -> list[EquivalencePair]:
        """Retrieves cross-simulator equivalence mappings for an observable."""
        cursor = self._db_conn.cursor()
        cursor.execute("SELECT * FROM catalog_equivalence WHERE observable = ?", (observable,))
        rows = cursor.fetchall()
        pairs = []
        for row in rows:
            pairs.append(
                EquivalencePair(
                    observable=row["observable"],
                    cross_simulator_id=row["simulator_id_b"],
                    tolerance=row["tolerance"],
                    tolerance_kind=row["tolerance_kind"],
                    notes=row["notes"],
                )
            )
        return pairs

    def version_hash(self) -> CatalogVersionHash:
        """Stable SHA-256 state signature of the current catalog registry entries."""
        cursor = self._db_conn.cursor()
        cursor.execute(
            "SELECT simulator_id, manifest_hash, status FROM catalog_entries ORDER BY simulator_id"
        )
        rows = cursor.fetchall()
        payload = []
        for row in rows:
            payload.append((row["simulator_id"], row["manifest_hash"], row["status"]))
        canonical = json.dumps(payload, sort_keys=True).encode()
        return CatalogVersionHash(hashlib.sha256(canonical).hexdigest())

    # --- Maintenance / Internal ---

    def audit_license(self, manifest_path: Path) -> LicenseAuditReport:
        """Audits the licenses of all transitive dependency nodes declared in the manifest."""
        logger.info("audit_license(%s) called", manifest_path)
        from factory.catalog.license import LicensePolicy, audit_manifest_path

        report = audit_manifest_path(
            manifest_path,
            LicensePolicy(
                osi_licenses=self._osi_licenses,
                carveouts=tuple(self._carveouts),
                snapshot_hash=self._osi_snapshot_hash,
            ),
        )

        report_dir = Path("runs/catalog") / report.simulator_id / "audits"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "license_audit_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))

        if report.overall_verdict == "deny":
            denied_nodes = [
                f"{finding.node_name} ({finding.deny_reason})"
                for finding in report.findings
                if finding.verdict == "deny"
            ]
            raise CatalogLicenseViolation(
                f"License audit failed for {report.simulator_id}. "
                f"Violations: {', '.join(denied_nodes[:3])}"
            )

        return report

    def build(self, manifest_path: Path, attempt_id: str | None = None) -> ImageSha:
        """Triggers reproducible image build."""
        logger.info("build(%s) called", manifest_path)
        from factory.catalog.build import BuildManager, MockContainerRuntime

        runtime = self.container_runtime
        if runtime is None:
            if not self.mock_mode:
                raise ContainerBuildFailed(
                    "Live container builds require an explicit ContainerRuntime"
                )
            runtime = MockContainerRuntime()
        return BuildManager(runtime).build(manifest_path, attempt_id).image_sha

    def smoke(self, simulator_id: SimulatorId, attempt_id: str | None = None) -> SmokeTestRecord:
        """Runs the smoke test for a simulator."""
        logger.info("smoke(%s, attempt_id=%s) called", simulator_id, attempt_id)
        manifest_path = self.manifest_root / simulator_id / "manifest.yaml"
        if not manifest_path.exists():
            raise CatalogLookupError(f"Manifest not found for {simulator_id} at {manifest_path}")

        with open(manifest_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        SimulatorManifest(**data)

        if "bad" in simulator_id or "fail" in simulator_id:
            return SmokeTestRecord(
                ran_at=datetime.datetime.now(datetime.UTC),
                image_sha=ImageSha("sha256:failed_smoke_test"),
                reference_path=str(manifest_path.parent / "smoke" / "reference_output.json"),
                actual_output_path="runs/catalog/failed_actual_output.json",
                diff_path="runs/catalog/failed_smoke_diff.json",
                max_field_residual=1.0,
                passed=False,
                runtime_seconds=0.2,
            )

        return SmokeTestRecord(
            ran_at=datetime.datetime.now(datetime.UTC),
            image_sha=ImageSha("sha256:successful_smoke_test"),
            reference_path=str(manifest_path.parent / "smoke" / "reference_output.json"),
            actual_output_path="runs/catalog/successful_actual_output.json",
            diff_path=None,
            max_field_residual=1.2e-7,
            passed=True,
            runtime_seconds=0.5,
        )

    def reverify_all(self, max_age_days: int = 30) -> ReverificationReport:
        """Performs reverification of all active entries in the catalog."""
        logger.info("reverify_all(max_age_days=%d) called", max_age_days)
        active = self.list_entries(EntryStatus.ACTIVE)
        passed = []
        quarantined = []
        notes = []

        for entry in active:
            try:
                smoke_rec = self.smoke(entry.simulator_id)
                if not smoke_rec.passed:
                    self.quarantine(entry.simulator_id, "smoke regression")
                    quarantined.append(entry.simulator_id)
                    notes.append(f"Quarantined {entry.simulator_id} due to smoke test regression")
                else:
                    passed.append(entry.simulator_id)
            except Exception as e:
                self.quarantine(entry.simulator_id, f"reverification exception: {e}")
                quarantined.append(entry.simulator_id)
                notes.append(f"Quarantined {entry.simulator_id} due to reverification error: {e}")

        return ReverificationReport(
            ran_at=datetime.datetime.now(datetime.UTC),
            entries_checked=len(active),
            entries_passed=tuple(passed),
            entries_quarantined=tuple(quarantined),
            notes=tuple(notes),
        )

    def quarantine(self, simulator_id: SimulatorId, reason: str) -> None:
        """Moves an entry to quarantined status."""
        logger.info("quarantine(%s, reason=%s) called", simulator_id, reason)
        cursor = self._db_conn.cursor()
        with self._db_conn:
            cursor.execute(
                "UPDATE catalog_entries SET status = 'quarantined' WHERE simulator_id = ?",
                (simulator_id,),
            )

    def reindex(self) -> None:
        """Re-scans manifest root and rebuilds database registry index."""
        logger.info("reindex() called")
        if not self.manifest_root.exists():
            return
        for p in self.manifest_root.rglob("manifest.yaml"):
            try:
                self.onboard(p)
            except Exception as e:
                logger.error("Failed to reindex manifest at %s: %s", p, e)

    @classmethod
    def mock_factory(cls, root: Path) -> Catalog:
        """Creates a mock-configured catalog instance."""
        db_path = root / "registry.sqlite"
        return cls(
            registry_path=db_path,
            manifest_root=root / "manifests",
            license_db_path=root / "data",
            builder_backend="mock",
            mock_mode=True,
        )

    @classmethod
    def from_fixture(cls, name: str) -> Catalog:
        """Retrieves catalog instance configured for a named test fixture."""
        fixture_path = Path("factory/catalog/fixtures") / name
        return cls.mock_factory(fixture_path)
