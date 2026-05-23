# Spec 005: Simulator Selector

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- The **Simulator Selector** is a deterministic ranker. Given a `HypothesisSpec`, it queries the `SimulatorCatalog` (spec 004) for entries whose declared capabilities can compute the hypothesis's `measurable_metric`, scores survivors against a weighted compatibility / license / cost / cross-validation / freshness rubric, and returns a ranked `SelectionResult` consumed at gate **G1.5** by the State Machine (spec 003).
- The 5 facts: (1) the Selector is **pure-deterministic** — no LLM calls, no stochastic ranking, no live network; LLM judgment between near-tied candidates happens later in council **C2** (Experimental Design); (2) failure to find any compatible Catalog entry yields an **empty `SelectionResult`** and routes to `terminate_parked_for_lack_of_tooling` — never an exception; (3) ranking weights are loaded from `config/selector/weights.yaml`, never hard-coded; (4) a `cross_simulator_available` flag is computed and propagated so the G4 validation portfolio can enable the cross-simulator check; (5) out-of-`DomainScope` hypotheses must be rejected at **G0** *before* reaching the Selector — Selector trusts its input is in-scope.
- Open first: `factory/selector/api.py` and `factory/selector/tests/test_selector_typical_usage.py`.

## ENTRY POINTS
- Main module: `factory/selector/api.py`
- Typical-usage test: `factory/selector/tests/test_selector_typical_usage.py`
- CLI: `python -m factory.selector --help` (subcommands: `select`, `explain`, `list-compatible`)
- Mock-mode example: `python -m factory.selector select --hypothesis-fixture sample --catalog-fixture phase_a --mock-mode`
- Runbook: `[TBD-impl]` (no runbook authored yet; tracked in §10 TODO).

## LOCAL DEBUG
- Instantiate without API or container deps: `Selector(catalog=Catalog.from_fixture("phase_a")).select(HypothesisSpec.from_fixture("sample"))` returns a deterministic `SelectionResult`.
- Fixture artifacts:
  - `factory/selector/fixtures/hypothesis_spec_sample.json` — typical in-scope hypothesis.
  - `factory/selector/fixtures/catalog_phase_a.json` — small fixture catalog (3 entries) with a cross-validatable observable.
  - `factory/selector/fixtures/weights_default.yaml` — default weight config.
- Common error signatures → recovery:
  - `NoSuitableSimulator` (returned, not raised, inside `SelectionResult.failure_mode`) → state machine routes to `terminate_parked_for_lack_of_tooling`; C5 may later flag the missing observable for Catalog growth.
  - `AmbiguousCompatibility` (flag on result) → ≥2 candidates score within `ambiguity_epsilon`; council C2 picks. Not an error.
  - `CostEstimateUnavailable` (per-candidate flag) → Catalog entry lacks cost metadata AND historical telemetry has no runs for this simulator; candidate kept but penalized via `cost_estimate_missing_penalty`.
  - `CrossSimulatorMapEmpty` (flag on result) → no two compatible candidates can cross-validate this observable; G4 will reweight toward refinement + symmetry (per `SPEC.md` §8).
  - `SelectorConfigError` → weights YAML missing or weights don't sum to 1.0 ± tol; fix `config/selector/weights.yaml` before any selection.
  - `CatalogStaleError` → Catalog version pinned in `SelectionResult.catalog_version_hash` no longer resolves; cycle aborted at G1.5 with a structured event.
- Logs to inspect: `runs/<cycle-id>/cycle.jsonl` filtered by `module=selector`; per-selection trace under `runs/<cycle-id>/artifacts/<selection-hash>.trace.json`.

## DEPENDENCIES
- **Hard:**
  - Spec 002 (artifacts) — reads `HypothesisSpec`, emits Selector-local `SelectionResult`, and writes the chosen `simulator_id` into the eventual `ExperimentSpec` (constructed by C2 / spec 003, not by Selector).
  - Spec 004 (catalog) — queries `Catalog.list_entries()`, `Catalog.list_for_observable(observable)`, `Catalog.equivalence_pairs(observable)`, and `Catalog.version_hash()`.
