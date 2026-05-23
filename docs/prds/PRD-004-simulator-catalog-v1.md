# PRD 004: Simulator Catalog v1 — 5–10 Hand-Curated Entries

> Status: ☐ not started · Owner: TBD · Target: Week 4 of Phase A

## 1. Goal

Ship a curated `SimulatorCatalog` containing 5–10 OSI-licensed open-source simulators across one primary domain plus one orthogonal cross-validation domain, with reproducible container builds and passing smoke tests. The Catalog is the substrate of the entire factory; nothing else runs until it exists.

## 2. Why Now

The factory's promise is "simulator-agnostic but bounded by what's open-source." The bound is the Catalog. Until v1 ships with at least two simulators that can cross-validate one shared observable, the G4 cross-simulator defense cannot fire, and the factory has no defense against single-simulator invariant hacking.

## 3. User Journey

The "user" is the Catalog onboarding engineer (initially, the operator). The journey per simulator:

1. Identify candidate simulator; verify OSI license + all-dependencies-OSI-or-redistributable.
2. Write the manifest YAML (see spec 004 for full schema).
3. Author the Dockerfile + dependency lockfile.
4. Define a smoke-test target (known-good problem with known output).
5. Run `catalog onboard <manifest.yaml>`:
   - System builds the container.
   - Runs the smoke test inside.
   - Compares output to the expected reference within tolerance.
   - On pass: writes the entry to the Catalog database, populates dependency-graph + cross-simulator-equivalence map.
   - On fail: reports the failure mode, leaves the entry in `pending` state.
6. Re-run smoke tests periodically (CI cron).

## 4. Success Metrics

| Metric | Threshold |
| :--- | :--- |
| Number of entries in Catalog v1 | ≥ 5, ≤ 10 |
| Number of OSI-licensed simulators in primary domain | ≥ 2 (enables cross-simulator validation) |
| All entries pass smoke test on a clean build host | yes |
| All entries have full dependency-graph license audit | yes |
| At least one cross-simulator equivalence map populated for one observable | yes |
| Median container build time | ≤ 15 minutes (with cache warm) |
| All container images are reproducible (same Dockerfile → same SHA) | yes |

## 5. Scope

### In scope

- 5–10 hand-curated entries across two domains.
- Manifest schema implementation (spec 004).
- Container build harness with caching.
- Smoke-test runner.
- License auditor: dependency-graph traversal verifying OSI compatibility of every transitive dependency.
- Cross-simulator equivalence map for at least one shared observable.

### Out of scope

- Autonomous Catalog onboarding (Phase C).
- More than 10 entries (Phase B grows to ~30).
- Cross-simulator validation across multiple observables in different domains (Phase B).

## 6. Deliverables

| Deliverable | Spec | Notes |
| :--- | :--- | :--- |
| `SimulatorCatalog` manifest schema (JSON Schema + Pydantic models) | `specs/004-simulator-catalog.md` | Authoritative source. |
| `catalog onboard` CLI command | `specs/004-simulator-catalog.md` | Builds + smoke-tests + persists. |
| License auditor utility (`catalog audit-license <entry>`) | `specs/004-simulator-catalog.md` | Traverses dependency graph. |
| 5–10 manifest YAML files | `specs/004-simulator-catalog.md` | One per entry, checked into repo. |
| Smoke-test reference data | `specs/004-simulator-catalog.md` | Known-good outputs per entry. |
| Container image registry (local or self-hosted) | `specs/004-simulator-catalog.md` | Persists built containers; cached by manifest hash. |

## 7. Risks & Mitigations

| Risk | Severity | Mitigation |
| :--- | :--- | :--- |
| A nominally OSI-licensed simulator has a non-redistributable runtime dependency | High | License auditor MUST traverse the full dependency graph; fail-loud at onboarding, no exceptions. |
| Container build flakiness (network, transient package mirrors) | Medium | Pin all dependency versions in lockfiles; cache base images; retry with backoff. |
| Smoke-test reference output drifts upstream | Medium | Pin upstream simulator version per entry; require explicit re-onboarding to update reference. |
| Cross-simulator equivalence map is hard to verify (definitions of "same observable" differ) | High | For v1, define the equivalence narrowly (one specific observable, one specific test case); expand later. |
| Catalog onboarding takes longer per entry than expected | Medium | Allocate 1–2 days per entry; do not block on perfect manifests, ship incremental. |

## 8. Acceptance Criteria

- [ ] Catalog has ≥5 entries with all smoke tests passing.
- [ ] At least one cross-simulator equivalence pair documented with at least one historical agreement measurement.
- [ ] License auditor has run on every entry; all clear.
- [ ] `SimulatorSelector` (spec 005) can query the Catalog and return ranked candidates for at least three distinct hypothesis classes.
- [ ] Container builds are reproducible (test: rebuild on a clean host yields same image SHA).
- [ ] Documentation: `docs/runbooks/catalog-onboarding.md` written so a new operator can onboard an entry without reading source code.

## 9. Linked Specs

- `specs/004-simulator-catalog.md` — schema + onboarding logic.
- `specs/005-simulator-selector.md` — consumer; needs the Catalog to be queryable.
- `specs/006-domain-adapter.md` — adapter implementation per entry.

## 10. Selecting the Initial Two Domains

The choice of primary domain + orthogonal cross-validation domain is **not** specified in this PRD — it is a decision the operator makes based on:

1. Personal/team expertise (so manifest authoring is fast).
2. Existence of ≥2 mature OSI-licensed simulators able to compute *the same observable*.
3. Existence of a public test case widely published so smoke-test reference output is uncontroversial.

The pairing must enable cross-simulator validation from day one. If only one OSI-licensed simulator exists in the candidate primary domain, the operator selects a different domain or expands the Catalog with a research-grade fork *before* PRD-004 closes.

Document the selection in `docs/runbooks/catalog-onboarding.md` §1 with rationale.
