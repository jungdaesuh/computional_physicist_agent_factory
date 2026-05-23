# Spec 004: Simulator Catalog

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- The **Simulator Catalog** is the curated registry of open-source simulators the factory is allowed to drive. Every `ExperimentSpec.simulator_id` resolves to exactly one entry here; nothing is simulated outside the Catalog. It owns the manifest schema, the license auditor, the reproducible container build harness, the smoke-test runner, and the on-disk registry.
- The 5 facts: (1) a Catalog entry is a Pydantic **configuration** model — distinct from the eight typed cycle artifacts in spec 002, but carries the same content-hash discipline; (2) a manifest is **the source of truth** — the registry is a materialized index over manifests, never the other way around; (3) **license auditing is mandatory** and walks the entire transitive dependency graph; "free for academic use" is a hard fail; (4) every entry must build a reproducible OCI image from scratch and pass a deterministic **smoke test** against a known-good reference; (5) growth is human-curated in Phase A, human-approved in Phase B, autonomous in Phase C (deferred research).
- Open first: `factory/catalog/api.py` (manifest schema + onboarding orchestrator), then `factory/catalog/tests/test_catalog_typical_usage.py`.

## ENTRY POINTS
- Main module: `factory/catalog/api.py`
- Typical-usage test: `factory/catalog/tests/test_catalog_typical_usage.py`
- CLI: `python -m factory.catalog --help` (subcommands: `onboard`, `audit-license`, `build`, `smoke`, `list`, `show`, `equivalence-map`, `quarantine`)
- Mock-mode example: `python -m factory.catalog onboard factory/catalog/fixtures/manifests/mock_solver_a.yaml --mock-mode`
- Runbook: `docs/runbooks/catalog-onboarding.md`

## LOCAL DEBUG
- Instantiate without a container runtime: `Catalog(registry_path=tmp, mock_mode=True).onboard(manifest)` runs validation + license audit against the fixture SBOMs in `factory/catalog/fixtures/sbom/` and never invokes Docker.
- Live mode requires: a working OCI builder (`docker buildx` or `podman build`), network egress for package mirrors *only at build time* (not at runtime), and the dependency-license database snapshot under `factory/catalog/data/licenses-osi.json`.
- Common error signatures → recovery:
  - `ManifestValidationError` → schema violation; run `python -m factory.catalog show --manifest <path>` to inspect, fix the YAML, re-onboard.
  - `CatalogLicenseViolation` → a transitive dep is non-OSI or non-redistributable; the offending dep is listed in the error; either remove it from the recipe or refuse the entry.
  - `ContainerBuildFailed` → image build returned non-zero; the build log is preserved under `runs/catalog/<entry-id>/<attempt>/build.log`; do **not** auto-retry without a Dockerfile change.
  - `SmokeTestFailed` → image built but reference output diverged beyond tolerance; the diff is preserved under `runs/catalog/<entry-id>/<attempt>/smoke.diff.json`; either tighten the recipe or widen the tolerance with rationale.
  - `EntryQuarantined` → an existing entry's smoke test stopped passing on the periodic re-check; the entry is moved to `quarantined` status and the Selector will not return it.
  - `ManifestRegistryDrift` → the registry index disagrees with manifest files on disk; run `python -m factory.catalog list --reindex` to rebuild the index from manifests (manifests win).
- Logs to inspect: every catalog operation writes a JSONL event stream to `runs/catalog/<entry-id>/<attempt>/events.jsonl`. Filter the cycle log via `module=catalog`.

## DEPENDENCIES
- **Hard:** Spec 002 (artifacts) — re-uses `ArtifactHash`, `FactoryError`, and the canonical-JSON hashing approach. The Catalog manifest itself is *not* one of the eight cycle artifacts (§4 below explains the distinction).
- **Soft:** Spec 014 (telemetry) — emits structured events if available, otherwise writes only to the local JSONL stream. Spec 013 (budget) — long container builds report cost if a budget context is provided.
- **Mocks available:** `Catalog.mock_factory()` returns a Catalog wired to fixture SBOMs and a fake OCI builder that returns deterministic image SHAs and pre-recorded smoke-test outputs. `factory/catalog/fixtures/manifests/` ships three mock manifests: `mock_solver_a.yaml` (passes), `mock_solver_b.yaml` (passes; cross-validatable with A for the `mean_observable` field), and `mock_solver_bad_license.yaml` (fails the license auditor).

---

## 1. Summary

This module owns everything between "a human-written manifest of an open-source simulator" and "a vetted, reproducible, smoke-tested catalog entry the rest of the factory may rely on." It defines the manifest schema, runs the license auditor, builds the OCI image deterministically, runs the smoke test inside the image, persists the entry to a content-addressed registry, and answers lookup queries from the Selector (spec 005), the Domain Adapter (spec 006), and the Generator-Verifier loop (spec 008).

The Catalog is the **substrate boundary** of the factory. The factory's intent is "any open-source simulator," but its realised capability is bounded by what the Catalog has audited and built. Honest framing of that asymmetry is enforced here: out-of-Catalog hypotheses fail at gate G1.5, not silently in the loop.

## 2. Scope

**In scope:**
- Pydantic `SimulatorManifest` model covering license, domain, capabilities, I/O schema, container recipe, dependency graph, maintenance signal, known pathologies, and the cross-simulator equivalence map.
- YAML loader / writer for manifests with `extra="forbid"` strictness.
- License auditor: traverses the *transitive* runtime + build dependency graph; checks each dep's SPDX ID against the `OsiApprovedLicense` enum + a `CarveOutLicense` allowlist for data/asset files only; **independently** phrase-scans the verbatim LICENSE-file text (carried on every `DependencyNode`) for "academic use only", "non-commercial", and similar rider clauses; fails loud on academic-only / registration-gated / non-redistributable artifacts (including data files such as gated DFT pseudopotentials).
- Reproducible container build harness: pinned base-image SHA, pinned install steps, hermetic build context by default with an opt-out for documented non-hermetic dependencies (e.g., GPU runtime libraries, in-build git submodules, conda envs), deterministic image SHA capture, build log capture.
- Smoke-test runner: executes a manifest-declared known-good problem inside the freshly built image and compares numeric output to a pinned reference with a per-field tolerance schema.
- Catalog registry: SQLite database serving as a materialized index over the on-disk manifest files (`runs/catalog/registry.sqlite`).
- `Catalog.onboard(manifest)` orchestrator: validate → license-audit → build → smoke → persist (or quarantine + report).
- Cross-simulator equivalence map: per-observable mapping of which entries can be cross-validated against which other entries; consumed by the G4 validation portfolio.
- Periodic re-verification (`Catalog.reverify_all()`): re-runs smoke tests and re-checks license database freshness; quarantines drifting entries.
- CLI subcommands: `onboard`, `audit-license`, `build`, `smoke`, `list`, `show`, `equivalence-map`, `quarantine`.
- Mock mode and live mode both implemented behind the same public API.