- **Soft:**
  - Spec 014 (telemetry) — historical run telemetry for cost calibration. Fallback: use Catalog manifest's static `cost_estimate_usd_per_run`.
  - Spec 013 (budget) — if a `Budget` context is provided, candidates whose estimated cost exceeds the per-hypothesis dollar cap are flagged `over_budget` (kept in the result, but ranked below in-budget alternatives).
- **Mocks available:**
  - `Catalog.from_fixture("phase_a")` (provided by spec 004 mock surface) — 3-entry catalog with a known cross-validatable observable.
  - `TelemetryStub.no_history()` — zero historical runs; forces fallback to static cost estimates.
  - `Selector.mock_default()` — pre-wired with the above for the typical-usage test.

---

## 1. Summary

The **Simulator Selector** is the gatekeeper between a falsifiable `HypothesisSpec` and the bounded universe of OSI-licensed simulators in the `SimulatorCatalog`. Given a hypothesis with a `measurable_metric`, it produces a ranked `SelectionResult` listing every catalog entry that can compute that observable, scored on a weighted rubric and annotated with cost estimates, cross-simulator availability, license status, and freshness.

The Selector is the deterministic floor of gate G1.5: when it returns an empty result, the hypothesis is parked for lack of tooling — no council debates whether a simulator that doesn't exist should be tried. When it returns multiple near-tied candidates, the Experimental Design council (C2) chooses among them; the Selector flags the ambiguity but never resolves it with LLM judgment.

## 2. Scope

**In scope:**
- Resolve `HypothesisSpec.measurable_metric` against `Catalog` capability declarations + `cross_simulator_equivalence_map`.
- Score surviving candidates on capability match, license compliance, cost estimate, cross-simulator availability, and maintenance freshness, with configurable weights.
- Estimate per-candidate compute cost from Catalog metadata + historical run telemetry (spec 014).
- Compute a `cross_simulator_available` boolean and the set of cross-validation partners per candidate.
- Detect and flag near-ties (`AmbiguousCompatibility`) for downstream council resolution.
- Emit a structured `SelectionResult` with full reasoning trace.
- CLI for offline ranking inspection (`select`, `explain`, `list-compatible`).
- Mock mode for CI.

**Out of scope:**
- Picking *the* simulator (C2 / spec 003 decides among ranked candidates).
- Constructing the `ExperimentSpec` (C2 council produces it from Selector output).
- Validating that the chosen simulator actually runs (container smoke test owned by spec 004).
- DomainScope checks (G0 in spec 003 — Selector trusts in-scope input).
- License auditing (catalog onboarding owned by spec 004; Selector reads the audited flag).
- Onboarding new simulators (spec 004 catalog growth policy).

## 3. Public Interface

