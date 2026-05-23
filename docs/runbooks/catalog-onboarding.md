# Runbook: Catalog Onboarding (One Simulator, End to End)

> What this covers: Onboards exactly one OSI-licensed open-source simulator to the `SimulatorCatalog` -- license audit, container build, smoke test, registry persistence, and cross-simulator equivalence wiring. Repeat the runbook once per simulator.
> When to use: Phase A v1 catalog buildout (PRD-004) or any time a new simulator is added in Phase B via the human-approved onboarding workflow. **Do not** use this runbook for Phase C autonomous onboarding (deferred research).
> Estimated time: 4-16 hours of attended work per simulator. Build wall-clock dominates; expect 15 minutes (cached) to 2 hours (cold) inside `factory catalog onboard` (operator CLI; the underlying pipeline can also be driven module-internally via `python -m factory.catalog onboard`).

The Catalog is the substrate boundary of the factory (`SPEC.md` §5). Every shortcut taken here -- a sloppy license audit, a loose smoke tolerance, an undeclared dependency -- becomes a silent bug downstream. Read the spec failure modes (spec 004 §6) before you start.

---

## 1. Prerequisites

### 1.1 Decide what you are onboarding

Before opening any file, write down the answers to these questions:

- **Simulator identity.** Upstream repo URL, the exact tag/commit you intend to pin, the canonical citation. If the simulator does not have a stable release tag or a commit within the last 24 months, stop -- spec 004 §5.1 forbids stale entries.
- **Domain label.** Use the canonical label that matches `config/domain_scope.yaml`. New domain labels require an `INDEX.md` update first.
- **Observable(s) the simulator computes.** Be specific. "Stress tensor" is not an observable; "mean von Mises stress over a referenced sub-volume" is. Cross-simulator validation hinges on this precision.
- **The cross-validation partner.** Which already-active Catalog entry will share an observable with this one? If the answer is "none", you must onboard the partner in the same session, or skip the equivalence map for this entry and onboard the partner immediately after. PRD-004 acceptance requires **at least one** populated `EquivalencePair`.

### 1.2 Environment and tools

- Repository checkout at the Phase A integration commit.
- `uv sync` already run in this checkout (the same venv used by the factory CLI).
- A container runtime: `docker buildx` 0.13+ or `podman` 5.0+. Spec 004 §5.3 supports `docker-buildx`, `podman`, and `mock` backends -- `mock` is for tests, not real onboarding.
- An SBOM generator on your `$PATH`. `syft` is the project default; `cyclonedx-py` is acceptable for pure-Python simulators. The factory does **not** auto-resolve transitive deps (spec 004 §5.2); you generate the graph out-of-band and commit it.
- Disk: ~5 GB scratch for the build context plus space for the final image (typically 1-3 GB for a numerical-solver image).
- Network: outbound access to your distro mirror and any language-specific registries (PyPI, conda-forge, etc.). Hermetic builds (`hermetic: true` in the manifest) drop to `--network=none` after the deps stage; verify your mirrors are reachable during the deps stage only.

### 1.3 Access and licensing

- A signed-off license audit ledger entry for this candidate. The two-step audit:
  1. **Manual review** by the onboarding engineer. Walk the upstream `LICENSE`, `NOTICE`, and every transitive dep's license. If you see "academic use only", "registration required", "redistribution prohibited", "non-commercial", "research only", or "personal use only" anywhere -- stop. This entry will fail the auditor; do not waste your time on the Dockerfile.
  2. **Automated audit** via the harness in step 2.4 below. Both must agree.
- For simulators that ship with data files (DFT pseudopotentials, basis sets, lookup tables), each data file is a separate dependency node in the manifest and must have its own license entry. `CC-BY-4.0`, `CC0-1.0`, and `Public-Domain` are allowed for data files; bare "redistribution by permission" is not.

### 1.4 Configuration that must be in place

- `factory/catalog/data/licenses-osi.json` and `factory/catalog/data/redistributable-carveouts.json` are present and the `osi_db_snapshot_hash` matches what the test suite expects. Run `python -m factory.catalog audit-license --version` to print both hashes.
- The Catalog registry exists: `runs/catalog/registry.sqlite`. If this is the first entry, the registry is created by the first successful onboarding.
- `mypy --strict factory/catalog/` passes against the current head. If it does not, the schema may have drifted -- repair before authoring manifests.

### 1.5 Other runbooks that must succeed first