**Out of scope:**
- Simulator *selection* given a `HypothesisSpec` — that's the Selector (spec 005).
- Per-simulator input translation — that's the Domain Adapter (spec 006).
- Running production simulations on Catalog entries — that's the Generator-Verifier loop (spec 008) and the validation portfolio (spec 009).
- Autonomous discovery and proposal of new candidate simulators from upstream documentation — that is Phase C and is deferred.
- Cross-language manifest tooling (e.g., R / Julia simulator wrappers). The harness is OCI-image agnostic w.r.t. the in-container language, but the manifest schema in this spec targets simulators we can drive from Python; multi-language adapters belong to spec 006.
- The Selector's compatibility scoring (spec 005). This module exposes lookup primitives only.

## 3. Public Interface

```python
# factory/catalog/api.py

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal, Mapping, NewType, Sequence
from pydantic import BaseModel, Field, ConfigDict, model_validator

from factory.artifacts import ArtifactHash, FactoryError


# ---------- Type aliases ----------

SimulatorId = NewType("SimulatorId", str)            # e.g. "stellarator-mhd-osi-a"
ManifestHash = NewType("ManifestHash", str)          # SHA-256 of canonical YAML payload
ImageSha = NewType("ImageSha", str)                  # OCI image digest, e.g. "sha256:abcd..."
ObservableName = NewType("ObservableName", str)      # e.g. "mean_observable", "vacuum_well"
CatalogVersionHash = NewType("CatalogVersionHash", str)  # SHA-256 content hash of catalog state


# ---------- Errors ----------

class CatalogError(FactoryError): ...
class ManifestValidationError(CatalogError): ...
class CatalogLicenseViolation(CatalogError): ...
class ContainerBuildFailed(CatalogError): ...
class SmokeTestFailed(CatalogError): ...
class EntryQuarantined(CatalogError): ...
class ManifestRegistryDrift(CatalogError): ...
class CatalogLookupError(CatalogError): ...


# ---------- License enums (OSI-approved vs. data/asset carve-outs) ----------

class OsiApprovedLicense(str, Enum):
    """OSI-approved software licenses only. Verified at https://opensource.org/licenses.
    Use for code dependencies in the transitive dependency graph."""
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


class CarveOutLicense(str, Enum):
    """Allowed for data/asset files only, NEVER for code dependencies.
    Covers lookup tables, basis sets, pseudopotentials, reference benchmarks, etc."""
    CC0_1_0 = "CC0-1.0"
    CC_BY_4_0 = "CC-BY-4.0"
    PUBLIC_DOMAIN = "Public-Domain"


LicenseId = OsiApprovedLicense | CarveOutLicense


# ---------- Manifest sub-models ----------

class IOSchema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    input_format: Literal["json", "yaml", "namelist", "toml", "hdf5", "netcdf", "binary-protobuf"]
    input_schema_path: str          # e.g. "schemas/input.schema.json" relative to manifest dir
    output_format: Literal["json", "yaml", "namelist", "toml", "hdf5", "netcdf", "binary-protobuf"]
    output_schema_path: str
    units_table_path: str | None    # optional units mapping for cross-simulator comparison


class ContainerRecipe(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    dockerfile_path: str            # path relative to manifest dir
    base_image: str                 # e.g. "docker.io/library/debian"
    base_image_sha: ImageSha        # pinned digest, e.g. "sha256:..."
    install_steps_hash: str         # SHA-256 of the canonicalized RUN steps; redundant integrity check
    smoke_test_target: str          # path inside the image to the smoke-test entry point
    expected_smoke_runtime_seconds: float
    hermetic: bool = True
    # --network=none is the default. Some simulators cannot be built or run hermetically:
    #   - git submodules fetched during compile (build-time network)
    #   - GPU runtime libraries linked from host-mounted vendor drivers
    #   - conda envs that resolve packages at first invocation
    # Manifest authors may set hermetic=false with an explanatory non_hermetic_reason.
    # Smoke-test runner then permits --network=host with a telemetry warning emitted
    # under factory.catalog.smoke_non_hermetic (see §5.4).
    non_hermetic_reason: str | None = None

    @model_validator(mode="after")
    def _hermetic_requires_no_reason(self) -> "ContainerRecipe":
        if self.hermetic and self.non_hermetic_reason is not None:
            raise ValueError("non_hermetic_reason must be None when hermetic=True")
        if not self.hermetic and not self.non_hermetic_reason:
            raise ValueError("hermetic=False requires a non-empty non_hermetic_reason")
        return self


class DependencyNode(BaseModel):
    """One transitive dep in the resolved dependency graph."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str                       # e.g. "openmpi", "openblas", "h5py"
    version: str                    # pinned, exact
    license: LicenseId | str        # SPDX ID; str escape allowed only via the carve-out audit
    license_text: str               # RAW LICENSE-file contents bundled with the dep — REQUIRED.
                                    # The auditor's phrase-scan (§5.2 step 3d) runs on THIS field,
                                    # not on the SPDX ID. Manifest authors paste the verbatim LICENSE
                                    # file the upstream artifact ships; empty strings reject.
    source_url: str                 # URL where the dep was obtained
    is_data_file: bool = False      # True for pseudopotentials, basis sets, lookup tables
    redistributable_in_container: bool = True
    notes: str | None = None        # human-readable rationale, esp. for carve-outs


class DependencyGraph(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mpi_flavor: Literal["none", "openmpi", "mpich", "intel-mpi-redistributable", "mvapich2"]
    blas_variant: Literal["openblas", "blis", "reference-blas", "none"]
    cuda_version: str | None        # e.g. "12.4"; None for CPU-only
    compiler: str                   # e.g. "gcc-13.2", "clang-17"
    os_family: Literal["debian", "ubuntu", "alpine", "rhel-derivative", "rocky", "alma"]
    nodes: list[DependencyNode]     # the full transitive graph (build + runtime)
    edges: list[tuple[str, str]]    # parent_name -> child_name pairs (informational, not validated structurally)


class MaintenanceSignal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    upstream_repo_url: str
    last_commit_date: datetime | None
    latest_stable_tag: str | None
    last_observed_at: datetime      # when the factory last checked
    # At least one of last_commit_date (≤24 months) OR latest_stable_tag must be present.


class KnownPathology(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    pathology_id: str               # e.g. "stellarator-rational-surface-stall"
    description: str
    affected_regime: str            # e.g. "iota near rational values"
    detection_hint: str | None      # heuristic the Selector / Adapter can use to flag in advance


class EquivalencePair(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    observable: ObservableName
    cross_simulator_id: SimulatorId
    tolerance: float                # relative tolerance for the G4 cross-simulator check
    tolerance_kind: Literal["relative", "absolute", "mixed"]
    notes: str | None = None


class SimulatorCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    computed_observables: list[ObservableName]
    supported_regimes: list[str]    # human-readable regime labels (e.g. "vacuum", "finite-beta")
    explicit_limits: list[str]      # things the simulator MUST NOT be asked to do
    fidelity_levels: list[Literal["dry_run", "surrogate", "mid_fidelity", "oracle"]]


class SimulatorManifest(BaseModel):
    """Configuration schema for a single Catalog entry. NOT a cycle artifact."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"]
    simulator_id: SimulatorId
    display_name: str
    domain: str                            # canonical domain label, e.g. "stellarator-mhd"
    license: LicenseId
    license_notice_path: str | None        # path to LICENSE / NOTICE files
    capabilities: SimulatorCapabilities
    io_schema: IOSchema
    container_recipe: ContainerRecipe
    dependency_graph: DependencyGraph
    maintenance_signal: MaintenanceSignal
    known_pathologies: list[KnownPathology] = Field(default_factory=list)
    cross_simulator_equivalence_map: list[EquivalencePair] = Field(default_factory=list)
    manifest_hash: ManifestHash             # computed at load; verified on read-back

    @model_validator(mode="after")
    def _enforce_maintenance(self) -> "SimulatorManifest":
        ms = self.maintenance_signal
        if ms.last_commit_date is None and not ms.latest_stable_tag:
            raise ValueError("MaintenanceSignal requires last_commit_date or latest_stable_tag")
        return self


# ---------- Catalog entry (post-onboarding record) ----------

class EntryStatus(str, Enum):
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    DEPRECATED = "deprecated"


class SmokeTestRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ran_at: datetime
    image_sha: ImageSha
    reference_path: str
    actual_output_path: str
    diff_path: str | None
    max_field_residual: float
    passed: bool
    runtime_seconds: float


class CatalogEntry(BaseModel):
    """Persisted index row, materialized from the manifest after a successful onboarding."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    simulator_id: SimulatorId
    manifest_hash: ManifestHash
    manifest_path: str                       # absolute or repo-relative
    image_sha: ImageSha
    status: EntryStatus
    onboarded_at: datetime
    last_reverified_at: datetime | None
    last_smoke_test: SmokeTestRecord
    license_audit_report_path: str           # JSONL artifact with the full dep audit


# ---------- Catalog API ----------

class Catalog:
    """The curated registry of open-source simulators."""

    def __init__(
        self,
        registry_path: Path,                  # e.g. runs/catalog/registry.sqlite
        manifest_root: Path,                  # directory tree holding manifests + Dockerfiles
        license_db_path: Path,                # static OSI snapshot under factory/catalog/data/
        builder_backend: Literal["docker-buildx", "podman", "mock"] = "docker-buildx",
        mock_mode: bool = False,
    ) -> None: ...

    # --- Onboarding ---

    def onboard(
        self,
        manifest_path: Path,
        attempt_id: str | None = None,        # auto-generated if None
    ) -> CatalogEntry:
        """Run the full validate → license-audit → build → smoke → persist pipeline.
        Raises one of ManifestValidationError / CatalogLicenseViolation /
        ContainerBuildFailed / SmokeTestFailed before persistence."""

    # --- Lookup ---

    def get(self, simulator_id: SimulatorId) -> CatalogEntry: ...
    def list_entries(self, status: EntryStatus = EntryStatus.ACTIVE) -> list[CatalogEntry]: ...
    def list_for_observable(self, observable: ObservableName) -> list[CatalogEntry]: ...
    def equivalence_pairs(self, observable: ObservableName) -> list[EquivalencePair]:
        """All (simulator_id_a, simulator_id_b, tolerance) pairs that can validate observable."""

    def version_hash(self) -> CatalogVersionHash:
        """SHA-256 content hash of catalog state (sorted simulator_id+manifest_hash+status tuples).
        Stable across processes; consumed by spec 011 RAG writer + spec 014 telemetry for
        cross-cycle catalog-state pinning."""

    # --- Maintenance ---

    def audit_license(self, manifest_path: Path) -> "LicenseAuditReport": ...
    def build(self, manifest_path: Path, attempt_id: str | None = None) -> ImageSha: ...
    def smoke(self, simulator_id: SimulatorId, attempt_id: str | None = None) -> SmokeTestRecord: ...
    def reverify_all(self, max_age_days: int = 30) -> "ReverificationReport": ...
    def quarantine(self, simulator_id: SimulatorId, reason: str) -> None: ...
    def reindex(self) -> None:
        """Drop and rebuild the SQLite index from the manifests on disk."""

    @classmethod
    def mock_factory(cls, root: Path) -> "Catalog": ...

    @classmethod
    def from_fixture(cls, name: str) -> "Catalog":
        """Alias for mock_factory keyed by a named fixture under
        factory/catalog/fixtures/. Loads the matching manifest tree and SBOM set.
        Equivalent to mock_factory(Path('factory/catalog/fixtures') / name)."""


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
    audited_at: datetime
    nodes_checked: int
    findings: list[LicenseFinding]
    overall_verdict: Literal["allow", "deny"]
    osi_db_snapshot_hash: str


class ReverificationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ran_at: datetime
    entries_checked: int
    entries_passed: list[SimulatorId]
    entries_quarantined: list[SimulatorId]
    notes: list[str]
```