```python
# factory/selector/api.py

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Mapping
from factory.artifacts import (
    HypothesisSpec, ArtifactHash, FactoryError
)
from factory.catalog import Catalog, SimulatorId, CatalogVersionHash, ObservableName

class SelectorError(FactoryError): ...
class SelectorConfigError(SelectorError): ...
class CatalogStaleError(SelectorError): ...

@dataclass(frozen=True)
class CostEstimate:
    expected_runtime_seconds: float
    expected_cost_usd: float
    source: Literal["telemetry", "manifest", "fallback_default"]
    confidence: Literal["high", "medium", "low", "unavailable"]

@dataclass(frozen=True)
class Candidate:
    simulator_id: SimulatorId
    score: float                                 # weighted sum in [0, 1]
    capability_match: float                      # in [0, 1]
    license_ok: bool                             # OSI-approved + redistributable
    cost: CostEstimate
    cross_simulator_partners: tuple[SimulatorId, ...]
    maintenance_freshness: float                 # in [0, 1]; from last-commit recency
    over_budget: bool                            # vs current Budget if provided
    flags: tuple[str, ...]                       # e.g. "cost_estimate_missing"
    rationale_lines: tuple[str, ...]             # human-readable scoring breakdown

@dataclass(frozen=True)
class SelectionResult:
    hypothesis_id: str
    catalog_version_hash: CatalogVersionHash
    weights_hash: str                            # hash of config/selector/weights.yaml
    candidates: tuple[Candidate, ...]            # ranked, best first
    cross_simulator_available: bool              # ≥1 candidate has ≥1 partner
    ambiguous: bool                              # ≥2 candidates within ambiguity_epsilon
    failure_mode: Literal[
        "ok",
        "no_suitable_simulator",
        "cross_simulator_map_empty",
        "all_over_budget",
    ]
    trace_path: Path                             # full reasoning trace JSON

@dataclass(frozen=True)
class SelectorWeights:
    capability_match: float
    license_compliance: float
    cost: float
    cross_simulator_availability: float
    maintenance_freshness: float
    ambiguity_epsilon: float                     # score gap below which ties are flagged
    cost_estimate_missing_penalty: float
    over_budget_penalty: float

class Selector:
    """Deterministic ranker over the SimulatorCatalog."""

    def __init__(
        self,
        catalog: Catalog,
        weights: SelectorWeights | None = None,
        telemetry: "TelemetryReader | None" = None,
        weights_path: Path = Path("config/selector/weights.yaml"),
        mock_mode: bool = False,
    ) -> None: ...

    def select(
        self,
        hypothesis_spec: HypothesisSpec,
        budget_dollar_cap: float | None = None,
    ) -> SelectionResult:
        """Pure function over (hypothesis, catalog snapshot, weights, telemetry snapshot).
        Never raises on selection failures; emits SelectionResult with failure_mode set.
        Raises SelectorConfigError / CatalogStaleError on infrastructural failures only.
        """

    def explain(
        self,
        result: SelectionResult,
        candidate_id: SimulatorId,
    ) -> str:
        """Return the human-readable rationale for one candidate's score."""

    @classmethod
    def mock_default(cls) -> "Selector":
        """Wired with Catalog.from_fixture('phase_a') + TelemetryStub.no_history()."""
```

The public surface is **`Selector.select`**. Everything else is convenience.

## 4. Data Structures / Schemas

`SelectionResult` is **not** one of the eight persistent typed artifacts in spec 002 — it is a transient selector-local result. It is, however, serialized to `runs/<cycle-id>/artifacts/<selection-hash>.json` for trace reproducibility, and the chosen `simulator_id` from `candidates[0]` (post-C2-resolution) is what eventually populates `ExperimentSpec.simulator_id` (spec 002).

Trace file (`<selection-hash>.trace.json`) records, per candidate:
- raw subscore vector (capability, license, cost, cross-sim, freshness),
- weight vector applied,
- telemetry rows used for cost estimation (anonymized run IDs only),
- cross-simulator partners considered and rejected,
- ambiguity-band membership.

Trace is regenerable from `(hypothesis_hash, catalog_version_hash, weights_hash, telemetry_snapshot_hash)` — those four hashes are the full reproducibility key, recorded in `SelectionResult`.

Weights config (`config/selector/weights.yaml`):

```yaml
capability_match: 0.40
license_compliance: 0.10        # binary in practice — entries that fail license audit are filtered, not scored
cost: 0.20
cross_simulator_availability: 0.20
maintenance_freshness: 0.10
# tunables
ambiguity_epsilon: 0.03
cost_estimate_missing_penalty: 0.15
over_budget_penalty: 0.30
```

Weight values must sum to 1.0 ± 1e-6 across the five main components; load-time validator raises `SelectorConfigError` otherwise.

## 5. Algorithms / Logic

### 5.1 Pipeline

```
HypothesisSpec
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│ 1. Compatibility filter                                  │
│    Catalog.list_for_observable(observable) → candidate   │
│    set. Drop entries failing license audit (binary).     │
│    Drop entries flagged disabled in current DomainScope. │
└─────────────────────────┬────────────────────────────────┘
                          ▼
┌──────────────────────────────────────────────────────────┐
│ 2. Per-candidate scoring                                 │
│    For each survivor:                                    │
│      cap   = capability_match(entry, metric, hypothesis) │
│      cost  = estimate_cost(entry, telemetry, hypothesis) │
│      xsim  = cross_sim_score(entry, metric, catalog)     │
│      fresh = freshness(entry.last_commit_at)             │
│      score = Σ wᵢ · subscoreᵢ − penalties                │
└─────────────────────────┬────────────────────────────────┘
                          ▼
┌──────────────────────────────────────────────────────────┐
│ 3. Rank, detect ambiguity                                │
│    Sort by score desc.                                   │
│    ambiguous = (candidates[0].score - candidates[1].score│
│                 ≤ ambiguity_epsilon)                     │
└─────────────────────────┬────────────────────────────────┘
                          ▼
┌──────────────────────────────────────────────────────────┐
│ 4. Failure-mode classification + result assembly         │
│    Empty candidates → no_suitable_simulator              │
│    All over budget  → all_over_budget                    │
│    No cross-sim     → cross_simulator_map_empty (warn)   │
│    Else             → ok                                 │
└──────────────────────────────────────────────────────────┘
```