- For the **very first** entry, none -- this is the bottom of the stack.
- For every subsequent entry, no other runbook is required.
- For the second entry (the cross-validation partner), you must have completed this runbook once already and have a working active entry to reference in `cross_simulator_equivalence_map`.

---

## 2. Steps

### Step 1 -- Lay out the manifest directory

Create the on-disk tree under `factory/catalog/manifests/<simulator-id>/`. The `simulator-id` must match `^[a-z][a-z0-9-]{2,63}$` per spec 004 §5.1.

```
factory/catalog/manifests/<simulator-id>/
|-- manifest.yaml
|-- Dockerfile
|-- schemas/
|   |-- input.schema.json
|   `-- output.schema.json
|-- smoke/
|   |-- input.<ext>
|   |-- reference_output.<ext>
|   `-- tolerance.yaml
|-- LICENSE
`-- NOTICE
```

The directory layout is enforced by spec 004 §4.2; the catalog harness will reject manifests with missing referenced files.

### Step 2 -- Author the manifest YAML

Drop the following template into `factory/catalog/manifests/<simulator-id>/manifest.yaml` and fill in every field. The Pydantic schema is in `factory/catalog/api.py` (`SimulatorManifest`) and is `extra="forbid"` -- unknown keys fail validation.

```yaml
schema_version: "1.0"
simulator_id: "<simulator-id>"
display_name: "<Human Readable Name>"
domain: "<canonical-domain-label>"           # matches config/domain_scope.yaml
license: "MIT"                                # one of LicenseId (spec 004 §3)
license_notice_path: "LICENSE"

capabilities:
  computed_observables:
    - "<observable_name_a>"
    - "<observable_name_b>"
  supported_regimes:
    - "<regime_label>"
  explicit_limits:
    - "<what this simulator must NOT be asked to do>"
  fidelity_levels:
    - "dry_run"
    - "mid_fidelity"
    - "oracle"

io_schema:
  input_format: "json"                        # one of: json|yaml|namelist|toml|hdf5|netcdf|binary-protobuf
  input_schema_path: "schemas/input.schema.json"
  output_format: "json"
  output_schema_path: "schemas/output.schema.json"
  units_table_path: null                      # set to a path if you need cross-simulator unit conversion

container_recipe:
  dockerfile_path: "Dockerfile"
  base_image: "docker.io/library/debian"
  base_image_sha: "sha256:<pinned digest>"    # MUST be a content digest, not a tag
  install_steps_hash: "<sha256 of normalised RUN lines>"
  smoke_test_target: "/opt/<simulator>/bin/smoke"
  expected_smoke_runtime_seconds: 30.0
  hermetic: true                              # set false only with rationale in NOTICE

dependency_graph:
  mpi_flavor: "openmpi"                       # one of: none|openmpi|mpich|intel-mpi-redistributable|mvapich2
  blas_variant: "openblas"                    # one of: openblas|blis|reference-blas|none
  cuda_version: null                          # e.g. "12.4" for GPU builds
  compiler: "gcc-13.2"
  os_family: "debian"
  nodes:
    - name: "openmpi"
      version: "4.1.6"
      license: "BSD-3-Clause"
      source_url: "https://www.open-mpi.org/software/ompi/v4.1/"
      is_data_file: false
      redistributable_in_container: true
      notes: null
    # ... one entry per transitive dep ...
  edges:
    - ["<simulator>", "openmpi"]
    # ... informational parent/child pairs ...

maintenance_signal:
  upstream_repo_url: "https://github.com/<org>/<repo>"
  last_commit_date: "2026-03-15T00:00:00Z"
  latest_stable_tag: "v2.7.0"
  last_observed_at: "2026-05-23T00:00:00Z"

known_pathologies:
  - pathology_id: "<short-id>"
    description: "<human-readable failure mode>"
    affected_regime: "<regime label or quantitative window>"
    detection_hint: "<heuristic for selector/adapter to flag in advance>"

cross_simulator_equivalence_map:
  - observable: "<observable_name>"
    cross_simulator_id: "<id-of-existing-active-entry>"
    tolerance: 1.0e-4
    tolerance_kind: "relative"                # one of: relative|absolute|mixed
    notes: "<historical agreement reference or null>"