The Selector (spec 005), Adapter (spec 006), and Generator-Verifier (spec 008) **only** import from `factory.catalog` (resolving through `__init__.py`); they never reach into internal files.

## 4. Data Structures / Schemas

### 4.1 Manifests are configuration, not cycle artifacts

The eight typed artifacts in spec 002 (`GapCandidate`, `HypothesisSpec`, etc.) describe *one-shot* state produced by a cycle. They are immutable, content-addressed, and consumed strictly downstream.

The `SimulatorManifest` is *static configuration*: it lives at rest in version control under `factory/catalog/manifests/<simulator-id>/manifest.yaml`, is versioned by a human-curated process, and is referenced from cycle artifacts by `simulator_id` (a string lookup key), not by content hash. This is the same distinction Python's `pyproject.toml` has versus, e.g., a build output.

Two consequences:

1. **Manifests do not inherit from `_ArtifactBase` (spec 002).** They reuse the canonical-JSON hashing approach for tamper-detection (`manifest_hash`), but they live outside the `runs/<cycle-id>/artifacts/` tree and outside the cycle's `MANIFEST.json`. A manifest's hash is computed against its canonical-YAML serialization with the `manifest_hash` field excluded.
2. **Cycle artifacts reference manifests by `simulator_id`, plus the manifest's content hash captured at experiment-spec time.** `ExperimentSpec.simulator_id` is the string; the Catalog also persists the manifest hash and the image SHA into the cycle's provenance block (spec 002 `ProvenanceBlock`) when the experiment runs, so the historical record knows which manifest version was used.

