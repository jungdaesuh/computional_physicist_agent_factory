# FIX_PLAN.md — Canonical Resolutions From Crucible Phase 1

This document is the **single source of truth** for every cross-spec contract decision that the Crucible doc review surfaced. Every fixer agent references this when editing specs, runbooks, PRDs, or top-level docs. After fixes land, this file is archived (not deleted) so the resolution rationale is preserved.

> Status: ACTIVE during fix wave · Last updated: 2026-05-23

---

## 1. Typed Artifacts — canonical list is **eleven**, not eight

The artifact registry in `factory/artifacts/` (spec 002) ships **eleven** typed artifacts. Every doc that says "eight" must be updated.

| # | Artifact | Producer | Consumers |
| ---: | :--- | :--- | :--- |
| 1 | `GapCandidate` | spec 007 Gap Miner | spec 003 (G0), spec 001 (C1) |
| 2 | `HypothesisSpec` | spec 003 after C1 | spec 003 (G1.5+), spec 005, spec 009 |
| 3 | `CouncilVerdict` | spec 001 | spec 003, spec 011 (embeds in RunReport) |
| 4 | `ExperimentSpec` | spec 003 after C2 | spec 005, spec 006, spec 008, spec 009 |
| 5 | `Budget` | spec 003 at cycle start | spec 013 tracker reads/updates |
| 6 | `DomainScope` | operator config | spec 003 (G0 check), C5 mutates |
| 7 | `EvidenceLedgerEntry` | spec 003 at cycle terminal | spec 010 (training data), spec 011 (RAG) |
| 8 | `RunReport` | spec 011 RAG writer | spec 003 (G6), spec 015 (approval CLI) |
| 9 | **`ValidationResult`** *(NEW)* | spec 009 G4 portfolio | spec 003 (G4 routing), spec 011 (embeds) |
| 10 | **`SurrogateProbeResult`** *(NEW)* | spec 010 surrogate | spec 003 (G3 routing) |
| 11 | **`FactoryControlEvent`** *(NEW)* | spec 015 mutation CLI | spec 003 (pause/resume/approve handler) |

**Naming:** The 7th artifact is `EvidenceLedgerEntry`. The class `Ledger` (spec 012) is the storage backend, **not** an artifact. Drop every reference to a class called `EvidenceLedger`.

---

## 2. GateOutcome enum — canonical set is **seven**, not five

Per spec 003 §3, `GateOutcome` extends to:

```python
class GateOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    QUALIFIED = "qualified"
    PARKED = "parked"
    INTRACTABLE = "intractable"
    INCONCLUSIVE = "inconclusive"        # NEW — used by G4 when cross-sim absent and refinement non-decisive
    OOD_ESCALATION = "ood_escalation"    # NEW — used by G3 when surrogate flags OOD candidate
```

**Routing implications.** Replace these undefined route targets in `gate_routes.yaml`:

| Old (undefined) | New (canonical) |
| :--- | :--- |
| `G2.5_with_intensified_validation` | `G2.5` (same gate; the intensified-validation flag is carried on `HypothesisSpec.qualified_track: bool` set when C1 issued `qualified`) |
| `G4_oracle_only` | `G4` (the OOD-escalation outcome from G3 carries a `skip_surrogate: True` metadata flag read by G4) |

Loops still forbidden; route validator stays as a DAG check.

---

## 3. Chairman decision and EvidenceResult mapping

### 3.1 `chairman_decision` has **four** values

Per spec 002 + spec 001:

```python
chairman_decision: Literal["approve", "reject", "qualified", "no_consensus"]
```

Spec 003 (consumer at C5 and as a generic council-verdict consumer) must handle **all four**:

- `approve` → apply the council's recommendation (e.g., update DomainScope).
- `reject` → no state change.
- `qualified` → apply with `qualified_track=True` flag on downstream artifact.
- `no_consensus` → no state change; flagged for operator attention via telemetry event.

### 3.2 Terminal → `EvidenceResult` mapping

Spec 003 §5.4 must include this canonical table:

| Terminal state | `EvidenceResult` value | Notes |
| :--- | :--- | :--- |
| `terminate_published_internal_only` | `passed` | Internal Ledger entry created; no external pub. |
| `terminate_published_external` | `passed` | Internal + external (G6 approved). |
| `terminate_falsified` | `falsified` | Result published as negative. |
| `terminate_intractable` | `intractable` | Budget exhausted or G2.5 dry-run failed. |
| `terminate_inconclusive` | `inconclusive` | G4 portfolio returned inconclusive OR C4 weak. |
| `terminate_discarded` | `inconclusive` | G1/G2 rejected; minimal Ledger entry for audit. |
| `terminate_parked_for_scope_expansion` | `inconclusive` | G0 rejected; parked for C5. |
| `terminate_parked_for_lack_of_tooling` | `inconclusive` | G1.5 rejected; parked for Catalog growth. |
| `terminate_dedup_skip` | `inconclusive` | G0 found identical prior; no re-run. |

`EvidenceResult` enum stays at `{passed, falsified, intractable, inconclusive}` — four values. The terminal granularity is captured by `EvidenceLedgerEntry.terminal_state` (string field), separate from `result`.

---

## 4. Catalog API — single source of truth

Spec 004 `Catalog` class exposes exactly:

```python
class Catalog:
    def get(self, simulator_id: SimulatorId) -> CatalogEntry: ...
    def list_entries(self, status: EntryStatus = EntryStatus.ACTIVE) -> list[CatalogEntry]: ...
    def list_for_observable(self, observable: ObservableName) -> list[CatalogEntry]: ...
    def equivalence_pairs(self, observable: ObservableName) -> list[EquivalencePair]: ...
    def version_hash(self) -> str: ...                     # NEW — content hash of catalog state
    @classmethod
    def mock_factory(cls, root: Path) -> "Catalog": ...
    @classmethod
    def from_fixture(cls, name: str) -> "Catalog": ...     # NEW — alias for mock_factory by name
```

**Selector (spec 005) must use these exact names** — drop `find_by_observable`, `get_cross_simulator_map`, `entries()`.

`CatalogEntry.capabilities` exposes `computed_observables` (list of `ObservableName`), not `observables`.