manifest_hash: "<computed in step 3>"
```

Field-level gotchas worth re-reading from spec 004:

- `base_image_sha` is a content digest, not a tag. `sha256:...`. The harness rejects tag references because tags are mutable -- spec 004 §5.3.
- `dependency_graph.nodes` lists the **full transitive** graph (build + runtime). The auditor only checks declared nodes; missing nodes mean the container fails to build, which the auditor cannot catch on its own.
- `cross_simulator_equivalence_map` may reference the simulator being onboarded itself for forward references; `Catalog.reindex()` resolves those later (spec 004 §5.1).
- `known_pathologies` is required to be a list (possibly empty). It is read by the Selector (spec 005) when ranking candidates.
- Leave `manifest_hash` blank for now -- step 3 computes it.

### Step 3 -- Generate the SBOM and finalise the dependency graph

```bash
cd factory/catalog/manifests/<simulator-id>
syft scan dir:. -o cyclonedx-json > sbom.cdx.json
```

For Python-only simulators, `cyclonedx-py environment > sbom.cdx.json` against the simulator's venv is acceptable.

Transcribe each dependency from `sbom.cdx.json` into `manifest.yaml` under `dependency_graph.nodes`. Do not skip data files. If `syft` flags an "unknown" license, you must research and record the actual license yourself; a literal `"UNKNOWN"` value will be denied by the auditor (spec 004 §5.2 step 3e).

Once the manifest is complete, compute and write the canonical hash:

```bash
python -m factory.catalog show --manifest manifest.yaml --compute-hash | tee /tmp/hash
# Open manifest.yaml and set manifest_hash to the printed value.
```

The hashing rule is documented in spec 004 §5.6 -- canonical JSON over the parsed Pydantic model excluding `manifest_hash`. Any tweak to the manifest after this point requires re-computing the hash; the harness verifies on load (spec 004 §5.1 step 3).

### Step 4 -- Author the Dockerfile and lockfile

Spec 004 §5.3 enforces a determinism contract: same Dockerfile + same `base_image_sha` + same install steps -> same image SHA. To satisfy it:

- Pin every dependency version. No `latest`, no unconstrained ranges. The lockfile (`requirements.txt`, `conda-lock.yaml`, distro-specific `apt` snapshot, etc.) ships under the manifest directory.
- Stage the build so the deps step is networked and the build step is `--network=none` if you intend `hermetic: true`.
- Set `SOURCE_DATE_EPOCH` and other determinism knobs (BuildKit `--provenance=mode=max`, `--source-date-epoch=0`) so the image SHA is stable across rebuilds.
- Compute `install_steps_hash` (spec 004 §5.3 step 4) and set it in the manifest:

```bash
grep -E '^RUN ' Dockerfile | tr -s ' ' | sha256sum | awk '{print $1}'
```

Update the manifest's `container_recipe.install_steps_hash`. The harness will recompute this and fail loud on mismatch.

### Step 5 -- Define the smoke test target and reference output

Spec 004 §5.4 specifies the runner. You must provide:

- `smoke/input.<ext>` -- the known-good input file. Keep it tiny; `expected_smoke_runtime_seconds` is also the wall-clock cap (×2 hard ceiling).
- `smoke/reference_output.<ext>` -- the canonical expected output. This is the chain-of-custody; if you cannot defend the reference output, the smoke test has no meaning.
- `smoke/tolerance.yaml` -- per-field tolerances. Template:

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
  max_field_residual: 1.0e-3
  allow_extra_fields: false
  allow_missing_fields: false
```

Set tolerances to the **tightest** values the simulator can reproducibly hit on the chosen reference. Loose tolerances are tolerated only with rationale in the manifest's `notes` field; do not silently widen tolerances when the smoke test fails -- that is a `SmokeTestFailed` recovery anti-pattern called out in spec 004 §6.

### Step 6 -- Pre-flight: dry-run the license auditor

Before invoking the full onboarding pipeline, run the auditor standalone:

```bash
python -m factory.catalog audit-license factory/catalog/manifests/<simulator-id>/manifest.yaml \
    --format json > /tmp/audit.json
jq '{overall_verdict, deny_findings: [.findings[] | select(.verdict=="deny")]}' /tmp/audit.json
```

Expected output: `overall_verdict: "allow"` and `deny_findings: []`.

If the auditor denies:
- A node has a non-OSI license: either remove that dependency from the simulator (rebuild without it) or refuse the entry. Phase A does **not** accept exceptions; "free for academic use" is a hard fail per spec 004 §5.2.
- A data file is flagged: add a carve-out entry to `factory/catalog/data/redistributable-carveouts.json` with explicit rationale, **only** if the file's true license is `CC0`, `CC-BY-4.0`, `Public-Domain`, or another freely-redistributable license. Anonymous carve-outs are forbidden (spec 004 §5.2 step 2).
- A "deny phrase" hit: read the offending license text carefully. If the phrase is in marketing copy but the actual license is OSI-approved, normalise the `declared_license` field to its SPDX ID and re-run. If the phrase is in the binding license text, the entry is denied -- do not proceed.