Within this module the distinction is enforced by mypy types (`SimulatorManifest` and `_ArtifactBase` are unrelated classes) and by the registry layout below.

### 4.2 On-disk layout

```
factory/catalog/
├── api.py
├── cli.py
├── mock.py
├── errors.py
├── manifests/                              # source of truth
│   └── <simulator-id>/
│       ├── manifest.yaml                   # SimulatorManifest serialization
│       ├── Dockerfile                      # ContainerRecipe.dockerfile_path
│       ├── schemas/
│       │   ├── input.schema.json
│       │   └── output.schema.json
│       ├── smoke/
│       │   ├── input.<ext>
│       │   ├── reference_output.<ext>
│       │   └── tolerance.yaml
│       ├── LICENSE
│       └── NOTICE
├── data/
│   ├── licenses-osi.json                   # static snapshot of OSI-approved SPDX list
│   └── redistributable-carveouts.json      # explicit per-package exceptions, e.g. CC-BY-4 data
├── fixtures/
│   ├── manifests/
│   │   ├── mock_solver_a.yaml
│   │   ├── mock_solver_b.yaml
│   │   └── mock_solver_bad_license.yaml
│   ├── sbom/
│   │   ├── mock_solver_a.sbom.json
│   │   ├── mock_solver_b.sbom.json
│   │   └── mock_solver_bad_license.sbom.json
│   └── smoke_outputs/
│       ├── mock_solver_a/...
│       └── mock_solver_b/...
└── tests/
    ├── test_catalog_typical_usage.py
    ├── test_manifest_schema.py
    ├── test_license_auditor.py
    ├── test_container_build.py
    ├── test_smoke_runner.py
    ├── test_registry_persistence.py
    └── test_equivalence_map.py
```

Per-cycle outputs (build logs, audit reports, smoke diffs) live under `runs/catalog/<entry-id>/<attempt-id>/`, not under `runs/<cycle-id>/`, because Catalog operations are independent of any single experiment cycle.

### 4.3 Registry schema (SQLite)

```sql
CREATE TABLE catalog_entries (
    simulator_id          TEXT PRIMARY KEY,
    manifest_hash         TEXT NOT NULL,
    manifest_path         TEXT NOT NULL,
    image_sha             TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('active','quarantined','deprecated')),
    onboarded_at          TEXT NOT NULL,
    last_reverified_at    TEXT,
    last_smoke_test_json  TEXT NOT NULL,   -- inlined SmokeTestRecord JSON
    license_audit_path    TEXT NOT NULL
);

CREATE TABLE catalog_observables (
    simulator_id    TEXT NOT NULL,
    observable      TEXT NOT NULL,
    PRIMARY KEY (simulator_id, observable),
    FOREIGN KEY (simulator_id) REFERENCES catalog_entries(simulator_id) ON DELETE CASCADE
);

CREATE TABLE catalog_equivalence (
    observable          TEXT NOT NULL,
    simulator_id_a      TEXT NOT NULL,
    simulator_id_b      TEXT NOT NULL,
    tolerance           REAL NOT NULL,
    tolerance_kind      TEXT NOT NULL CHECK (tolerance_kind IN ('relative','absolute','mixed')),
    notes               TEXT,
    PRIMARY KEY (observable, simulator_id_a, simulator_id_b),
    FOREIGN KEY (simulator_id_a) REFERENCES catalog_entries(simulator_id) ON DELETE CASCADE,
    FOREIGN KEY (simulator_id_b) REFERENCES catalog_entries(simulator_id) ON DELETE CASCADE
);

CREATE INDEX idx_entries_status      ON catalog_entries(status);
CREATE INDEX idx_observables_obs     ON catalog_observables(observable);
CREATE INDEX idx_equivalence_obs     ON catalog_equivalence(observable);
```

`catalog_equivalence` rows are inserted in both directions (a-b and b-a) when a manifest declares a pair, so lookups by observable return all reachable counterparts in a single query.

### 4.4 Smoke-test tolerance schema

`manifests/<simulator-id>/smoke/tolerance.yaml`:

```yaml
schema_version: "1.0"
fields:
  - path: "$.outputs.observable_a"
    kind: "relative"
    tolerance: 1.0e-6
  - path: "$.outputs.observable_b"
    kind: "absolute"
    tolerance: 1.0e-9
  - path: "$.outputs.spectrum[*]"
    kind: "relative"
    tolerance: 1.0e-4
global:
  max_field_residual: 1.0e-3        # any field whose residual exceeds this fails
  allow_extra_fields: false
  allow_missing_fields: false
```

Tolerances live in the manifest tree, are loaded by the smoke runner, and are part of the canonical manifest hash via their declared file paths and content hashes (§5.6).

## 5. Algorithms / Logic

### 5.1 Manifest loading

1. Read `manifest.yaml`; parse with PyYAML `safe_load`.
2. Construct `SimulatorManifest(**data)` — Pydantic raises `ValidationError` on any extra/missing/typed field; we wrap into `ManifestValidationError`.
3. Recompute the manifest hash (§5.6) and compare to the declared `manifest_hash`. Mismatch raises `ManifestValidationError("manifest_hash drift")`.
4. Resolve all relative paths against the manifest's directory and assert each exists (Dockerfile, schemas, smoke inputs, references, license notice).
5. Validate per-field invariants:
   - `simulator_id` matches `^[a-z][a-z0-9-]{2,63}$`.
   - `container_recipe.base_image_sha` matches `^sha256:[0-9a-f]{64}$`.
   - `container_recipe.smoke_test_target` is an absolute in-container path.
   - `dependency_graph.nodes` is non-empty; every `is_data_file=False` node has `license ∈ OsiApprovedLicense`; every `is_data_file=True` node has `license ∈ OsiApprovedLicense ∪ CarveOutLicense` AND, if `license ∈ CarveOutLicense`, an entry in the carve-out database (§5.2). Carve-out licenses on code deps are an automatic deny.
   - Every `DependencyNode.license_text` is non-empty (the verbatim LICENSE-file contents the upstream artifact ships).
   - `cross_simulator_equivalence_map` references only `simulator_id`s currently in the registry **or** the simulator being onboarded itself (forward references resolved post-onboarding by `reindex()`).