### 5.2 Compatibility match (subscore in [0, 1])

For a candidate entry `e` and hypothesis `H`:
1. **Direct match** — `e.capabilities.computed_observables` contains `H.measurable_metric` exactly → subscore 1.0.
2. **Equivalence-map match** — `H.measurable_metric` is reachable via `Catalog.equivalence_pairs(H.measurable_metric)` from one of `e.capabilities.computed_observables` → subscore 0.85 (capped lower than direct match because translation introduces uncertainty).
3. **Capability-superset match** — `e.capabilities` advertises a strictly more general observable that contains `H.measurable_metric` as a special case (declared in the manifest) → subscore 0.70.
4. **Otherwise** — drop the entry from the candidate set. Not a subscore of 0; the entry is filtered out before scoring.

The match level + the supporting catalog-manifest field path are written to `rationale_lines`.

### 5.3 Cost estimation

```
expected_cost_usd =
    expected_runtime_seconds × per_second_cost

where:
  expected_runtime_seconds =
      telemetry.median_runtime_for(entry.simulator_id, observable=hypothesis.measurable_metric)
      if available with ≥ telemetry.min_runs_for_confidence,
      else entry.manifest.expected_runtime_seconds_default

  per_second_cost =
      entry.manifest.per_second_cost_usd
      (host-class-aware: cpu-only vs gpu vs mpi-cluster)
```

Cost source is recorded on `CostEstimate.source` ∈ {`telemetry`, `manifest`, `fallback_default`}. The `fallback_default` source applies `cost_estimate_missing_penalty` to the cost subscore. The cost subscore is normalized **within the current candidate set** (best-cost candidate gets 1.0, worst gets 0.0) so the cost signal is comparative, not absolute.

If a `Budget` was passed to `select` and `expected_cost_usd > budget_dollar_cap`, the candidate is marked `over_budget=True` and an additional `over_budget_penalty` is subtracted from the final score (but the candidate is **not** dropped — operators may override at C2).

### 5.4 Cross-simulator availability

Per candidate `e_i`:
```
partners(e_i) = {
    e_j ∈ surviving_candidates : e_j ≠ e_i AND
    catalog.can_cross_validate(e_i, e_j, observable=H.measurable_metric)
}
```

`cross_sim_score(e_i) = 1.0 if |partners(e_i)| ≥ 1 else 0.0`.

`SelectionResult.cross_simulator_available` is the OR across all candidates. Selection-level `cross_simulator_map_empty` is set when no candidate has any partner.

### 5.5 Maintenance freshness

```
freshness =
    1.0  if days_since_last_commit ≤ 180
    linear interpolation between 1.0 → 0.0 from 180 to 730 days
    0.0  if days_since_last_commit > 730 OR entry.unmaintained_flag
```

Catalog entries already enforce a hard 24-month upper bound at onboarding (spec 004); freshness is the soft-decay signal within that window.

### 5.6 Ambiguity flagging

After sort:
- If `len(candidates) ≥ 2` and `candidates[0].score − candidates[1].score ≤ ambiguity_epsilon`, set `SelectionResult.ambiguous = True`.
- The state machine routes ambiguous results to C2 with **all near-tied candidates** surfaced as a choice, not just the top one. The Selector does not pick.

### 5.7 Determinism guarantees

Given identical `(HypothesisSpec.provenance_hash, Catalog.version_hash(), weights_hash, telemetry_snapshot_hash)`, `select()` must return a `SelectionResult` whose own canonical-JSON serialization is byte-identical. Tie-break on equal scores uses lexicographic order of `simulator_id` (deterministic). No `time.time()`, no `random`, no dict iteration that depends on hash randomization (sort all dict iterations explicitly).