### Step 7 -- Onboard the entry

```bash
factory catalog onboard factory/catalog/manifests/<simulator-id>/manifest.yaml \
    --attempt-id $(date +%Y%m%dT%H%M%S)
```

This runs the full pipeline (spec 004 §5.5): validate -> license audit -> container build -> smoke test -> single-transaction registry persist. Expected output is a `CatalogEntry` JSON projection with:

- `simulator_id: "<your id>"`
- `status: "active"`
- `image_sha: "sha256:..."` matching the deterministic rebuild.
- `last_smoke_test.passed: true`
- `last_smoke_test.max_field_residual` reported and well under your tolerance.

Per-attempt artifacts land under `runs/catalog/<simulator-id>/<attempt-id>/`:

- `events.jsonl` -- structured event stream for the attempt.
- `build.log` -- builder stdout/stderr (capped at 16 MB).
- `license_audit.json` -- the full `LicenseAuditReport`.
- `smoke.diff.json` -- present only on smoke failures.

Failures route to typed errors (spec 004 §6) and **do not auto-retry**. Read the table below for recovery paths.

### Step 8 -- Verify reproducibility

Determinism is a PRD-004 acceptance criterion. Build twice in fresh work dirs and assert the same image SHA:

```bash
python -m factory.catalog build --manifest factory/catalog/manifests/<simulator-id>/manifest.yaml \
    --attempt-id rebuild-a
python -m factory.catalog build --manifest factory/catalog/manifests/<simulator-id>/manifest.yaml \
    --attempt-id rebuild-b

jq -r '.image_sha' runs/catalog/<simulator-id>/rebuild-a/result.json
jq -r '.image_sha' runs/catalog/<simulator-id>/rebuild-b/result.json
```

Both lines must print the same `sha256:...`. If they differ, the build is non-deterministic -- BuildKit timestamps, locale, or `pip` wheel ordering are the usual culprits. Spec 004 §5.3 lists the determinism knobs to enable. Do not register the entry as active until rebuild produces identical digests.

### Step 9 -- Populate or extend the cross-simulator equivalence map

If you set `cross_simulator_equivalence_map` in step 2, `onboard()` already inserted the rows. Verify both directions are present:

```bash
python -m factory.catalog equivalence-map --observable "<observable_name>" --format json
```

Expected: a list of `EquivalencePair`s including `simulator_id_a -> simulator_id_b` **and** `simulator_id_b -> simulator_id_a`. Spec 004 §4.3 inserts both directions.

If the partner simulator was not yet active when you onboarded this one, the harness skipped the row. After the partner is active, run:

```bash
python -m factory.catalog reindex
```

`reindex()` rebuilds the SQLite registry from the manifests on disk (spec 004 §5.5 step 6 and §6 `ManifestRegistryDrift`). Manifests are authoritative.

Finally, confirm `list_for_observable` returns the new entry:

```bash
python -m factory.catalog list --observable "<observable_name>"
```

### Step 10 -- Schedule periodic re-verification

`Catalog.reverify_all(max_age_days=30)` is meant to run on cadence (spec 004 §5.8). Add a cron job or CI scheduled workflow:

```
0 3 * * SUN  python -m factory.catalog reverify-all --max-age-days 30
```

If reverification finds smoke regression, base-image SHA mismatch, or license drift, the entry is quarantined -- the Selector will not return it, and any in-flight cycle that references it falls to G1.5 `parked_for_lack_of_tooling`.

---

## 3. Verification

For the entry to count toward PRD-004 acceptance:

- [ ] **Onboarding completed.** `python -m factory.catalog list --status active` includes the new `simulator_id`.
- [ ] **License audit clean.** `runs/catalog/<simulator-id>/<attempt-id>/license_audit.json` has `overall_verdict: "allow"` and `findings[].verdict` is `allow` for every node.
- [ ] **Reproducible build.** Two fresh rebuilds produce the same `image_sha`.
- [ ] **Smoke test green.** `last_smoke_test.passed: true`, `max_field_residual < global.max_field_residual`, `runtime_seconds <= 2 * expected_smoke_runtime_seconds`.
- [ ] **Manifest hash verified.** `python -m factory.catalog show --manifest <path> --verify-hash` exits 0.
- [ ] **mypy strict passes.** `mypy --strict factory/catalog/` is clean.
- [ ] **Cross-simulator equivalence map populated** (PRD-004 acceptance #2). At minimum one `EquivalencePair` exists across the active catalog with a historical agreement reference noted in `notes`.
- [ ] **Re-verification cron scheduled.** A CI or system cron entry calls `python -m factory.catalog reverify-all` weekly.
- [ ] **Documentation.** Manifest committed to `factory/catalog/manifests/<simulator-id>/` with `LICENSE`, `NOTICE`, `Dockerfile`, schemas, and smoke fixtures. The PR description references this runbook.

After the second entry is onboarded, run `python -m factory.catalog equivalence-map --observable "<observable_name>"` and capture the output in the PRD-004 acceptance evidence -- the entry pair is the precondition for the Phase A G4 cross-simulator check (`SPEC.md` §11 Phase A).

---

## 4. Troubleshooting

| Failure mode | Diagnosis | Recovery |
| :--- | :--- | :--- |
| `ManifestValidationError: extra fields not permitted` | A typo in a top-level key or a left-over field from an older schema version. | Open the manifest, diff against the template in step 2, remove unknown keys. Pydantic `extra="forbid"` is non-negotiable (spec 004 §3). |
| `ManifestValidationError: manifest_hash drift` | The hash you wrote does not match the canonical-JSON projection of the current content. | Recompute via `python -m factory.catalog show --compute-hash`. Never hand-edit the hash. |
| `ManifestValidationError: missing referenced file` | `dockerfile_path`, a schema, or a smoke input does not exist. | The harness resolves paths relative to the manifest directory; check spelling and case sensitivity. |
| `CatalogLicenseViolation: non-OSI license` on a node you believed was OSI | `declared_license` is not normalised to its SPDX ID; auditor's alias map missed it. | Update the manifest's node `license` to the canonical SPDX (e.g. `Apache-2.0`, not `Apache 2`). Spec 004 §5.2 step 3a does case-insensitive matching against the OSI snapshot, not free-text normalisation. |
| `CatalogLicenseViolation: redistribution_in_container=False` | A data file is marked non-redistributable. | The container must build with no external pulls (spec 004 §5.2 step 4). Either bundle a freely-redistributable equivalent or refuse the entry. |
| `ContainerBuildFailed: install-steps-hash mismatch` | The Dockerfile changed but the manifest's `install_steps_hash` was not updated. | Recompute the hash (step 4 above) and re-onboard. |
| `ContainerBuildFailed: timeout` | The build exceeded 2 hours (spec 004 §8). | Either speed the build up (cache layers, drop unused deps) or split the simulator into separate base-image and app-image manifests. There is no `--allow-long-build` knob and there should not be. |
| `ContainerBuildFailed: non-deterministic SHA` | The detection in step 8 caught a timestamp or ordering bug. | Add `--source-date-epoch=0`, `LANG=C.UTF-8`, sort `pip` requirements, pin wheel hashes. Do not register until determinism is verified. |
| `SmokeTestFailed: residual exceeded tolerance` | The image built but the output diverges from the reference. | Read `smoke.diff.json`. If a single field drifts, the simulator changed upstream -- pin a different version or re-derive the reference (and record why in `NOTICE`). Do **not** widen tolerances to silence the failure (spec 004 §6 recovery). |
| `SmokeTestFailed: extra fields` | The simulator's output schema added a field. | Update `output.schema.json` and `smoke/reference_output.<ext>` together; the schemas are checked into version control and travel as one unit. |
| `EntryQuarantined` after re-verification | Periodic smoke test failed or license drift detected. | Inspect `runs/catalog/<simulator-id>/<latest-attempt>/`. Patch the manifest and re-onboard from step 7; the prior entry stays quarantined as a historical record. |
| `ManifestRegistryDrift` | SQLite registry disagrees with manifests on disk. | Run `python -m factory.catalog reindex`. Manifests are authoritative; the registry is regenerated from them (spec 004 §5.5 step 6). |
| Build succeeds on dev laptop but fails in CI | Build context references files outside the manifest dir (Docker `..` paths) or relies on host packages. | Containers must build from `manifest_dir/context/` only -- spec 004 §5.3 step 3. Move any external inputs into the manifest tree. |
| `syft` reports an "unknown" license | The dep's metadata does not declare a license. | Manual research: read the upstream repo's `LICENSE` file, contact the maintainer if needed. Set `declared_license` to the actual SPDX ID. Do not commit `"UNKNOWN"`. |
| Equivalence pair was registered but `list_for_observable` returns only one entry | Partner entry is quarantined or deprecated. | `python -m factory.catalog show --simulator-id <partner-id>`; resurrect or replace the partner before claiming PRD-004 acceptance. |
| Catalog refuses to onboard a Phase B agent-drafted manifest | The Phase A/B distinction is *who clicked merge*, not a separate code path (spec 004 §5.9). | The agent's PR must still pass human review; the harness does not branch on origin. |
| Image build pulls from a non-pinned base | `base_image_sha` is a tag rather than a digest. | Replace with the resolved `sha256:...` digest. Tags are mutable; the harness rejects tag-only references (spec 004 §5.1). |

If none of these apply, read the spec failure table (spec 004 §6) verbatim, then `runs/catalog/<simulator-id>/<attempt-id>/events.jsonl` line by line. Every catalog operation emits a structured event; missing events mean a code path that should have logged was skipped.

---

## 5. Selecting the Initial Two Domains (Phase A only)

PRD-004 §10 makes the domain pair the operator's call, not the spec's. Use this decision flow exactly once, when you stand up the v1 catalog. Document the answer at the top of this runbook in the repo before you onboard the first entry.

1. **Team expertise.** Which physics domain do you (or the operators reviewing manifests) know cold? Manifest authoring takes 1-2 days per simulator; that cost doubles if you are also learning the domain. Pick a domain where you can defend the smoke-test reference output from memory.
2. **Open-source simulator density.** The primary domain must have **at least two** mature OSI-licensed simulators able to compute the *same observable*. If only one exists -- pick a different domain or fork a research-grade equivalent into a new manifest *before* onboarding. Spec 004 §1 makes this a hard precondition: without two cross-validatable entries, the Phase A G4 defense is missing.
3. **Public reference case.** A widely-published test case (a known textbook problem, a community benchmark, a peer-reviewed numerical study) for the chosen observable. The smoke-test reference output is uncontroversial only if it is independently citable. If you have to derive it yourself, you have to defend it yourself -- a future C5 audit will ask.
4. **Orthogonal domain choice.** The second (orthogonal) domain exists to enable a *different* cross-validation pair on a *different* observable, broadening the factory's substrate. It does not need its own mature pair on day one; it needs at least one entry that PRD-004 acceptance can extend. Pick the orthogonal domain to maximise the chance that future hypotheses cross over (e.g. a structural-mechanics primary plus a fluid-dynamics orthogonal lets the agent later propose fluid-structure-interaction hypotheses).
5. **Document the rationale.** Append a short paragraph to this runbook (or to a sibling `docs/runbooks/catalog-domain-selection.md` if you prefer) stating: the primary domain, the orthogonal domain, the shared observable for the primary pair, the literature reference for the smoke test, and the rationale for ruling out other candidates. PRD-004 §10 explicitly requires this rationale to be checked in.

If after this exercise you cannot identify a primary pair, the project is blocked on the Catalog -- escalate to the operator before writing any manifests.

---

## 6. Related

- **Spec backing this runbook:** `docs/specs/004-simulator-catalog.md` -- the full manifest schema, license auditor logic, build harness, and smoke runner.
- **Adjacent specs:**
  - `docs/specs/002-artifacts.md` -- `ArtifactHash` and `FactoryError` are reused by the manifest schema.
  - `docs/specs/005-simulator-selector.md` -- consumer; uses `equivalence_pairs()` for G4 cross-simulator routing.
  - `docs/specs/006-domain-adapter.md` -- each Catalog entry needs a Domain Adapter; spec 006 owns the abstract solver interface that maps to your simulator's actual API.
  - `docs/specs/009-validation-portfolio.md` -- reads the equivalence map at G4.
  - `docs/specs/015-operator-interface.md` -- defines the operator surface `factory catalog onboard`. Other steps in this runbook use the per-module CLI `python -m factory.catalog <subcommand>` per FIX_PLAN §9.2.
- **Adjacent runbooks:**
  - `docs/runbooks/first-cycle.md` -- depends on this runbook for the cross-simulator pair.
  - `docs/runbooks/council-calibration.md` -- a peer prerequisite for the first autonomous cycle; not directly related to catalog onboarding.
- **PRDs:**
  - `docs/prds/PRD-004-simulator-catalog-v1.md` -- this runbook's acceptance authority. PRD-004 §10 contains the domain-selection rules cross-referenced in §5 above.
  - `docs/prds/PRD-001-phase-a-mvp.md` -- broader Phase A envelope.