### 5.2 License auditor

This is *the* most-underestimated risk in the architecture (`SPEC.md` §5). Treat every assumption as adversarial.

**Discipline: SPDX IDs are checked against the enum allowlist; phrase scanning operates on raw
LICENSE-file text.** The two checks are independent. The SPDX-ID check (steps 3a–c) is a
structured allowlist over a controlled enum. The phrase scan (step 3d) is a defensive text
search over the *actual* LICENSE-file contents the upstream artifact ships, carried on
`DependencyNode.license_text`. This catches the common attack surface where an SPDX ID is
misdeclared (e.g., "BSD-3-Clause") but the actual LICENSE file contains rider clauses
("academic use only", "non-commercial", …) that the SPDX ID alone does not surface. The
manifest schema requires every dep to carry both the SPDX ID and the verbatim LICENSE text.

```
Input:  SimulatorManifest (DependencyGraph.nodes each carry .license + .license_text)
Output: LicenseAuditReport (overall_verdict ∈ {allow, deny})

Steps:
1. Load OSI snapshot: factory/catalog/data/licenses-osi.json.
   Snapshot is a static, versioned list of SPDX IDs the project considers acceptable for
   redistribution inside a self-contained OCI image. The snapshot has its own
   osi_db_snapshot_hash that the audit report records. The snapshot is derived from the
   OsiApprovedLicense enum plus the CarveOutLicense enum, with per-license metadata
   (redistributable_in_container, allowed_for_code_dep, allowed_for_data_file).
2. Load carve-outs: factory/catalog/data/redistributable-carveouts.json.
   Carve-outs are explicit { package, version_range, license, rationale } records covering
   data files (CC0/CC-BY-4/Public-Domain lookup tables, basis sets, pseudopotentials) and
   other narrow cases. Every carve-out must cite a rationale; no anonymous exceptions.
   Carve-out licenses are NEVER allowed for code dependencies (is_data_file must be True).
3. For each DependencyNode in DependencyGraph.nodes:
   a. Normalize node.license (the SPDX ID) to canonical SPDX form (case-insensitive, alias
      map). Reject if normalization fails.
   b. If node.license is a member of OsiApprovedLicense → SPDX check verdict=allow.
   c. Else if node.license is a member of CarveOutLicense AND node.is_data_file=True AND
      a carve-out entry matches package@version → SPDX check verdict=allow. The carve-out's
      rationale is copied into LicenseFinding.deny_reason as a positive note.
      (CarveOutLicense values on code deps — is_data_file=False — are an automatic deny.)
   d. SPDX check verdict=deny if neither (b) nor (c) holds.
   3d. **Phrase scan operates on node.license_text (the raw LICENSE-file contents), NOT on
       node.license (the SPDX ID).** Search node.license_text case-insensitively for any of:
         "academic use only", "non-commercial", "noncommercial", "registration required",
         "redistribution prohibited", "research only", "personal use only", "evaluation only",
         "no commercial use", "not for commercial"
       If any phrase matches → phrase verdict=deny, deny_reason="non-redistributable phrase
       in LICENSE text: <phrase>" with line-number citation from license_text.
       This scan runs INDEPENDENTLY of steps 3a-c — a node with an OSI SPDX ID can still
       be denied if its actual LICENSE text contains a rider phrase.
   e. Combined verdict for the node = allow iff SPDX check AND phrase scan both allow.
      Else verdict=deny with both deny_reasons concatenated.
4. is_data_file nodes that are not redistributable_in_container always deny, regardless of
   stated license — the container must build with no external pulls.
5. overall_verdict = "allow" iff EVERY finding is "allow".
6. Persist LicenseAuditReport JSONL under runs/catalog/<entry-id>/<attempt-id>/license_audit.json.
   The report records BOTH the SPDX-ID check outcome and the phrase-scan outcome per node,
   plus a snippet (≤200 chars) of license_text where a phrase matched.
7. If overall_verdict == "deny", raise CatalogLicenseViolation with the first three deny findings
   inlined and the full report path attached.
```

The auditor walks the dep graph that *the manifest declares*. It does **not** independently re-resolve transitive deps — that would be a non-deterministic operation depending on whatever the package manager would do *today*. The discipline is: the manifest author runs an SBOM tool out-of-band, commits the resolved graph as part of the manifest, and the auditor verifies the declared graph against the static OSI snapshot. Onboarding fails loud if the declared graph is incomplete (no MPI flavor, no BLAS variant) because the container won't build without those edges.

A separate offline tool, `python -m factory.catalog audit-license --regenerate-sbom <manifest>`, can be run to refresh the declared graph; it is **not** invoked automatically during `onboard()`.

### 5.3 Container build harness

```
Input:  SimulatorManifest with container_recipe and Dockerfile at manifest_dir/<recipe.dockerfile_path>
Output: ImageSha

Determinism contract:
- The same Dockerfile + same base_image_sha + same install steps must produce the same
  image SHA. Reproducibility is verified by an idempotent rebuild assertion in CI.

Steps:
1. attempt_id := provided or f"build-{utc-ts}-{uuid4().hex[:8]}".
2. work_dir := runs/catalog/<simulator_id>/<attempt_id>/
   mkdir; write events.jsonl with event=build_start.
3. Stage build context: copy the manifest directory tree into work_dir/context/.
   Drop files matching .dockerignore. Hermetic builds get --network=none after stage 0.
4. Recompute container_recipe.install_steps_hash:
   - Concatenate all RUN lines in the Dockerfile in order, normalize whitespace,
     SHA-256. Compare to manifest's declared hash. Mismatch → ContainerBuildFailed.
5. Invoke the builder backend:
   - docker-buildx: docker buildx build --platform <pin> --provenance=true \
       --output type=image,name=catalog/<simulator_id>:<attempt_id>,push=false \
       --no-cache work_dir/context
   - podman: equivalent
   - mock: deterministic ImageSha via SHA-256(manifest_hash || install_steps_hash).
   Capture stdout+stderr to build.log; cap log at 16 MB and rotate.
6. On non-zero exit → ContainerBuildFailed with build.log path attached.
7. Parse the builder's image SHA from the structured output (--output digest); verify
   it matches expected_format ^sha256:[0-9a-f]{64}$. Persist as image_sha.
8. Write events.jsonl event=build_complete with image_sha and runtime.
9. Return image_sha.
```