### 5.8 Failure-mode decision table

| Condition (post-pipeline) | `failure_mode` | State machine effect |
| :--- | :--- | :--- |
| ≥1 in-budget, license-OK candidate | `ok` | G1.5 → G2 |
| Candidate set empty after compatibility filter | `no_suitable_simulator` | G1.5 → `terminate_parked_for_lack_of_tooling` |
| All candidates `over_budget` | `all_over_budget` | G1.5 → `terminate_parked_for_lack_of_tooling` with `relitigate_if` = "budget cap raised" |
| ≥1 candidate but `cross_simulator_available == False` | `cross_simulator_map_empty` | G1.5 → G2 (proceed), but G4 reweights per `SPEC.md` §8 |

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `SelectorConfigError(SelectorError)` | Weights YAML missing, malformed, or weights do not sum to 1.0 ± tol | Halt at module init; fix config; surfaces in `cycle.jsonl` with the offending field path |
| `CatalogStaleError(SelectorError)` | The Catalog version hash captured at start of `select()` no longer matches the live Catalog at trace emission | Abort current selection; state machine re-fetches Catalog and retries G1.5 once; second failure escalates |
| `NoSuitableSimulator` (result mode, **not** raised) | Catalog has no entry whose capabilities or equivalence map cover the metric | State machine routes to `terminate_parked_for_lack_of_tooling`; C5 sees aggregate "missing observables" report and may grow the Catalog |
| `AmbiguousCompatibility` (result flag, **not** raised) | ≥2 candidates within `ambiguity_epsilon` | State machine forwards all near-tied candidates to C2; council picks; if council also ties, chairman_decision = `no_consensus` and hypothesis terminates as `inconclusive` at G2 |
| `CostEstimateUnavailable` (per-candidate flag, **not** raised) | No telemetry rows for this `(simulator_id, observable)` pair AND manifest lacks `expected_runtime_seconds_default` | Apply `cost_estimate_missing_penalty`; candidate remains but is downweighted; C2 may still pick it |
| `CrossSimulatorMapEmpty` (result flag, **not** raised) | No candidate has any partner for the observable | Proceed to G2; G4 reweights toward refinement + symmetry per `SPEC.md` §8 |

Note the asymmetry: only **infrastructural** failures (config / catalog version drift) raise exceptions. Every **content-driven** failure — including "no simulator can do this" — is encoded in the structured `SelectionResult`. This keeps the state machine in control of all routing.

## 7. Testing

**Mock-mode** (in CI):
- `test_selector_typical_usage.py` — REQUIRED. Hypothesis fixture + 3-entry catalog fixture → ranks 2 compatible candidates, flags cross-simulator availability, returns `failure_mode=ok`. Asserts result hash stability.
- `test_compatibility_filter.py` — exact-match, equivalence-map, capability-superset, and miss cases. Each path tested.
- `test_scoring_weights.py` — given fixed subscores, asserts final score = Σ wᵢ · subᵢ − penalties to within 1e-9; swapping weight YAML changes ranking as expected.
- `test_cost_estimation.py` — telemetry source vs manifest source vs fallback default, each with the appropriate `source` and `confidence` flags.
- `test_ambiguity_flag.py` — feed two candidates with score gap < `ambiguity_epsilon` → `ambiguous=True`; feed gap > epsilon → `ambiguous=False`.
- `test_no_suitable_simulator.py` — hypothesis metric not in any catalog entry → empty candidates, `failure_mode=no_suitable_simulator`, no exception raised.
- `test_cross_simulator_map_empty.py` — one compatible candidate, no partners → `cross_simulator_available=False`, `failure_mode=cross_simulator_map_empty`.
- `test_over_budget.py` — `budget_dollar_cap` below all candidates' estimates → `over_budget=True` on all, `failure_mode=all_over_budget`.
- `test_determinism.py` — same inputs + telemetry snapshot → byte-identical `SelectionResult` canonical JSON across 10 runs and 2 Python processes.
- `test_in_scope_assumption.py` — Selector trusts in-scope input; an out-of-DomainScope hypothesis is NOT filtered by the Selector (it's G0's job). Verifies Selector neither rejects nor warns — surfaces the assumption explicitly so a future agent doesn't add the check in the wrong layer.