Type aliases exported from `factory.catalog`: `SimulatorId`, `ManifestHash`, `ImageSha`, `ObservableName`, `CatalogVersionHash` (NEW — alias for the content hash). Drop `CatalogEntryId` (it's just `SimulatorId`).

---

## 5. License enum — split OSI-approved from carve-outs

Spec 004 currently mislabels CC0/CC-BY/Public-Domain as OSI-approved. Resolution: split into two enums.

```python
class OsiApprovedLicense(str, Enum):
    # OSI-approved software licenses only. Verified at https://opensource.org/licenses
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
    AGPL_3 = "AGPL-3.0-only"             # NEW
    AGPL_3_PLUS = "AGPL-3.0-or-later"    # NEW
    MPL_2 = "MPL-2.0"
    ISC = "ISC"
    EPL_2 = "EPL-2.0"                    # NEW
    EUPL_1_2 = "EUPL-1.2"                # NEW
    CDDL_1_0 = "CDDL-1.0"                # NEW

class CarveOutLicense(str, Enum):
    # Allowed for data/asset files only, never for code dependencies.
    CC0_1_0 = "CC0-1.0"
    CC_BY_4_0 = "CC-BY-4.0"
    PUBLIC_DOMAIN = "Public-Domain"

LicenseId = OsiApprovedLicense | CarveOutLicense
```

The license auditor's "academic use only" phrase scan (spec 004 §5.2 step 3d) operates on **license file contents** (the raw LICENSE text attached to the manifest), not SPDX IDs. SPDX IDs are checked at step 3a-c against the enum allowlist.

---

## 6. Budget API — single canonical surface

### 6.1 Tracker, not artifact, owns behavior

`Budget` is a **frozen Pydantic artifact** carrying caps; `BudgetTracker` is the live module that records spends. Spec 008 must:

- Never call `budget.record_entry(...)` or `budget.dollar_remaining`.
- Always go through `tracker = BudgetTracker(budget)` then `tracker.record(...)` / `tracker.remaining()`.

### 6.2 Three tiers, not four

Tiers: `per_hypothesis`, `per_day`, `aggregate`. There is no `per_cycle` tier (a cycle = a hypothesis traversal in Phase A).

`cmd_budget_set` (spec 015) signature drops `per_cycle_usd`:

```python
def cmd_budget_set(
    aggregate_usd: float | None = None,
    per_hypothesis_usd: float | None = None,
    daily_usd: float | None = None,
) -> int: ...
```

### 6.3 CLI name

Canonical: `factory budget set` (operator CLI in spec 015) AND `python -m factory.budget set-cap` (per-module CLI in spec 013). Operator CLI is `set` (short); per-module CLI is `set-cap` (explicit). Both invoke the same `BudgetTracker.set_cap(...)` underneath. Runbooks pick the operator CLI form.

### 6.4 BudgetTokenUsageMissing

Rename `BudgetUnknownCost` → `BudgetTokenUsageMissing`. Spec 013 also documents:

- Vendors do not return USD; tokens only.
- Council library (spec 001) computes USD via `pricing_table.lookup(model_id, kind) * tokens` and passes USD to `tracker.record(cost_usd=...)`.
- Pricing table location: `config/pricing/<vendor>.yaml`. Schema documented in spec 013 §4.

### 6.5 Iteration cap

`iterations` field on `CapSet` is only valid for `per_hypothesis`. The data model expresses this via separate dataclasses:

```python
@dataclass(frozen=True)
class HypothesisCaps:
    dollars: float
    tokens: int
    wall_clock_seconds: float
    iterations: int

@dataclass(frozen=True)
class TimeWindowCaps:
    dollars: float
    tokens: int
    wall_clock_seconds: float
```

Per-day and aggregate use `TimeWindowCaps`.

---

## 7. Sandbox directory layout — single canonical scheme

Per-cycle sandbox layout (used by specs 006 + 008 + 009):

```
runs/<cycle-id>/sandbox/
├── <iteration:03d>/                      # 000, 001, 002, ... (one per generator-verifier iteration)
│   ├── code.py                           # the proposed solver code for this iteration
│   ├── diff.patch                        # diff vs. previous iteration
│   ├── stdout.log
│   ├── stderr.log
│   └── adapter_outputs/                  # populated by the domain adapter (spec 006)
│       └── <seed>/                       # one subdirectory per seed in ExperimentSpec.seed_set
│           ├── run_artifacts.json        # RunArtifacts (spec 006 §4) — the canonical adapter output
│           ├── observables.json
│           └── diagnostics.json
```

Spec 006 paths (`<simulator_id>/<seed>/`) are deprecated; the simulator identity is implicit in the parent cycle's `ExperimentSpec.simulator_id`.

`wipe_staging(run_dir/sandbox/)` (spec 008) wipes only `adapter_outputs/` subtrees on rollback, preserving per-iteration code + diffs + logs for forensics.

---

## 8. Event taxonomy — extensible namespace, not closed set

Spec 014 redefines the taxonomy as **extensible by namespace**:

- Closed set of **module namespaces**: `factory.council`, `factory.catalog`, `factory.selector`, `factory.adapter`, `factory.literature`, `factory.genver`, `factory.validation`, `factory.surrogate`, `factory.writer`, `factory.ledger`, `factory.budget`, `factory.telemetry`, `factory.operator`, `factory.state_machine`, `factory.artifacts`.
- Each module is free to emit events under its namespace (`factory.<module>.<event_name>`) **provided the event name is declared in that module's `events.py`** (per the canonical module template).
- Aggregator reads the registered event names from each module at startup.
- `EventTaxonomyViolation` fires when emit() is called with an event name not registered by the namespace's `events.py`.

**Required events that must be registered:**

- `factory.genver.iteration_start`, `.iteration_end`, `.sandbox_open`, `.sandbox_exit`, `.promote_attempt`, `.promote_succeeded`, `.promote_failed`
- `factory.ledger.entry_inserted`, `.trigger_check_failed`, `.evaluate_triggers_complete`
- `factory.surrogate.evaluated`, `.ood_escalation`, `.retrain_started`, `.retrain_complete`
- `factory.budget.cap_warning`, `.cap_exhausted`, `.aggregate_halt`
- `factory.state_machine.gate_enter`, `.gate_exit`, `.cycle_complete`
- Plus the per-spec events already registered.

---

## 9. CLI surface — operator vs per-module

Two surfaces, both valid, with explicit prefixes:

| Surface | Invocation | Audience | Spec |
| :--- | :--- | :--- | :--- |
| Operator CLI | `factory <subcommand>` | Day-to-day operator | spec 015 |
| Per-module CLI | `python -m factory.<module> <subcommand>` | Module-internal debugging | each module spec |

### 9.1 Canonical operator CLI subcommands (spec 015 §2)

```
factory start [--seed TOPIC] [--cycles N] [--daily-cap-usd USD] [--mock-mode]
factory stop
factory pause
factory resume
factory status
factory inspect <hypothesis-id> [--format text|json]
factory discover --seed "<topic>"
factory replay <cycle-id> [--dry-run] [--format text|json] [--mock-mode]
factory approve <run-report-hash>
factory reject <run-report-hash> --reason "<text>"
factory catalog onboard <manifest.yaml>
factory council calibrate
factory budget show
factory budget set --aggregate-usd USD [--per-hypothesis-usd USD] [--daily-usd USD]
factory serve [--host HOST] [--port PORT]              # NEW — starts the read-only HTTP API
```

Global flags: `--mock-mode`, `--quiet`, `--verbose`, `--config-dir PATH`. Add all four to spec 015 §3.

### 9.2 Per-module CLI subcommands

- `factory.council`: `deliberate`, `calibrate`, `show-session`, `show-lineup`, `show-report`, `promote-calibration`
- `factory.catalog`: `onboard`, `audit-license`, `build`, `smoke`, `list`, `show`, `equivalence-map`, `quarantine`, `reverify-all`
- `factory.ledger`: `query`, `audit`, `export`, `verify-chain`, `evaluate-triggers`
- `factory.budget`: `show`, `breakdown`, `set-cap`, `reset-day`, `simulate`, `clear-halt`
- `factory.state_machine`: `run-cycle`, `replay`, `inspect`, `step`, `submit-gaps`, `run-gate`, `validate-routes`, `force-terminate`
- `factory.artifacts`: `validate`, `hash`, `show`, `verify-chain`, `emit-schemas`
- `factory.tooling`: `scaffold-module`, `lint-specs`, `lint-runbooks`

Runbooks use the operator CLI for normal operations and per-module CLI for debugging. Spec runbook references must match.

---

## 10. Config + persistence paths

| Item | Canonical path |
| :--- | :--- |
| Council lineup config | `config/council/lineup.yaml` |
| Council personas | `config/council/personas/{visionary,pessimist,pragmatist}.md` |
| Council calibration probes | `config/council/probes.yaml` |
| Pricing tables | `config/pricing/<vendor>.yaml` |
| Gate routes | `config/state_machine/gate_routes.yaml` |
| Per-gate config | `config/state_machine/gates/<gate>.yaml` |
| Operator config | `config/operator.yaml` |
| EvidenceLedger DB | `runs/ledger.db` |
| Per-cycle root | `runs/<cycle-id>/` |
| Per-cycle event log | `runs/<cycle-id>/cycle.jsonl` |
| Per-cycle council sessions | `runs/<cycle-id>/councils/<session_id>.jsonl` |
| Per-cycle artifacts | `runs/<cycle-id>/artifacts/<hash>.json` |
| Aggregate halt sentinel | `runs/_control/HALT_AGGREGATE_CAP` |
| Control events (operator mutations) | `runs/_control/events/<ts>.json` |
| Paper Store | `runs/_paper_store/<work_id>/` |
| Calibration reports | `runs/_calibration/<ts>/report.json` |

Drop `council/sessions/...` (legacy from spec 001 — overridden by the canonical per-cycle path).

---

## 11. Environment variables

| Variable | Purpose | Required? |
| :--- | :--- | :--- |
| `ANTHROPIC_API_KEY` | Council live mode | yes |
| `OPENAI_API_KEY` | Council live mode | yes |
| `GOOGLE_API_KEY` | Council live mode | yes |
| `XAI_API_KEY` or `OPENROUTER_API_KEY` | 4th council vendor | yes |
| `OPENALEX_MAILTO` | OpenAlex polite-pool email | recommended |
| `OPENALEX_API_KEY` | Higher OpenAlex rate limit | optional |
| `FACTORY_MOCK` | Force mock mode | no |
| `FACTORY_CONFIG_DIR` | Override config dir | no |

Drop `OPENALEX_EMAIL` — use `OPENALEX_MAILTO` everywhere.

---

## 12. Onboarding ramp time — canonical is **40 minutes**

ARCHITECTURE.md §1.10 currently says "60 minutes" in the title and "40 minutes" in the breakdown summary. Resolution: drop "60 minutes" everywhere. The ramp is:

1. `INDEX.md` quick read — 5 min
2. `ARCHITECTURE.md` §1 + §3 read — 10 min
3. Target spec read — 15 min
4. Mock-mode run — 5 min
5. First productive edit + green test — 5 min

Total: **40 minutes**. Update ARCHITECTURE.md §1 line 5, §1.10 line 74, INDEX.md §0/§2.

---

## 13. Artifact hashing — canonical JSON without NaN

Spec 002 §5.1 canonical-JSON serializer must:

- Set `allow_nan=False` in `json.dumps`. NaN/Infinity raise at serialize time, surfacing the upstream physics bug instead of producing an unparseable artifact.
- Document that the format approximates RFC 8785 but is not strictly compliant. Cite the deviation (float representation may vary subtly across Python versions for subnormal numbers).
- Recommend that producer modules sanitize NaN/Infinity *before* constructing the artifact (G4 validation portfolio handles this — if a residual is NaN, validation already fails, so no NaN reaches Ledger).

`ArtifactHash` adds runtime regex validation:

```python
class ArtifactHash(str):
    _PATTERN = re.compile(r"^[0-9a-f]{64}$")

    def __new__(cls, value: str) -> "ArtifactHash":
        if not cls._PATTERN.match(value):
            raise ArtifactValidationError(f"invalid hash format: {value!r}")
        return super().__new__(cls, value)
```

(Or equivalent Pydantic `StringConstraints(pattern=...)` typed alias.)

---

## 14. Untyped dict at module boundary — promote to typed schemas

ARCHITECTURE.md §1.5 bans `dict` at module boundaries. Spec 002 §3 violations to fix:

- `ExperimentSpec.control_definition: dict` → `ControlDefinition` Pydantic model with at minimum `{baseline_simulator_id: SimulatorId, baseline_config: dict[str, str | int | float | bool]}` and an explicit per-simulator-family extension point.
- `EvidenceLedgerEntry.uncertainty: dict` → `UncertaintyBlock` Pydantic model with `metric_name`, `point_estimate`, `ci_lower`, `ci_upper`, `ci_method: Literal["t_interval", "bootstrap", "bca"]`, `n_seeds`.

(Other `dict` fields tolerated only at strict configuration boundaries where the schema is intentionally extensible — must be flagged with comment + dataclass for typed value.)

---

## 15. Validation Portfolio (G4) — math corrections

Spec 009 must:

### 15.1 Richardson with variable refinement ratio

Replace:
```python
f_extrap = f_fine + (f_fine - f_mid) / (2**p_obs - 1)
```
With:
```python
r = h_mid / h_fine  # actual refinement ratio
f_extrap = f_fine + (f_fine - f_mid) / (r**p_obs - 1)
```

Plus a **monotonic-convergence check** before computing `f_extrap`:
```python
R = (f_mid - f_fine) / (f_coarse - f_mid)
if not 0 < R < 1:
    return "Richardson NOT applicable: non-monotonic convergence"
```

### 15.2 Conservation tolerances carry `kind`

```python
class ConservationTolerance(BaseModel):
    model_config = ConfigDict(frozen=True)
    invariant: str
    threshold: float
    kind: Literal["absolute", "relative"]

# Per-domain config:
conservation_tolerances: list[ConservationTolerance]
```

### 15.3 Add CFL / temporal-stability check

New G4 sub-check `_check_cfl(experiment, run)`:
- If the simulator manifest declares `time_dependent: True`, the validator pulls `dt`, `dx_min`, `v_max` from `run_artifacts.diagnostics` and verifies `dt * v_max / dx_min ≤ cfg.cfl_max` (default 0.5 for advection, 0.25 for diffusion). Configurable per-domain.
- For time-independent simulators (equilibrium codes), this check is skipped with explicit `skipped: True` and rationale.

### 15.4 ∇·B = 0 dichotomy

In the `stellarator-mhd` domain config, replace `div_B` with **`force_balance`** as the primary check. The validator reads `run_artifacts.diagnostics.force_balance_residual` (the J×B − ∇p residual) and applies the tolerance. A `div_B` check remains as a secondary smoke test labeled "structurally trivial for vector-potential codes" in the spec.

### 15.5 Statistical check resolution

- `min_seeds` default **stays at 3** but the spec acknowledges this gives poor power; an additional config knob `recommended_seeds: int = 10` is documented as the Phase B target.
- CI method is `bootstrap` by default (not t-interval). t-interval is opt-in via `ci_method: Literal["bootstrap", "t_interval"]` on the per-domain config.
- Dispersion check uses `|std|` (absolute) when `|mean| < cfg.near_zero_threshold`, else `std/|mean|` (relative). Both branches documented.

### 15.6 tolerance_kind="mixed"

Two scalars required: `tolerance_relative: float` and `tolerance_absolute: float`. The mixed test is `|delta| < max(tolerance_relative * |reference|, tolerance_absolute)` per ASME V&V 20.

```python
class EquivalencePair(BaseModel):
    ...
    tolerance_kind: Literal["relative", "absolute", "mixed"]
    tolerance_relative: float | None = None
    tolerance_absolute: float | None = None

    @model_validator(mode="after")
    def _check_tolerances(self) -> "EquivalencePair":
        if self.tolerance_kind == "mixed":
            if self.tolerance_relative is None or self.tolerance_absolute is None:
                raise ValueError("mixed kind requires both relative and absolute tolerances")
        return self
```

### 15.7 Finite-precision floor

Effective tolerance = `max(prescribed_tol, cfg.precision_floor)` where `precision_floor` is per-domain (default `1e-15` for float64 codes, `1e-7` for float32 codes). Documented in spec 009 §5.1.

---

## 16. Council math corrections

Spec 001 §5.4 sycophancy detection:

- **Statistic:** `max` pairwise cosine similarity (catches groupthink-with-dissenter), not `mean`. Document that mean dilutes the signal in the very scenario the check is meant to catch.
- **Pair count:** explicit `N*(N-1)/2` unordered pairs, excluding self-pairs. Add a worked example for N=4.
- **Embedding model:** pin to `sentence-transformers/all-mpnet-base-v2` (open-weight, local, vendor-agnostic, well-calibrated cosine scale). Document the threshold 0.85 is calibrated against this model.

Spec 001 §5.3 step 5 — dissent omission:

- Use an NLI (entailment/contradiction) model, not cosine similarity. Pin to `sentence-transformers/cross-encoder/nli-deberta-v3-base` or equivalent. Threshold: dissent omission fires when any first-opinion's stance is classified `contradiction` relative to `majority_view` AND that stance is absent from `preserved_dissents`.

Spec 001 session log path: `runs/<cycle-id>/councils/<session_id>.jsonl` (matches ARCHITECTURE §1.4). Drop `council/sessions/`.

---

## 17. Surrogate (spec 010) — OOD dimensionality

Add to spec 010 §5.4:

- Document curse-of-dimensionality for Mahalanobis distance in high-d (~80 features for ConStellaration-style problems).
- Default OOD detector is **kNN distance with k=5** in *reduced feature space* (PCA to dimension ≤ 20) for Phase A. Mahalanobis is opt-in for low-d feature sets.
- `ood_threshold_percentile` semantics: the threshold value is the `p`-th percentile of the *training-set leave-one-out kNN distance* distribution. Document that this hardcodes the false-positive rate at `1 - p`.
- Field name is `ood_threshold_percentile` everywhere (drop `ood_threshold_value`).

---

## 18. OpenAlex API surface (spec 007)

- Endpoint for forward citations: `/works?filter=cites:<work_id>` (canonical). Drop `cited_by_api_url` from the prose — it's a derivable URL pattern, not a Work-object field.
- `is_oa` filter parameter is `is_oa=true` (top-level filter); within Work response, the field is `open_access.is_oa` (nested under `open_access`). Document the dual representation.
- Pin `OPENALEX_MAILTO` (not `OPENALEX_EMAIL`).
- Export `PaperStore` class from `factory.literature` public API. Define its public interface in §3 (`.query(...)`, `.get(work_id)`, `.get_bibtex(work_id)`, `.has_bibtex(work_id)`, `.promote(work_ids)`, plus mock).

---

## 19. PRD reconciliations

### 19.1 PRD-001 dollar cap

PRD-001 §4 success metric: **per-hypothesis ≤ $50**. Spec 013 default `per_hypothesis.dollars` is set to **$50** to match (drop the $20 default). The operator can lower locally; $50 is the canonical Phase A acceptance ceiling.

### 19.2 PRD-001 §8 acceptance list

Add specs **014 and 015** to the acceptance criteria list. The full list is 001–015 (all 15 Phase A specs).

### 19.3 PRD-002 paths

PRD-002 §6 deliverables: every path becomes `factory/council/...` (not bare `council/`). PRD-002 CLI examples become `python -m factory.council deliberate ...` and `python -m factory.council calibrate` (per-module form for the standalone library).

### 19.4 PRD-003 cross-references

PRD-003 §7 Risks: per-gate timeout caps live in **spec 003 §8**, not spec 013.

---

## 20. Top-level docs

### 20.1 INDEX.md §2 top-level table

Must list all 7 top-level docs:

| Doc | Purpose |
| :--- | :--- |
| `SPEC.md` | Canonical architectural specification |
| `ARCHITECTURE.md` | Modularity invariants + canonical module template |
| `INDEX.md` | This file — navigation + onboarding + status |
| `ORCHESTRATION.md` | Subagent orchestration playbook |
| `GLOSSARY.md` | Authoritative term definitions |
| `DIAGRAMS.md` | Mermaid diagrams (dependency, gates, councils, lineage) |
| `UI_DESIGN.md` | 11 UI screen prompts |

### 20.2 SPEC.md updates

- §2 artifact list: **eleven** entries (add ValidationResult, SurrogateProbeResult, FactoryControlEvent).
- §2 CouncilVerdict fields: drop `dissent_rationales[]` (rationales are inside each `DissentEntry`).
- §6.2: drop `cited_by_api_url`.
- gap_type values: **underscored** (`structural_hole`, `methodology_transfer`, `contradiction`, `negative_result`) everywhere.

### 20.3 ORCHESTRATION.md

§5 Wave 1 verification: `python -m factory.tooling lint-specs` is documented as **TBD** in §5 and **also** in §9 (the quick-reference must say "TBD until Wave 2 W2-B lands"). No silent promise of an existing command.

§9 Quality Gates: only commands that exist (or are clearly marked TBD) appear.

---

## 21. Runbook canonical command patterns

All runbooks must use:

- Operator CLI form (`factory <subcommand>`) for normal operations.
- Per-module CLI form (`python -m factory.<module> <subcommand>`) for debugging.
- Mark `[TBD-impl]` for any command not yet documented in spec 015 OR the relevant module spec (per §9 above).

All runbook ENTRY POINTS references in specs must use the **actual** runbook filenames:

| Spec | Wrong | Right |
| :--- | :--- | :--- |
| 005 | `selector-debugging.md` | `[no runbook yet]` (mark TBD or write it) |
| 006 | `adding-a-domain-adapter.md` | `adapter-writing.md` |
| 007 | `literature-traversal.md` | `literature-discovery.md` |
| 009 | `validation-portfolio.md` | `validation-debugging.md` |
| 010 | `surrogate-retraining.md` | `surrogate-training.md` |
| 011 | `rag-writer.md` | `writer-debugging.md` |
| 013 | `budget-operations.md` | `budget-tuning.md` |
| 014 | `telemetry-export-and-audit.md` | `telemetry-export.md` |
| 015 | `operator-quickstart.md` | `operator-cli.md` |

---

## 22. Open issues deferred to Phase B (not fixed in this wave)

- Schema versioning across artifact types (frozen at v1 for Phase A).
- Cross-cycle artifact deduplication (one file per hash globally).
- Compression at rest for artifacts.
- Multi-cycle concurrent execution.
- Pricing-table auto-update from vendor APIs.
- Surrogate retraining automation.
- C5 expansion criteria automation.

These are explicitly out-of-scope for the current fix wave.

---

## 23. Application order

Recommended order for fixers (most can run in parallel since they own disjoint files):

1. **First (sequential):** spec 002 (artifacts) — every other spec references the artifact set.
2. **Then (parallel):** specs 001, 003, 004, 005, 006, 007, 008, 009, 010, 011, 012, 013, 014, 015.
3. **Then (parallel):** PRDs, top-level docs (INDEX/ARCHITECTURE/SPEC/GLOSSARY/ORCHESTRATION), UI_DESIGN (minor; mostly leave alone).
4. **Then (parallel):** runbooks (CLI invocations, paths, env vars).
5. **Then (audit):** Phase 4 dialectical re-read.

---

## 24. AMENDMENT (2026-05-23) — Single-vendor LLM constraint: Gemini 3.5 Flash only

The factory uses a **single LLM**: `gemini-3.5-flash` via the Google Gemini API. Every previous reference to multi-vendor LLM access (Claude, GPT-5, xAI, OpenRouter, open-weight) is superseded by this amendment.

### 24.1 Canonical LLM facts

| Item | Value |
| :--- | :--- |
| Provider | Google Gemini API (`https://ai.google.dev/gemini-api`) |
| Model ID | `gemini-3.5-flash` |
| SDK | `google-genai` Python package (`from google import genai`) |
| API key env var | `GEMINI_FLASH` (single key, read from operator shell) |
| Context window | 1M tokens |
| Max output | 65k tokens |
| Sampling parameters | **DEFAULTS ONLY.** Per Google guidance, `temperature` / `top_p` / `top_k` are NOT varied from default values. |
| Structured outputs | Supported via `response_schema` / JSON mode (use for `CouncilVerdict` parsing). |
| System instruction | Supported (used for persona prompts). |
| Multi-turn chat | Supported (council stages use independent single-turn calls, not chat). |
| Reference docs | https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5 |

### 24.2 Canonical Python invocation pattern

```python
from google import genai
import os

_CLIENT = genai.Client(api_key=os.environ["GEMINI_FLASH"])

def call_gemini(system_instruction: str, user_content: str) -> "GeminiResponse":
    """Single call. No temperature override per Google guidance. Returns text + usage."""
    response = _CLIENT.models.generate_content(
        model="gemini-3.5-flash",
        contents=[user_content],
        config=genai.types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",  # when structured output is required
            # No temperature / top_p / top_k — defaults only per upstream guidance.
        ),
    )
    return GeminiResponse(
        text=response.text,
        input_tokens=response.usage_metadata.prompt_token_count,
        output_tokens=response.usage_metadata.candidates_token_count,
    )
```

### 24.3 Council architecture change — heterogeneity redefined

**The previous "≥4 distinct vendors" requirement is dropped.** The council now uses **≥4 independent calls to `gemini-3.5-flash`, each under a distinct persona prompt**. Persona heterogeneity is the entire source of disagreement; vendor heterogeneity no longer exists.

`ModelSpec` is replaced with a simpler shape:

```python
@dataclass(frozen=True)
class CouncilCall:
    persona: PersonaName          # Visionary | Pessimist | Pragmatist
    system_instruction: str       # rendered from config/council/personas/<persona>.md
    timeout_s: float = 60.0
    max_output_tokens: int = 4096

@dataclass(frozen=True)
class CouncilLineup:
    calls: Sequence[CouncilCall]   # ≥4 required; ≥3 distinct personas required
    chairman_persona: PersonaName  # which persona acts as chairman in stage 3
```

The 4+ council calls span 3 personas. A typical lineup is 2 × Visionary + 2 × Pessimist + 2 × Pragmatist (6 calls) or the leaner 1 × Visionary + 2 × Pessimist + 1 × Pragmatist (4 calls). The Pessimist persona is over-weighted because RLHF flattening of adversarial framing is the dominant risk on a single-vendor lineup.

**Stage 1 isolation:** each `CouncilCall` is a fresh `generate_content` invocation. Calls cannot see each other (no shared chat history, no shared cache key). Independence guarantees that responses are not anchored on each other.

**Stage 2 anonymization** stays unchanged — reviewers see opinions stripped of persona labels under "Voice A / B / C / D" mapping. Persona identities are revealed only by an explicit toggle in the UI.

**Stage 3 chairman synthesis** stays unchanged — the chairman call is one more `generate_content` invocation under the configured `chairman_persona`. Chairman rotation across cycles uses a deterministic schedule from `config/council/chairman_rotation.yaml`.

### 24.4 Sycophancy-defense tradeoff (load-bearing)

Single-vendor + no temperature variation **materially weakens** the sycophancy defense. The old design had two orthogonal axes of diversity (vendor + persona); the new design has only one (persona). The disagreement-rate calibration probe set will produce a lower baseline.

- The PRD-002 acceptance threshold drops from **0.40** to **0.25** overall disagreement rate.
- The threshold floor is empirical: calibrate on the built-in probe set + at least 5 operator-supplied domain-specific probes. If the empirical floor is below 0.20, the council is unusable and the factory must escalate (either expand to multi-vendor — overriding this amendment — or strengthen persona prompts and re-calibrate).
- Defense weight shifts to the **G4 validation portfolio**: held-out symmetry tests, refinement convergence, cross-simulator check carry more burden. Spec 009's "intensified G4" track (triggered when C1 returns `qualified` with substantive dissent) is now the default G4 path for any cycle where the C1 chairman_decision is anything other than unanimous `approve`.
- The `CouncilSycophancyDetected` exception still fires on `max` pairwise cosine > 0.92 (lifted from 0.85 to reflect single-vendor baseline similarity).

### 24.5 API key + pricing simplification

**Env var:** `GEMINI_FLASH` is the only required LLM env var. Drop `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY`, `OPENROUTER_API_KEY` from every doc.

**Pricing:** one pricing table only — `config/pricing/gemini.yaml`. Schema:

```yaml
model_id: gemini-3.5-flash
input_per_1m_tokens_usd: <fill_at_setup_time_from_https://ai.google.dev/gemini-api/docs/pricing>
output_per_1m_tokens_usd: <same>
last_updated_iso: YYYY-MM-DD
```

The Council library reads this once at startup; USD is computed as `(input_tokens × input_per_1m / 1e6) + (output_tokens × output_per_1m / 1e6)` and passed to `BudgetTracker.record(cost_usd=...)`.

**`BudgetTokenUsageMissing`** stays as the error class — Gemini returns `usage_metadata.prompt_token_count` and `candidates_token_count`. Absence of `usage_metadata` raises `BudgetTokenUsageMissing`.

### 24.6 Files affected by this amendment

The following files MUST be updated by Wave-Gemini fixer agents:

- `specs/001-council.md` — drop multi-vendor lineup, redefine as persona-only.
- `specs/013-budget-tracker.md` — pricing table reduces to one file.
- `specs/015-operator-interface.md` — env section.
- `docs/SPEC.md` §3.1 + §10.1 — council composition + sycophancy defense.
- `docs/ARCHITECTURE.md` — env-var enumeration if any.
- `docs/GLOSSARY.md` — drop multi-vendor entries, add Gemini-specific entry.
- `docs/DIAGRAMS.md` — council sequence diagram labels.
- `prds/PRD-002-council-library.md` — acceptance threshold + heterogeneity check.
- `runbooks/first-cycle.md` — env section.
- `runbooks/council-calibration.md` — lineup setup, threshold, Google's temperature guidance.

### 24.7 Acceptance check

After all Wave-Gemini fixes land:

```bash
grep -rn "ANTHROPIC_API_KEY\|OPENAI_API_KEY\|XAI_API_KEY\|OPENROUTER\|claude-opus\|gpt-5\|grok\|anthropic\b\|openai\b\|four vendors\|≥4 distinct vendors\|multi-vendor router" docs/
```

This must return zero hits (except inside the FIX_PLAN amendment itself documenting the *removal*). Same applies to `temperature=` / `top_p=` / `top_k=` outside of explicit "do not set" callouts.

---

## 25. AMENDMENT (2026-05-23) — Hybrid LLM via OpenRouter (SUPERSEDES §24)

This amendment **supersedes §24**. The single-vendor Gemini-only constraint from §24 is retracted because it materially weakened the council's sycophancy defense. The new architecture is:

- **Council** (judgment gates C1–C5): heterogeneous, 4 frontier models from 4 distinct vendors.
- **Agentic LLM calls everywhere else** (code-gen, Gap Miner LLM analysis, RAG writer drafting, surrogate-OOD audit prose, telemetry summarization): `google/gemini-3.5-flash` (cheap, single model).
- **All LLM access** is routed through **OpenRouter**, using a **single env var `OPENROUTER_API_KEY`**.

The sycophancy defense restored by this amendment is load-bearing for the entire factory. Do not collapse the council back to a single vendor without an equivalent compensating defense.

### 25.1 Canonical OpenRouter facts (verified via Context7 / official docs)

| Item | Value |
| :--- | :--- |
| Base URL | `https://openrouter.ai/api/v1` |
| Endpoint | `POST /api/v1/chat/completions` |
| Auth | `Authorization: Bearer ${OPENROUTER_API_KEY}` |
| API key env var | `OPENROUTER_API_KEY` (single env var for **all** LLM access) |
| SDK | `openai` Python package (OpenAI-compatible REST). No OpenRouter-specific client needed. |
| Optional headers | `HTTP-Referer: <YOUR_SITE_URL>`, `X-OpenRouter-Title: <YOUR_SITE_NAME>` (for OpenRouter rankings; we set `X-OpenRouter-Title: ai-co-computational-physicist`) |
| Model ID format | `<vendor>/<model-id>` (vendor prefix required) |
| Response | OpenAI-shaped `choices[0].message` + `usage` block (`prompt_tokens`, `completion_tokens`, `total_tokens`) |
| Structured outputs | Standard `response_format={"type": "json_object"}` works; `json_schema` works on supported models |
| Reference | https://openrouter.ai/docs/quickstart, https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request |

### 25.2 Canonical Python invocation pattern

```python
import os
from openai import OpenAI

# Single client, shared by council and all agentic calls.
_CLIENT = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

_OPENROUTER_RANKING_HEADERS: dict[str, str] = {
    "HTTP-Referer": "https://github.com/<org>/<repo>",         # filled from config at startup
    "X-OpenRouter-Title": "ai-co-computational-physicist",
}

def call_llm(
    model: str,                # canonical IDs in §25.3
    system_instruction: str,
    user_content: str,
    max_tokens: int = 4096,
    json_mode: bool = False,
) -> "OpenRouterResponse":
    """Single LLM call. Same client for council and agentic calls. Returns text + usage."""
    response = _CLIENT.chat.completions.create(
        extra_headers=_OPENROUTER_RANKING_HEADERS,
        model=model,
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_content},
        ],
        max_tokens=max_tokens,
        response_format={"type": "json_object"} if json_mode else None,
        # No temperature override by default. Council personas + heterogeneity carry diversity.
    )
    return OpenRouterResponse(
        text=response.choices[0].message.content,
        model_id_actual=response.model,                        # may differ from request if OpenRouter routes
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
    )
```

### 25.3 Canonical model IDs

| Use site | Model ID (OpenRouter format) | Role |
| :--- | :--- | :--- |
| Council slot 1 | `openai/gpt-5.5` | OpenAI vendor |
| Council slot 2 | `anthropic/claude-opus-4.7` | Anthropic vendor |
| Council slot 3 | `google/gemini-3.1` | Google vendor |
| Council slot 4 | `x-ai/grok-4.3` | xAI vendor |
| Agentic default (code-gen, Gap Miner, RAG writer, OOD audit, telemetry digest) | `google/gemini-3.5-flash` | single cheap model |

Verify exact ID strings against the live OpenRouter model catalog at setup time (`curl https://openrouter.ai/api/v1/models -H "Authorization: Bearer $OPENROUTER_API_KEY"`). If a model ID has moved (e.g., `gpt-5.5` → `gpt-5-5-preview`), update the lineup config; do not edit code.

**Council lineup invariant:** 4 calls minimum, one per vendor above. Persona assignment can vary per cycle (random / round-robin / weighted) but the four vendors are fixed. A failure of any single vendor falls back to **failing the deliberation** (raise `CouncilError`); there is no silent substitution — vendor heterogeneity IS the defense.

### 25.4 Council architecture — restored to multi-vendor + persona

Restoring §24's retracted defense. The council now has **two** orthogonal axes of diversity:
1. **Vendor heterogeneity** — 4 frontier models from 4 distinct vendors.
2. **Persona heterogeneity** — each call carries a Visionary / Pessimist / Pragmatist system instruction.

Updated dataclasses:

```python
@dataclass(frozen=True)
class ModelSpec:
    openrouter_id: str             # e.g. "openai/gpt-5.5"
    vendor: Literal["openai", "anthropic", "google", "x-ai"]
    timeout_s: float = 60.0
    max_tokens: int = 4096

@dataclass(frozen=True)
class CouncilLineup:
    models: Sequence[ModelSpec]                    # ≥4, one per vendor in §25.3
    persona_assignment: dict[str, PersonaName]     # model_id → persona
    chairman_policy: Literal["random", "round_robin", "weighted_by_cost"]
```

**Sycophancy threshold restored:** `sycophancy_threshold = 0.85` (max pairwise cosine). The §24 single-vendor bump to 0.92 is reverted.

**Calibration acceptance threshold restored:** overall disagreement-rate `≥ 0.40` for PRD-002 acceptance. The §24 lowered threshold of 0.25 is reverted.

**Stage 2 anonymization** unchanged — reviewers see Voice A/B/C/D mapping.

**Chairman synthesis** unchanged — preserved dissent required.

### 25.5 Agentic (non-council) LLM uses

Every non-council LLM call uses `google/gemini-3.5-flash` via the same OpenRouter client.

Concrete sites:
- **spec 008 Generator-Verifier code-gen** — `_CLIENT.chat.completions.create(model="google/gemini-3.5-flash", ...)`. Default sampling (Google's guidance on Gemini still applies to Gemini calls — see §25.7).
- **spec 007 Literature / Gap Miner LLM analysis** — same.
- **spec 011 RAG Writer section drafting** — same.
- **spec 010 Surrogate OOD audit prose** (when present) — same.
- **spec 014 Telemetry C5-input digest** (when present) — same.

Single-vendor for these is acceptable because:
- They produce text whose validity is checked downstream by the council (e.g., code-gen output is validated by G2.5 / G3 / G4); the LLM is *not* the judgment substrate.
- Cost discipline matters more here (one call per iteration × many iterations).

### 25.6 API key + pricing

**Env var:** `OPENROUTER_API_KEY` is the single LLM env var. Drop every other LLM key reference (no `ANTHROPIC_API_KEY`, no `OPENAI_API_KEY`, no `GEMINI_FLASH`, no `XAI_API_KEY`, no `GOOGLE_API_KEY`).

**Pricing:** one pricing table — `config/pricing/openrouter.yaml`:

```yaml
# OpenRouter passthrough prices. Verify at https://openrouter.ai/models
# Updated YYYY-MM-DD by operator-during-setup.
models:
  "openai/gpt-5.5":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
  "anthropic/claude-opus-4.7":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
  "google/gemini-3.1":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
  "x-ai/grok-4.3":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
  "google/gemini-3.5-flash":
    input_per_1m_tokens_usd: <fill>
    output_per_1m_tokens_usd: <fill>
last_updated_iso: YYYY-MM-DD
```

USD per call = `(input_tokens × input_per_1m / 1e6) + (output_tokens × output_per_1m / 1e6)`. The Council library reads this once at startup; passes USD to `BudgetTracker.record(cost_usd=...)`.

`BudgetTokenUsageMissing` fires when OpenRouter response lacks the `usage` block.

### 25.7 Sampling parameters policy

- **Council calls (frontier models):** no `temperature` / `top_p` / `top_k` override by default. Council diversity comes from vendor heterogeneity + persona system instructions, not sampling noise.
- **Agentic Gemini Flash calls:** no `temperature` / `top_p` / `top_k` override (Google's official guidance still applies via the underlying provider).
- Operator-controlled `--exploration-temperature 0.7` flag may be added in Phase B for explicit creative-exploration cycles; deferred.

### 25.8 Cost expectations

| Operation | Estimated cost | Per Phase A |
| :--- | :--- | :--- |
| Single council deliberation (4 frontier × 3 stages + chairman + embeddings) | ≤ $0.50 | Restored from §24's $0.10 target |
| Single agentic LLM call (Gemini Flash) | ≤ $0.005 | (depends on prompt + response size) |
| Generator-verifier iteration (1 code-gen call) | ≤ $0.005 | Per iteration |
| Full cycle (G0 → G6 with 4 councils + 10 genver iterations + 1 RAG write) | ≤ $5.00 typical, ≤ $50 PRD-001 cap | Cap remains |

### 25.9 Files affected by this amendment (SUPERSEDES §24's list)

All files touched by §24 must be **re-edited** to apply §25's hybrid setup:

- `specs/001-council.md` — restore multi-vendor lineup; OpenRouter SDK; 4 models from §25.3.
- `specs/008-generator-verifier.md` — code-gen uses `google/gemini-3.5-flash` via OpenRouter.
- `specs/007-literature-discovery.md` — any LLM-driven analysis uses `google/gemini-3.5-flash` via OpenRouter.
- `specs/011-rag-writer.md` — section drafting uses `google/gemini-3.5-flash` via OpenRouter.
- `specs/013-budget-tracker.md` — single pricing table `config/pricing/openrouter.yaml` with 5 models.
- `specs/015-operator-interface.md` — env section: only `OPENROUTER_API_KEY`.
- `docs/SPEC.md` §3.1, §10.1 — council composition restored to multi-vendor + persona; sycophancy threshold 0.85.
- `docs/ARCHITECTURE.md` — env-var section: `OPENROUTER_API_KEY` only.
- `docs/GLOSSARY.md` — restore multi-vendor council entry; add OpenRouter entry; thresholds returned.
- `docs/DIAGRAMS.md` — council sequence diagram relabeled to vendor-prefixed model IDs.
- `prds/PRD-002-council-library.md` — acceptance threshold restored to 0.40; cost target $0.50; 4-vendor heterogeneity required.
- `runbooks/first-cycle.md` — env section: `OPENROUTER_API_KEY`; lineup verification against OpenRouter catalog.
- `runbooks/council-calibration.md` — restore multi-vendor lineup setup; threshold 0.40; recovery rotates models within OpenRouter catalog.

### 25.10 Acceptance grep

After all Wave-OpenRouter fixes land:

```bash
grep -rn "ANTHROPIC_API_KEY\|OPENAI_API_KEY\|XAI_API_KEY\|GEMINI_FLASH\|GOOGLE_API_KEY" docs/
```

Must return zero hits outside this amendment text. Same for `pricing/gemini.yaml` (singular Gemini pricing file from §24 is replaced by `pricing/openrouter.yaml`).

---

## 26. AMENDMENT (2026-05-23) — GCPH solver-blueprint lock-in + Strategy Archive (BFTS + Bayesian surprise) + Multi-Fidelity Scheduler abstraction

This amendment closes two implementation gaps the Crucible review surfaced:

1. **GCPH-doc gaps** (from `computational_physics_harness.md` in the brain folder): the six-component solver blueprint was gestured at by spec 006 but ABC names were TBD; the Multi-Fidelity Grid Scheduler from GCPH Phase 4 was implicit (`ExperimentSpec.fidelity_ladder`) but not a named component.
2. **Proxima-harness gaps** (from `/Users/suhjungdae/code/software/proxima_fusion/ai-sci-feasible-designs/harness/`): the production-tested **Strategy Archive** — Bayesian surprise via graded Dirichlet KL, UCT composite scoring, behavior-descriptor diversity (MAP-Elites), lineage selection for parallel branches — was absent from the new factory docs entirely.

Both gaps are closed by this amendment. The Strategy Archive abstraction is essentially a port of the proxima harness's contract; references to the source files appear inline so the abstraction stays faithful.

### 26.1 Six-component solver blueprint — canonical ABC names locked

Lock these names in `factory/adapter/abstract.py` (referenced by spec 006 §3 and spec 008 §3). They map 1:1 to the GCPH brain-folder doc's modules:

| GCPH module (brain folder) | Canonical Python ABC name |
| :--- | :--- |
| Module 1 — Fidelity & Discretization Manager | `Discretizer` |
| Module 2 — Boundary & Constraint Aggregator | `ConstraintAggregator` |
| Module 3 — Update & Step Operator | `UpdateStepOperator` |
| Module 4 — Globalization & Acceptance Controller | `AcceptanceController` |
| Module 5 — Restart & Reset Controller | `RestartController` |
| Module 6 — Polishing & Local Search | `LocalPolisher` |

Each ABC is in `factory/adapter/abstract.py`. The per-simulator adapter (e.g., `factory/adapter/<simulator_id>.py`) returns a `BlueprintComponents` tuple binding all six concrete subclasses.

The Generator-Verifier code-gen (spec 008) targets the abstract ABCs only — code-gen never sees the per-simulator concrete subclass implementations. This is the abstraction boundary that lets the factory drive a new simulator by adding an adapter, not by re-prompting code-gen.

### 26.2 New spec 016 — Strategy Archive

Spec 016 owns the **BFTS + Bayesian surprise + UCT + MAP-Elites** machinery. Module path: `factory/strategy/`.

**Reference implementation** (do not edit, but study the contract):
- `/Users/suhjungdae/code/software/proxima_fusion/ai-sci-feasible-designs/harness/beliefs.py` — `beta_kl`, `dirichlet_kl`, `binary_bayesian_surprise`, `bayesian_surprise` (graded).
- `harness/strategy_config.py` — `StrategyArchiveConfig` invariants (`reward_alpha + surprise_beta == 1.0`, `surprise_mode ∈ {graded, binary}`, `ema_alpha`).
- `harness/strategy_selection.py` — UCT composite scoring with behavior-novelty bonus.
- `harness/strategy_evidence.py` — per-cycle evidence aggregation.
- `harness/world_model_schema.py` lines 96–168 — DB schema for `strategies`, `strategy_edges`, `strategy_subtree`.

**Public interface for spec 016:**

```python
class GuideLLM(Protocol):
    """Belief-eliciting LLM, separate from the council. Uses google/gemini-3.5-flash via OpenRouter (FIX_PLAN §25.5)."""
    async def boolean(self, prompt: str) -> bool: ...
    async def feasibility_bucket(self, prompt: str) -> Literal["lt_10", "10_50", "gt_50"]: ...

def beta_kl(a_post: float, b_post: float, a_pre: float, b_pre: float) -> float: ...
def dirichlet_kl(alpha_post: tuple[float, ...], alpha_pre: tuple[float, ...]) -> float: ...
async def binary_bayesian_surprise(strategy_md: str, evidence: str, guide_llm: GuideLLM, n: int = 5) -> float: ...
async def graded_bayesian_surprise(strategy_md: str, evidence: str, guide_llm: GuideLLM, n: int = 5) -> float: ...

@dataclass(frozen=True)
class StrategyArchiveConfig:
    enabled: bool = True
    surprise_mode: Literal["graded", "binary"] = "graded"
    surprise_n_samples: int = 5
    reward_alpha: float = 0.7              # MUST satisfy reward_alpha + surprise_beta == 1.0
    surprise_beta: float = 0.3
    feasibility_gamma: float = 1.0
    uct_exploration_constant: float = 1.414
    behavior_novelty_weight: float = 0.25
    map_elites_cell_bonus: float = 1.0
    parallel_lineages_k: int = 1           # 1 in Phase A; > 1 in Phase B
    ema_alpha: float = 0.5
    cross_run_transfer_k: int = 8

class StrategyArchive:
    def attribute_surprise(self, strategy_sha: str, evidence: StrategyCycleEvidence) -> float: ...
    def attribute_reward(self, strategy_sha: str, evidence: StrategyCycleEvidence) -> float: ...
    def select_lineages(self, k: int) -> list[str]: ...     # UCT + novelty + MAP-Elites
    def add_strategy(self, summary_md: str, parents: list[str], kind: StrategyKind) -> str: ...
    def transfer_priors_from(self, source_problem_id: str, k: int) -> None: ...
```

**Bayesian-surprise math (per `harness/beliefs.py`):**

- Buckets: `lt_10`, `10_50`, `gt_50` (feasible-candidate fraction).
- Prior: `Dirichlet(1 + counts_pre)` from `n` LLM samples before evidence.
- Posterior: `Dirichlet(1 + counts_pre + counts_post)` after evidence is shown.
- **Surprise = `KL(posterior || prior)`**, gated to `0.0` unless the unique dominant pre/post bucket changes (polarity gate prevents counting sampling noise as surprise).
- Binary path uses Beta-Bernoulli conjugacy + 0.5-mean polarity gate.

**Phase A defaults:** `surprise_mode = "binary"` (cheaper, 2× n_samples LLM calls per surprise), `parallel_lineages_k = 1` (no MAP-Elites at first; single lineage walked through the gate sequence). Phase B promotes to `graded` + multi-lineage.

**Strategy artifact (added to spec 002):**

```python
class StrategyKind(str, Enum):
    NOVEL = "novel"
    MUTATE = "mutate"
    CROSSOVER = "crossover"
    LIBRARY = "library"

class Strategy(_ArtifactBase):
    sha: str                                    # content hash of summary_md
    summary_md: str                             # full strategy description (markdown)
    kind: StrategyKind
    parent_shas: tuple[str, ...]                # empty for novel/library; ≥1 for mutate/crossover
    reward_ema: float | None                    # NULL until first observation
    surprise_ema: float | None                  # NULL until first observation
    feasibility_distance_ema: float | None
    feasible_count: int
    visits: int
    behavior_descriptor: BehaviorDescriptor      # lazy; for MAP-Elites diversity
    provenance: Literal["agent_authored", "hand_authored", "transferred_from_exp_*"]

class StrategyCycleEvidence(_ArtifactBase):
    strategy_sha: str
    cycle_id: CycleId
    best_objective: float | None
    best_feasibility_distance: float | None
    feasible_count: int
    constraint_overshoots: dict[str, ConstraintOvershootStats]  # typed model
```

The artifact registry grows from 11 (per §1) to **13** artifacts. SPEC.md / ARCHITECTURE.md / GLOSSARY.md / INDEX.md all need the count bump.

**EvidenceLedgerEntry gains `surprise_bits: float | None`** (NULL until the strategy archive scores the entry). C5 (Program Direction) ranks entries by surprise × downstream citation count.

### 26.3 New spec 017 — Multi-Fidelity Ladder Scheduler

Spec 017 owns the runtime ladder traversal: given an `ExperimentSpec.fidelity_ladder`, decide which tier to run next, promote on success, kill on threshold violation, surface telemetry per tier transition. Module path: `factory/fidelity/`.

Distinct from spec 006's `Discretizer` ABC: the `Discretizer` decides grid/mesh choices **within one run**; the FidelityLadderScheduler decides **which run** is next on the ladder.

**Public interface:**

```python
class FidelityKind(str, Enum):
    DRY_RUN = "dry_run"
    SURROGATE = "surrogate"
    MID_FIDELITY = "mid_fidelity"
    ORACLE = "oracle"
    CROSS_SIMULATOR = "cross_simulator"

@dataclass(frozen=True)
class TierResult:
    tier: FidelityTier
    metric_value: float
    cost_usd: float
    wall_clock_seconds: float
    promoted: bool                             # True ⇒ continue to next tier; False ⇒ kill

class FidelityLadderScheduler:
    def __init__(self, ladder: tuple[FidelityTier, ...], surrogate: SurrogateRegistry, adapter_run_fn: Callable) -> None: ...
    def run_next_tier(self, hypothesis_id: HypothesisId) -> TierResult: ...
    def is_complete(self) -> bool: ...
    def kill_reason(self) -> str | None: ...
```

Promotion criteria per tier are declared on the `FidelityTier` artifact (already in spec 002 §3 `FidelityTier`). The scheduler reads `kill_threshold` and the surrogate-baseline gate (G3) and the validation portfolio (G4) outcomes.

Phase A ladder: `[DRY_RUN, SURROGATE, ORACLE]` (3 tiers). Phase B adds `MID_FIDELITY` and `CROSS_SIMULATOR` as separate tiers.

### 26.4 Updates to existing specs

- **spec 002** (artifacts) — Adds `Strategy`, `StrategyCycleEvidence`, `BehaviorDescriptor`, `ConstraintOvershootStats` artifacts and supporting `StrategyKind` enum. Adds `surprise_bits: float | None` to `EvidenceLedgerEntry`. Artifact count bumped to **13**.
- **spec 006** (domain adapter) — Locks the six ABC names (§3 Public Interface). Removes the "TBD" placeholders.
- **spec 008** (generator-verifier) — When `StrategyArchiveConfig.enabled=True` and `parallel_lineages_k > 1`, the loop receives a `parent_strategy_sha` per iteration from the archive's `select_lineages(k)` output; otherwise (Phase A default) the loop runs un-parented as today. Either way, on iteration end the loop reports `StrategyCycleEvidence` to the archive.
- **spec 010** (surrogate) — Optional active-learning hook: after a surrogate is retrained, the archive can use the surrogate's posterior variance as a *fallback* surprise signal when GuideLLM is unavailable. Phase B.
- **spec 012** (ledger) — Adds the `surprise_bits` column and the C5 audit query `top_high_surprise_with_dependents`.
- **spec 003** (state machine) — C5 program-direction council reads the archive (top-K productive strategies, lineage saturation) to decide DomainScope changes.

### 26.5 Repo layout (ARCHITECTURE.md §3)

```
factory/
├── adapter/                         # spec 006 — abstract ABCs + per-simulator adapters
│   └── abstract.py                  # the 6 ABCs locked in §26.1
├── strategy/                        # spec 016 — Bayesian surprise + UCT + archive (NEW)
│   ├── beliefs.py                   # beta_kl, dirichlet_kl, surprise variants
│   ├── archive.py                   # StrategyArchive class
│   ├── selection.py                 # UCT + novelty + MAP-Elites
│   ├── evidence.py                  # StrategyCycleEvidence aggregation
│   └── distill.py                   # off-path strategy distillation (Phase B)
├── fidelity/                        # spec 017 — multi-fidelity ladder scheduler (NEW)
│   ├── scheduler.py
│   └── tiers.py
└── ...                              # (rest unchanged)
```

### 26.6 Acceptance grep

After Wave-Harness fixes land:

```bash
grep -rn "Discretizer\|ConstraintAggregator\|UpdateStepOperator\|AcceptanceController\|RestartController\|LocalPolisher" specs/006-domain-adapter.md
# Expect: each name appears ≥ once.

grep -rn "Bayesian surprise\|surprise_ema\|dirichlet_kl\|beta_kl" specs/016-strategy-archive.md
# Expect: each appears ≥ once.

grep -rn "FidelityLadderScheduler\|FidelityKind\|run_next_tier" specs/017-fidelity-scheduler.md
# Expect: each appears ≥ once.

grep -rn "thirteen typed artifact\|13 typed artifact" SPEC.md ARCHITECTURE.md GLOSSARY.md INDEX.md
# Expect: each file has ≥ 1 hit (count bumped from 11 → 13).
```

### 26.7 Phase A scope

Spec 016 + spec 017 are **fully specified now** but the Phase A deliverable uses the simpler config:
- Spec 016: `surprise_mode="binary"`, `parallel_lineages_k=1`, no MAP-Elites cells, no cross-run transfer. Single lineage walked through the gate sequence; surprise computed per cycle and stored on EvidenceLedgerEntry.
- Spec 017: 3-tier ladder (DRY_RUN, SURROGATE, ORACLE). Phase B adds MID_FIDELITY + CROSS_SIMULATOR + active-learning surprise.

The proxima harness's production config (graded surprise, multi-lineage, MAP-Elites) is the Phase B target.