Determinism is verified by an *idempotent rebuild* test (§7) that builds the same manifest twice in fresh work dirs and asserts identical image SHAs. If a backend's output is non-deterministic (e.g., timestamps embedded in metadata), the test fails and the manifest author must use a deterministic backend invocation (e.g., `--source-date-epoch=0` or buildkit's `--provenance=mode=max`).

### 5.4 Smoke-test runner

```
Input:  CatalogEntry (built image), tolerance.yaml in manifest tree
Output: SmokeTestRecord

Steps:
1. work_dir := runs/catalog/<simulator_id>/<attempt_id>/smoke/
   mkdir; events.jsonl event=smoke_start.
2. Resolve network mode from container_recipe.hermetic:
   - hermetic=True  → --network=none (default; the strict path).
   - hermetic=False → --network=host AND emit factory.catalog.smoke_non_hermetic event
     carrying simulator_id + non_hermetic_reason. The telemetry warning is mandatory;
     non-hermetic smoke tests are still acceptable but never silent.
3. Run container:
   - docker run --rm <network-mode> \
       --memory=<recipe.memory_limit_default> \
       --cpus=<recipe.cpu_limit_default> \
       -v work_dir/in:/in:ro \
       -v work_dir/out:/out \
       catalog/<simulator_id>:<attempt_id> <recipe.smoke_test_target>
   - Mount the manifest's smoke/input.<ext> at /in/input.<ext>.
   - Cap wall-clock at 2 × expected_smoke_runtime_seconds; SIGKILL on overrun.
4. Load actual output from work_dir/out/output.<ext>.
5. Load reference from manifests/<simulator_id>/smoke/reference_output.<ext>.
6. Load tolerance schema from manifests/<simulator_id>/smoke/tolerance.yaml.
7. For each tolerance entry, apply JSONPath / HDF5 path lookup against both files;
   compute residual under the declared kind (relative/absolute):
     residual = |actual - reference| / max(|reference|, eps)        # relative
     residual = |actual - reference|                                 # absolute
   Track max_field_residual across all fields.
8. If global.allow_extra_fields=false and actual has fields the reference does not,
   the test fails. Same for global.allow_missing_fields.
9. If any per-field residual > tolerance OR max_field_residual > global.max_field_residual,
   the test fails. Write diff to smoke.diff.json.
10. Record SmokeTestRecord (passed: bool, max_field_residual, runtime, diff_path if any).
11. If passed=false, raise SmokeTestFailed during onboarding; during reverify_all,
    quarantine the entry instead of raising.
```

Smoke tests are deliberately *narrow*: a single known-good input with a tightly-bounded expected output. They are not a substitute for the G4 validation portfolio (spec 009) — they confirm that *this build of this image* still computes a reference observable correctly. A green smoke test means "the simulator is alive and runs"; the validation portfolio means "the simulator is right for *this* hypothesis."

### 5.5 `onboard()` orchestrator

```
Input:  manifest_path
Output: CatalogEntry  (or raises one of the typed errors)

Steps:
1. attempt_id := uuid.
2. Validate manifest (§5.1). Raise ManifestValidationError on failure.
3. Audit license (§5.2). Raise CatalogLicenseViolation on deny.
4. Build container (§5.3). Raise ContainerBuildFailed on builder non-zero or hash mismatch.
5. Run smoke test (§5.4). Raise SmokeTestFailed if reference deviates beyond tolerance.
6. Compute CatalogEntry; open SQLite registry; in a single transaction:
   - INSERT into catalog_entries.
   - INSERT into catalog_observables for every observable in capabilities.
   - INSERT both directions of every EquivalencePair into catalog_equivalence (skip if
     the counterpart simulator is not yet in the registry; reindex() picks them up later).
   - COMMIT. On any constraint violation, ROLLBACK and raise ManifestRegistryDrift with
     the offending row.
7. Emit factory.catalog.entry_onboarded event with simulator_id, manifest_hash, image_sha.
8. Return the CatalogEntry.
```

Failures at any step preserve all per-attempt artifacts under `runs/catalog/<simulator_id>/<attempt_id>/` so a human (or a subsequent agent) can inspect logs without re-running. **No automatic retries** — onboarding is a curated act; auto-retry would mask the failure surface this module is built to expose.

### 5.6 Manifest hashing

Manifests are YAML; the hashing input is the *canonical-JSON* projection of the parsed Pydantic model (mirroring spec 002 §5.1) with `manifest_hash` excluded. Per-file content hashes for the Dockerfile, schemas, smoke inputs, and reference outputs are *not* part of the manifest hash directly, but the manifest's `container_recipe.install_steps_hash` and the schema-version field cover those changes by reference. This keeps the manifest hash stable across whitespace-only YAML edits but sensitive to anything that changes the semantic content of the entry.

```python
def compute_manifest_hash(m: SimulatorManifest) -> ManifestHash:
    payload = m.model_dump(exclude={"manifest_hash"}, mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return ManifestHash(hashlib.sha256(canonical).hexdigest())
```

### 5.7 Cross-simulator equivalence map

The map is the input the G4 validation portfolio reads to decide whether a cross-simulator check is even possible for an observable. Logic:

```
Given an experiment computing observable O on simulator X:
  pairs = catalog.equivalence_pairs(O)
  candidates = [p.simulator_id_b for p in pairs if p.simulator_id_a == X and catalog.get(p.simulator_id_b).status == ACTIVE]
  if candidates is empty:
      G4 cannot run a cross-simulator check; portfolio reweights toward refinement + symmetry.
  else:
      G4 picks the lowest-cost candidate (Selector spec 005 supplies cost estimate) and runs.
```

Phase A acceptance requires **at least one EquivalencePair populated in the v1 catalog** — that is the precondition for the G4 cross-simulator check called out in `SPEC.md` §11 Phase A. The mock fixture pair (`mock_solver_a` ↔ `mock_solver_b` on `mean_observable`) exists precisely so this code path is exercised end-to-end in mock mode in CI from day one.

### 5.8 Periodic reverification

`reverify_all(max_age_days=30)` iterates every active entry. For each:

1. Re-pull the base image by SHA (must match `container_recipe.base_image_sha`); pull failure indicates the upstream tag was rewritten — quarantine.
2. Re-run the smoke test against the entry's existing image SHA. If it fails, quarantine with `reason="smoke regression"`.
3. Re-check the OSI snapshot hash; if the snapshot has been updated since onboarding, re-run the license audit. Any new deny finding quarantines with `reason="license drift: <node>"`.
4. Update `last_reverified_at`.