**Live-mode tests:** none required for this module — the Selector is pure logic over catalog + telemetry snapshots.

**Cross-module integration test** (lives in `tests/integration/`):
- `test_selector_to_state_machine.py` — feeds each `failure_mode` value into the spec-003 state machine and asserts the documented routing decisions in §5.8.

## 8. Performance & Budget

- Per `select()` call: < 50 ms for catalogs up to 100 entries and up to 1000 telemetry rows. Pure in-process work, no network, no LLM, no container.
- Memory: O(catalog_entries + telemetry_rows) — fits in tens of MB at Phase-A scale.
- No dollar cost (no LLM calls). The Selector itself does not consume the `Budget` artifact; it only **reads** the dollar cap to flag over-budget candidates.

## 9. Open Questions

- **Telemetry confidence threshold.** How many historical runs constitute "enough" for `confidence=high`? Phase A heuristic: `min_runs_for_confidence=5`. Revisit once we have real telemetry distributions.
- **Cost normalization scope.** Cost subscore is normalized within the current candidate set, which means a single-candidate selection always gets cost subscore 1.0 (no comparison possible). Whether to instead normalize against a rolling baseline of recent selections is open. Phase A keeps within-set normalization for simplicity and reproducibility.
- **Equivalence-map subscore cap.** Setting the equivalence-map match at 0.85 (vs 1.0 for direct) is a heuristic. The right value depends on how lossy real-world cross-simulator mappings turn out to be in the initial domain; tune in PRD-004 acceptance.
- **Catalog entries with multiple per-host-class costs.** A simulator that has both a CPU and a GPU path may have very different `per_second_cost`. Phase A assumes the Catalog entry declares the cost for the *preferred* execution mode; multi-mode cost handling is deferred.
- **What if the metric is genuinely novel?** No catalog entry can compute it. `no_suitable_simulator` is the correct response, but a long tail of novel-metric hypotheses indicates Catalog growth pressure that C5 should see in aggregate. Reporting/dashboard surface deferred to spec 015.

## 10. TODO Checklist

- [ ] Scaffold `factory/selector/` from the canonical module template.
- [ ] Implement `SelectorWeights` loader + validator for `config/selector/weights.yaml` (raises `SelectorConfigError`).
- [ ] Implement compatibility filter against `Catalog.list_for_observable` + `Catalog.equivalence_pairs`.
- [ ] Implement per-candidate subscore functions (capability, license, cost, cross-sim, freshness) — each pure, individually testable.
- [ ] Implement cost estimator with telemetry / manifest / fallback source tracking.
- [ ] Implement cross-simulator partner resolution + selection-level `cross_simulator_available` aggregation.
- [ ] Implement ranking + ambiguity detection with deterministic tie-break.
- [ ] Implement failure-mode classification per §5.8 decision table.
- [ ] Implement trace emission to `runs/<cycle-id>/artifacts/<selection-hash>.trace.json` with the four reproducibility hashes.
- [ ] Implement `Selector.explain(result, candidate_id)` returning the rationale lines.
- [ ] Build mock surface: `Selector.mock_default()`, `Catalog.from_fixture("phase_a")` consumer, `TelemetryStub.no_history()`.
- [ ] Write `factory/selector/cli.py` with `select`, `explain`, `list-compatible` subcommands; all support `--mock-mode`.
- [ ] Author fixtures: `hypothesis_spec_sample.json`, `catalog_phase_a.json`, `weights_default.yaml`.
- [ ] Write the 10 mock-mode tests listed in §7.
- [ ] Write `tests/integration/test_selector_to_state_machine.py` (cross-module).
- [ ] Write `factory/selector/README.md` (≤ 1 page; mock-mode example as the headline).
- [ ] Write `docs/runbooks/selector-debugging.md` covering the failure-mode table and how to read a trace file (currently `[TBD-impl]`).
- [ ] Verify `mypy --strict factory/selector/` passes.
- [ ] Verify `python -m factory.selector select --mock-mode` works on a fresh checkout.
- [ ] PRD-004 acceptance: ranking on the Phase-A catalog returns the expected partner pair for the chosen cross-validatable observable.