Quarantined entries are not returned by `list_for_observable`, are not eligible Selector candidates, and surface in `factory.catalog.quarantine_alert` events for human review.

### 5.9 Catalog growth policy

| Phase | Workflow | Who approves |
| :--- | :--- | :--- |
| A — first 90 days | A human writes a manifest + Dockerfile + smoke inputs by hand; `onboard()` runs the audits and builds the image. 5–10 entries total, with a **hard minimum of two OSI-licensed simulators in the primary domain** so the G4 cross-simulator validation portfolio (spec 009) has a real `EquivalencePair` to exercise. The mock fixtures (mock_solver_a + mock_solver_b) demonstrate the pattern; the two real entries must replicate it on a non-trivial observable in the chosen Phase A domain. | Human PR review |
| B — year 1 | The factory may *propose* a candidate entry (the literature module suggests a simulator; the agent drafts a manifest; the build harness verifies). A human approves before `onboard()` is invoked. ~30 entries. | Human approver from a documented allowlist |
| C — year 2+ | Autonomous onboarding from upstream documentation. Out of scope for this spec; tracked as open research. | Deferred |

The Phase B "agent drafts a manifest" path is **not** an alternate code path here — it produces a YAML file by exactly the same schema. The only difference from Phase A is *who* clicked merge.

**Phase A precondition for G4.** Without the two-OSI-simulators-per-primary-domain floor, the G4 cross-simulator check would be untestable end-to-end with real (non-mock) builds, and the Phase A acceptance criterion in `SPEC.md` §11 (and PRD-004 §8) cannot be ticked. Ship the floor before claiming Phase A complete.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `ManifestValidationError` | Pydantic validation, hash drift, missing referenced files | State machine routes the experiment back to the operator; Catalog rejects with the field-level Pydantic error attached to `cycle.jsonl` |
| `CatalogLicenseViolation` | A transitive dep is non-OSI, non-redistributable, or registration-gated | Onboarding aborts pre-build; the offending deny findings (top 3) and full audit report path are surfaced; the manifest is not persisted |
| `ContainerBuildFailed` | Builder returned non-zero, install-steps-hash mismatch, or non-deterministic SHA | Onboarding aborts; `build.log` preserved; **no auto-retry** — Dockerfile must change first |
| `SmokeTestFailed` | Image built but residuals exceed tolerance or fields are extra/missing | Onboarding aborts; `smoke.diff.json` preserved; either tighten the recipe or amend `tolerance.yaml` with rationale |
| `EntryQuarantined` | An existing entry failed a periodic reverification (smoke regression, base-image SHA mismatch, or license drift) | Entry status → quarantined; Selector skips it; cycle that referenced it falls to G1.5 with `parked_for_lack_of_tooling` |
| `ManifestRegistryDrift` | Registry index disagrees with manifest files (e.g., SQLite row with no matching manifest, or duplicate `simulator_id`) | Run `catalog list --reindex`; manifests are authoritative; the registry is regenerated from them |
| `CatalogLookupError` | `get()`/`list_for_observable()` asked for a non-existent or quarantined entry | Selector treats as "no available simulator"; G1.5 parks the hypothesis |

All errors inherit from `CatalogError(FactoryError)` so the gate state machine and telemetry pipeline can dispatch on a single root class.

## 7. Testing

**Mock-mode** (CI, no Docker, no network):

- `test_catalog_typical_usage.py` — **REQUIRED**. Onboard `mock_solver_a.yaml`; assert active entry, image SHA matches the deterministic mock, smoke test recorded as passed. Then onboard `mock_solver_b.yaml`; assert the equivalence pair shows up bi-directionally in `catalog_equivalence` for `mean_observable`.
- `test_manifest_schema.py` — load each fixture; assert validation; assert `manifest_hash` deterministic across reloads; assert `extra="forbid"` rejects an unknown YAML key.
- `test_license_auditor.py` — `mock_solver_bad_license.yaml` (contains an "academic use only" node) raises `CatalogLicenseViolation`; the report names the offending node. A second case asserts the carve-out database admits a CC-BY-4 data file with explicit rationale.
- `test_container_build.py` — mock backend returns deterministic image SHA for `mock_solver_a`; rebuild produces the *same* SHA (idempotency); install-steps-hash mismatch raises `ContainerBuildFailed`.
- `test_smoke_runner.py` — pre-recorded actual outputs under `fixtures/smoke_outputs/`; tolerance schema applied; per-field residuals computed correctly; extra-field rejection works.
- `test_registry_persistence.py` — onboard two mocks; query by observable; quarantine one; verify it disappears from `list_for_observable`; `reindex()` rebuilds the DB from manifests and the same entries reappear.
- `test_equivalence_map.py` — `equivalence_pairs("mean_observable")` returns the A↔B pair; asymmetric tolerance preserved.

**Live-mode** (`@pytest.mark.live`, gated behind Docker availability):

- `test_live_onboard_smoke.py` — onboards a real, tiny OSI-licensed numerical solver from the project's `containers/` tree; full build + smoke pass; takes <10 minutes.
- `test_live_reverify_drift.py` — re-pulls base image by SHA; failure to match (simulated by pointing at a deliberately-wrong SHA) quarantines the entry.

**Determinism tests:**

- Build the same manifest twice (in fresh work dirs); assert the same image SHA. Skip if backend is not deterministic; emit a warning rather than passing silently.

**Acceptance criteria (PRD-004):**

1. ≥ 5 entries onboarded successfully.
2. **≥ 2 OSI-licensed simulators in the primary domain** with at least one `EquivalencePair` registered between them on a shared observable (the precondition for Phase A G4 cross-simulator check). The mock fixtures alone do not satisfy this — two real, OSI-licensed entries are required.
3. License auditor blocks at least one synthetic adversarial manifest in CI — including one case where the SPDX ID is OSI-approved but the LICENSE-file text contains a "non-commercial" rider (proves the phrase scan operates on `license_text`, not on the SPDX ID).
4. `python -m factory.catalog onboard <fixture> --mock-mode` succeeds on a clean checkout with no API keys, no Docker, and no network.
5. `Catalog.version_hash()` is stable across processes for the same catalog state and changes when any entry's `manifest_hash`, `image_sha`, or `status` changes.

## 8. Performance & Budget

- **Manifest validation:** < 50 ms per manifest (Pydantic + YAML parse).
- **License audit:** < 100 ms for a graph with ≤ 500 nodes (in-memory dict lookups against the OSI snapshot).
- **Container build:** dominated by upstream compilers; bound is the manifest's declared `expected_smoke_runtime_seconds × 60`. Hard ceiling per onboarding attempt: 2 hours wall clock; over-cap raises `ContainerBuildFailed("timeout")`.
- **Smoke test:** capped at `2 × expected_smoke_runtime_seconds`.
- **Reverification batch:** ≤ 30 entries × max 2 minutes per entry = under 1 hour wall clock; scheduled weekly off-peak.
- **Disk:** each catalog entry persists ~50 MB of metadata + logs under `runs/catalog/<simulator-id>/`. Image layers themselves live in the OCI runtime store, not in the repo.
- **Cost:** there is no per-LLM-call cost in this module. The only money spent is compute time for container builds, which is reported to `factory.telemetry` if available.

## 9. Open Questions

- **SBOM tool authority.** We assume the manifest author runs an SBOM generator (Syft, CycloneDX, conda-meta inspection, pip dependency graph) out-of-band and commits the resolved graph. Should the harness also support an *opt-in* in-CI SBOM regeneration that compares against the declared graph? Deferred until we've seen the first 5 manifests by hand — over-eager automation here trades one risk surface (manual mistakes) for another (silent SBOM-tool drift).
- **License database freshness.** The OSI snapshot is checked in; we refresh it by hand. A future enhancement is a small auditor that pulls the canonical OSI list weekly and proposes an update PR. Until then, `osi_db_snapshot_hash` in every audit report is the chain-of-custody.
- **Multi-platform image SHAs.** `docker buildx` can produce per-platform digests; the manifest currently records one. Multi-platform support is deferred until a Phase A simulator actually requires it.
- **Equivalence-map asymmetry.** Some observables are not symmetric — simulator A may bound simulator B from above on `observable_x` but not vice versa. The schema currently stores per-direction pairs with independent tolerances; whether to add an asymmetry flag is open until we see a real case.
- **Image signing.** Signing onboarded images with sigstore / cosign so the registry could be audited externally is straightforward to add, but the threat model in Phase A doesn't justify it. Tracked as a Phase B nice-to-have.
- **Quarantine UX.** Quarantining is unidirectional today — once quarantined, the entry stays out until a human re-onboards with a fresh manifest. Whether to allow an "un-quarantine" path (with a forced re-audit) is a policy question, not a technical one.

## 10. TODO Checklist

- [ ] Scaffold `factory/catalog/` from the canonical module template (`factory/tooling scaffold-module --name catalog --spec 004`).
- [ ] Implement `OsiApprovedLicense`, `CarveOutLicense`, and the `LicenseId = OsiApprovedLicense | CarveOutLicense` union; export from `factory.catalog`.
- [ ] Implement `SimulatorManifest` and all sub-models in `factory/catalog/api.py`; round-trip YAML ↔ Pydantic with `extra="forbid"`; every `DependencyNode` carries SPDX `license` + verbatim `license_text`.
- [ ] Implement `ContainerRecipe.hermetic`/`non_hermetic_reason` validator pair (hermetic=True → reason must be None; hermetic=False → reason required).
- [ ] Implement canonical manifest hashing (§5.6); verify it matches across re-serialization.
- [ ] Author `factory/catalog/data/licenses-osi.json` as a static SPDX snapshot derived from `OsiApprovedLicense ∪ CarveOutLicense`; record `osi_db_snapshot_hash` at load.
- [ ] Author `factory/catalog/data/redistributable-carveouts.json` with explicit per-package rationales for `CarveOutLicense` data-file deps.
- [ ] Implement license auditor (§5.2) with both SPDX-ID check (against the enum allowlist) AND independent phrase scan over `DependencyNode.license_text`; produce `LicenseAuditReport` JSON recording both outcomes per node; raise `CatalogLicenseViolation` on deny.
- [ ] Implement container build harness with `docker-buildx`, `podman`, and `mock` backends; verify idempotent rebuild SHA. Support both hermetic (`--network=none`) and non-hermetic (`--network=host` + `factory.catalog.smoke_non_hermetic` warning) modes.
- [ ] Implement smoke-test runner with `tolerance.yaml` parser and per-field residual computation (JSONPath + HDF5 path lookups); honor `container_recipe.hermetic` for network mode.
- [ ] Implement `Catalog.onboard()` orchestrator (§5.5) with single-transaction registry write.
- [ ] Implement registry schema (`runs/catalog/registry.sqlite`) with the three tables in §4.3.
- [ ] Implement `get`, `list_entries(status=ACTIVE)`, `list_for_observable`, `equivalence_pairs`, `version_hash() -> CatalogVersionHash`, `mock_factory`, `from_fixture(name)` (alias).
- [ ] Implement `reverify_all` with smoke + base-image-SHA + license-drift checks (re-runs phrase scan against stored `license_text`); quarantine on any drift.
- [ ] Implement `reindex()` from manifests as authoritative source.
- [ ] Write three fixture manifests under `factory/catalog/fixtures/manifests/` (`mock_solver_a.yaml`, `mock_solver_b.yaml`, `mock_solver_bad_license.yaml`) and their SBOM + smoke fixtures. The bad-license fixture must include one dep whose SPDX is OSI-approved but whose `license_text` carries a "non-commercial" rider.
- [ ] Write `factory/catalog/cli.py` with `onboard`, `audit-license`, `build`, `smoke`, `list`, `show`, `equivalence-map`, `quarantine`, `--reindex`.
- [ ] Write seven tests in `factory/catalog/tests/`; all pass in mock mode in CI.
- [ ] Write `tests/test_live_onboard_smoke.py` and `tests/test_live_reverify_drift.py` (`@pytest.mark.live`).
- [ ] Write `factory/catalog/README.md` (≤ 1 page, mock-mode example).
- [ ] Write `docs/runbooks/catalog-onboarding.md` covering manifest authoring, SBOM generation with `license_text` capture, hermetic vs non-hermetic builds, and Dockerfile reproducibility tips.
- [ ] Verify `mypy --strict factory/catalog/` passes.
- [ ] Verify `python -m factory.catalog onboard factory/catalog/fixtures/manifests/mock_solver_a.yaml --mock-mode` works on a fresh checkout.
- [ ] Land first 2 OSI-licensed real entries in `factory/catalog/manifests/` in the same primary domain, sharing at least one observable via `EquivalencePair` (PRD-004 acceptance §7.2).
- [ ] Tick PRD-004 acceptance in `docs/INDEX.md` once the 5 criteria in §7 above pass.
