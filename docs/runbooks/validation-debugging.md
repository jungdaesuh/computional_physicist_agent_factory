# Runbook: Debugging the G4 Validation Portfolio

> What this covers: triaging a FAIL or inconclusive G4 outcome by walking the eight orthogonal checks (conservation, convergence, refinement, held-out symmetry, limiting cases, statistical validity, cross-simulator, provenance) in the `ValidationResult` artifact, with a hard-halt branch for `HeldoutLeakDetected` and the reweighting policy for missing cross-simulator. · When to use: a `ValidationResult.verdict == FAIL`, a `gate_outcome == inconclusive`, a `HeldoutLeakDetected` cycle halt, or any `ValidationError` subclass surfacing in `cycle.jsonl` from `module=validation`. · Estimated time: 20 minutes for a single check failure; 60 minutes for a cross-simulator disagreement requiring operator arbitration; immediate hard-halt response for `HeldoutLeakDetected`.

## 1. Prerequisites

- A failing cycle ID. Find it via `factory status` or `runs/`. The relevant subtree is `runs/<cycle-id>/validation/<candidate_id>/`.
- The `ValidationResult` artifact hash from the error trace. Locate via `runs/<cycle-id>/artifacts/MANIFEST.json` filtered on type `ValidationResult`.
- The `ExperimentSpec` that drove G4 (declares the domain, the simulator, the pre-registered metric).
- The `CandidateRunOutput` that G4 consumed. Persisted alongside the validation result under `runs/<cycle-id>/validation/<candidate_id>/`.
- `factory` CLI on `$PATH` for cycle-level operator commands. Validation-portfolio inspection is per-module: confirm with `python -m factory.validation --help`.
- Domain-config knowledge: `factory/validation/config/<domain>.yaml` declares conservation invariants, refinement grid factors, Richardson order, symmetry tolerance, limiting cases, min seeds, max relative std, and the cross-simulator policy. Read this file for the cycle's domain before triaging.

Mental model: **G4 is deterministic and orthogonal.** No LLM is ever called inside the portfolio. The verdict is binary (PASS / FAIL). The state machine maps that to a gate outcome of `pass`, `fail`, or `inconclusive` — the last only when cross-simulator was unavailable AND refinement+symmetry could not disambiguate (§5.10 of spec 009). Every check must run for diagnostics; the portfolio never short-circuits. If your `ValidationResult.check_outcomes` has fewer than eight entries, something stripped checks off the result — file a bug, do not patch around it.

The eight checks, with the error class each raises:

| # | Check | Error class | What it catches |
| :--- | :--- | :--- | :--- |
| 1 | Conservation invariants | `ConservationViolated` | Energy / mass / div B / momentum residuals beyond tolerance |
| 2 | Numerical convergence | `ConvergenceFailed` | Solver claims success but residual norm too high |
| 3 | Refinement (Richardson) | `RefinementInconsistent` | Grid too coarse; answer drifts under refinement |
| 4 | Held-out symmetry | `SymmetryHeldOutFailed` | Invariant hacking — passes seen invariants, fails unseen symmetries |
| 5 | Limiting cases | `LimitingCaseFailed` | Wrong answer in axisymmetric / Newtonian / one-electron limit |
| 6 | Statistical validity | `StatisticalInvalid` | Metric swap, insufficient seeds, or excessive variance |
| 7 | Cross-simulator | `CrossSimulatorDisagreement` | Two simulators disagree past equivalence-map tolerance |
| 8 | Provenance | `ProvenanceIncomplete` | A required hash / id / version is missing |

Plus one pre-flight that aborts before any check runs:

| 0 | Held-out fixture leak | `HeldoutLeakDetected` | Code-gen context referenced a symmetry fixture path |

## 2. Steps

### 2.1 Open the `ValidationResult` artifact

```bash
python -m factory.artifacts show runs/<cycle-id>/artifacts/<validation-result-hash>.json
```

The verdict, per-check outcomes, cross-simulator comparison, and reweighting flag are all in this single artifact. Default output is a summary table:

```
ValidationResult  hash=b4e9c2d...  verdict=FAIL  cycle=20260523-abc
  pre_registered_metric: L_grad_B = 7.42 (CI 95%: [7.18, 7.66])
  reweighted_for_missing_cross_sim: false
  duration_seconds: 38.9
  check_outcomes:
    conservation       PASS  residual=2.1e-13 tol=1e-12
    convergence        PASS  residual_norm=4.7e-9 tol=1e-8
    refinement         FAIL  delta=0.084 tol=0.02         <-- failing check
    symmetry_holdout   PASS
    limiting_case      PASS
    statistical        PASS
    cross_simulator    PASS  primary=7.42 secondary=7.39 tol=0.05
    provenance         PASS
```

If multiple checks fail, the portfolio still runs all eight — read every row, not just the first failure. Multiple correlated failures (e.g., conservation + symmetry) are a stronger signal than a single failure.

### 2.2 Open the per-check log

Every check writes a structured trace to:

```
runs/<cycle-id>/validation/<candidate-id>/portfolio.jsonl
```

One JSON line per check. Filter by `check_id`:

```bash
jq 'select(.check_id == "refinement")' runs/<cycle-id>/validation/<candidate-id>/portfolio.jsonl
```

Each line contains the check's `details` field — the structured diagnostics that the summary table elides. Refinement-check details include the full `{grid_h: metric_value}` map, observed convergence order, extrapolation result, and the comparison tolerance actually used (which may differ from the default if reweighting was active).

### 2.3 Triage by failing check

#### 2.3.1 `ConservationViolated` — Check #1

`details` example:
```json
{
  "check_id": "conservation",
  "passed": false,
  "tolerance": 1e-12,
  "residual": 3.4e-10,
  "details": {
    "per_invariant": {
      "energy":   {"residual": 2.1e-13, "tolerance": 1e-9,  "passed": true},
      "div_B":    {"residual": 3.4e-10, "tolerance": 1e-12, "passed": false},
      "momentum": {"residual": 4.5e-15, "tolerance": 1e-11, "passed": true},
      "W_MHD":    {"residual": 0.012,   "tolerance": 0.0,   "passed": true}
    }
  },
  "error_class": "ConservationViolated"
}
```

Read the per-invariant table. The violation here is on `div_B`. Steps:

1. **Confirm the adapter actually emitted the diagnostic.** A missing diagnostic for a required invariant is a hard fail in the check; check `CandidateRunOutput.conservation_diagnostics` keys against `cfg.conservation_invariants`.
2. **Decide: real physics violation or instrumentation bug?** Open the candidate's blueprint (`runs/<cycle-id>/sandbox/<i>/blueprint.py`) and trace how the residual was computed.
3. **If real violation:** the candidate is genuinely incorrect. The hypothesis falsifies the result via the EvidenceLedger; the state machine routes to `falsified`. The Generator-Verifier loop owns retry.
4. **If instrumentation bug:** the adapter's diagnostic computation has a bug. Fix in the adapter (spec 006), regenerate the candidate.
5. **Do NOT loosen `conservation_tolerances` to "make the check pass."** That is the trap of all G4 checks — loosening the defense to suit the candidate erases the gate. The tolerance is part of the experiment design.

#### 2.3.2 `ConvergenceFailed` — Check #2

`details` example:
```json
{
  "check_id": "convergence",
  "passed": false,
  "tolerance": 1e-8,
  "residual": 4.7e-6,
  "details": {
    "residual_norm": 4.7e-6,
    "iterations_used": 500,
    "iteration_cap": 500,
    "iter_cap_pegged": true
  },
  "error_class": "ConvergenceFailed"
}
```

Two distinguishable sub-cases:
1. **`iter_cap_pegged: true`.** Solver ran out of iterations. The Generator-Verifier loop's blueprint set the iter cap too low. Re-run with a higher cap (the loop owns this, not G4).
2. **`iter_cap_pegged: false` but residual high.** Solver gave up early or hit a stagnation. Likely a solver bug or a poor initial condition. Inspect the blueprint's solver-initialization code.

In either case, **do not increase `solver_residual_tolerance`** in the domain config to make the check pass.

#### 2.3.3 `RefinementInconsistent` — Check #3

`details` example for a 2-grid case:
```json
{
  "check_id": "refinement",
  "passed": false,
  "tolerance": 0.02,
  "residual": 0.084,
  "details": {
    "refinement_grid_values": {"1.0": 7.42, "0.5": 8.07},
    "relative_difference": 0.084,
    "richardson_tolerance_factor": 0.02,
    "mode": "two_grid_relative"
  },
  "error_class": "RefinementInconsistent"
}
```

For a 3-grid (Richardson) case:
```json
{
  "details": {
    "refinement_grid_values": {"1.0": 7.42, "0.5": 7.91, "0.25": 7.99},
    "observed_order": 2.6,
    "expected_order": 2.0,
    "extrapolated_value": 8.01,
    "claim_value": 7.42,
    "relative_extrapolation_gap": 0.074,
    "richardson_tolerance_factor": 0.02
  }
}
```

Actions:
1. **The candidate is grid-sensitive.** That is the failure mode — the base grid is too coarse, and the claimed metric drifts under refinement past the tolerance.
2. **Fix at the experiment level.** Raise the base grid resolution in `ExperimentSpec.fidelity_ladder` and rerun the Generator-Verifier loop with the new spec. The state machine signals this on a `RefinementInconsistent` fail.
3. **Special case: no refinement run supplied.** If the experiment did not ship a refinement tier and the domain config marks refinement as required, the check fails with `details.reason == "no_refinement_run_supplied"`. The Generator-Verifier loop should always ship at least two grids — if it did not, the loop's fidelity-ladder execution is broken.
4. **Wrong-order warning.** If `|observed_order - expected_order|` is large but the answer agrees, the check still passes (it is a warning, not a failure). Surfaced in `details` for postmortem.

#### 2.3.4 `SymmetryHeldOutFailed` — Check #4 (strongest invariant-hacking signal)

This is the defense against the failure mode described in `SPEC.md` §10.3. **Do not loosen the symmetry tolerance under any circumstance** — that is the architectural trap.

`details` example:
```json
{
  "check_id": "symmetry_holdout",
  "passed": false,
  "tolerance": 0.001,
  "residual": 0.018,
  "details": {
    "cases_run": 5,
    "cases_failed": ["reflection_across_stellarator_plane",
                     "rotation_2pi_over_Nfp"],
    "per_case": {
      "reflection_across_stellarator_plane":
        {"residual": 0.018, "tolerance": 0.001, "passed": false},
      "rotation_2pi_over_Nfp":
        {"residual": 0.014, "tolerance": 0.001, "passed": false},
      "swap_toroidal_index":
        {"residual": 1.2e-6, "tolerance": 0.001, "passed": true},
      ...
    },
    "fixture_path": "factory/validation/fixtures/symmetry/stellarator-mhd/"
  },
  "error_class": "SymmetryHeldOutFailed"
}
```

Actions:
1. **Quarantine the candidate.** A candidate that fails held-out symmetry has almost certainly hacked the visible invariants. Mark the hypothesis `falsified` with a strong invariant-hacking annotation in the EvidenceLedger entry.
2. **Audit recent code-gen prompts.** A symmetry leak (Check #0) is the only legitimate way the candidate could have known about these tests. Run `python -m factory.validation verify-holdout-isolation` to re-confirm isolation; if it passes, the candidate genuinely overfit by accident on the visible invariants — accept the falsification.
3. **Do NOT loosen `symmetry_tolerance`.** Specifically excluded from any "tighten the gate later" allowance.
4. **Do NOT rotate the fixture set in response.** That makes the defense weaker, not stronger. Rotation is a Phase B concern.

#### 2.3.5 `LimitingCaseFailed` — Check #5

`details` example:
```json
{
  "check_id": "limiting_case",
  "passed": false,
  "tolerance": 0.01,
  "residual": 0.13,
  "details": {
    "case_id": "axisymmetric_limit",
    "transform_fn": "factory.validation.limits.stellarator.to_axisymmetric",
    "expected_value": 1.842,
    "observed_value": 2.082,
    "relative_error": 0.13
  },
  "error_class": "LimitingCaseFailed"
}
```

Actions:
1. The candidate produces the wrong answer in the limit (axisymmetric stellarator should reduce to the analytic tokamak; Newtonian limit of a relativistic solver; one-electron DFT to hydrogenic energies). Genuine physics bug.
2. Inspect the `transform_fn` to confirm it correctly produces the limit configuration; rare but possible that the transform itself is buggy.
3. If the transform is correct, the candidate's blueprint has a physics error. Falsify the hypothesis.

#### 2.3.6 `StatisticalInvalid` — Check #6 (cherry-picking detection)

The most semantically tight check. Subcases:

```json
{
  "check_id": "statistical",
  "passed": false,
  "details": {
    "reason": "metric_swap",
    "experiment.pre_registered_metric": "L_grad_B",
    "candidate.pre_registered_metric_name": "max_elongation"
  },
  "error_class": "StatisticalInvalid"
}
```

This is the cherry-picking failure: the experiment was pre-registered on `L_grad_B` and the candidate reported `max_elongation`. **This is non-negotiable.** Reject the candidate; do not let the state machine re-run with a re-registered metric — that defeats the pre-registration defense.

Other subcases:
- `reason: "insufficient_seeds"` — `len(candidate.seed_values) < cfg.min_seeds`. Re-run the Generator-Verifier loop with more seeds in `ExperimentSpec.seed_set`.
- `reason: "excessive_variance"` — `std / |mean| > cfg.max_relative_std`. The candidate's per-seed variance is too high. Either rerun with more seeds (statistical) or accept the hypothesis as `inconclusive`.

The 95% CI computation:
```python
details["ci_method"] == "t_interval"  # or "bootstrap" if N >= some threshold
details["ci_seed"] == <int>           # if bootstrap was used, recorded for determinism
```

Reproducibility of the CI is asserted by `test_validation_determinism.py`; if the CI changes across runs of the same inputs, file a bug.

#### 2.3.7 `CrossSimulatorDisagreement` — Check #7

`details` example:
```json
{
  "check_id": "cross_simulator",
  "passed": false,
  "details": {
    "primary_simulator_id": "vmecpp",
    "primary_simulator_version": "0.4.2",
    "secondary_simulator_id": "desc",
    "secondary_simulator_version": "1.1.0",
    "primary_value": 7.42,
    "secondary_value": 8.91,
    "tolerance": 0.05,
    "comparison_kind": "relative",
    "relative_difference": 0.169,
    "equivalence_map_version": "stellarator-mhd-v3"
  },
  "error_class": "CrossSimulatorDisagreement"
}
```

This is the highest-signal disagreement G4 can produce. Two simulators independently computed the same observable and disagreed past the equivalence-map tolerance. Actions:

1. **Do not pick a winner programmatically.** The state machine surfaces the disagreement to the operator for arbitration (the `inconclusive` branch may or may not trigger depending on whether refinement+symmetry passed — see §5.10 of spec 009).
2. **Inspect both simulators' published agreement bounds.** Open `factory/catalog/simulators/<primary>.yaml` and `factory/catalog/simulators/<secondary>.yaml`; cross-reference their `cross_simulator_equivalence_map[<observable>].tolerance`. If the tolerance is too tight (rare) or too loose (common), the map quality is the bug, not the candidate.
3. **Compare simulator versions.** Disagreement after a simulator version bump is a regression signal; mark `relitigate_if` triggers for both simulator versions to force re-litigation if either updates.
4. **Reject `inconclusive` is not a synonym for `pass`.** An `inconclusive` outcome does not promote the hypothesis to the EvidenceLedger as `passed`; it is recorded as `inconclusive` with the cross-simulator gap fully documented.

#### 2.3.8 `ProvenanceIncomplete` — Check #8

`details` example:
```json
{
  "check_id": "provenance",
  "passed": false,
  "details": {
    "missing_fields": ["container_sha"]
  },
  "error_class": "ProvenanceIncomplete"
}
```

A required hash, id, or version is null. The check is mechanical: every field of `ProvenanceBlock` must be populated. Possible causes:
- The container build pipeline did not emit a SHA (build-system bug).
- The simulator adapter returned an unversioned binary (catalog-entry bug — every simulator must report a version per spec 004).
- The seed was null but the experiment is not seedless (Phase A disallows seedless experiments).

Fix at the source. **Never write a validation result to the ledger with an incomplete provenance block** — that is the architectural firewall.

#### 2.3.9 Reweighting policy (cross-simulator unavailable)

If the cross-simulator check could not run (no secondary available AND `cfg.require_cross_simulator == False`), the portfolio applies §5.7.3 reweighting:

| Check | Default tolerance | Tightened tolerance (when reweighted) |
| :--- | :--- | :--- |
| Refinement | `richardson_tolerance_factor` | `richardson_tolerance_factor / 2` |
| Symmetry held-out | `symmetry_tolerance` | `symmetry_tolerance / 2` |

The reweighting happens **before** those checks run. The actual tolerance used is recorded in `CheckOutcome.tolerance`, and `ValidationResult.reweighted_for_missing_cross_sim` is `true`.

To confirm reweighting was applied:
```bash
jq '.reweighted_for_missing_cross_sim' runs/<cycle-id>/artifacts/<validation-result-hash>.json
# true

jq '.check_outcomes[] | select(.check_id == "refinement") | .tolerance' \
   runs/<cycle-id>/artifacts/<validation-result-hash>.json
# 0.01 (instead of the default 0.02)
```

If you see `reweighted_for_missing_cross_sim: true` and the refinement / symmetry tolerances do NOT show the tightened values, the reweighting logic broke — file a bug.

**Required vs. reweighted.** If the domain config sets `require_cross_simulator: true`, the absence of a secondary fails the cross-simulator check directly (`CrossSimulatorDisagreement` with `reason: "secondary_unavailable_and_required"`). Reweighting only kicks in when `require_cross_simulator: false`.

#### 2.3.10 Map verdict to gate outcome (`inconclusive` branch)

The state machine (spec 003) converts `ValidationResult.verdict` to a G4 gate outcome:

```
if verdict == PASS:
    gate_outcome = "pass"
elif (cross_simulator_comparison.secondary_simulator_id is None
      and not (refinement_outcome.passed and symmetry_outcome.passed)):
    gate_outcome = "inconclusive"
else:
    gate_outcome = "fail"
```

Manually verify by inspecting the artifact:
```bash
python -m factory.artifacts show runs/<cycle-id>/artifacts/<validation-result-hash>.json --format json | \
  jq '{
    verdict,
    secondary: .cross_simulator_comparison.secondary_simulator_id,
    refinement_passed: (.check_outcomes[] | select(.check_id=="refinement") | .passed),
    symmetry_passed: (.check_outcomes[] | select(.check_id=="symmetry_holdout") | .passed)
  }'
```

If verdict is FAIL, no secondary was available, AND both refinement and symmetry passed → the gate outcome should be `fail` (the remaining failure was elsewhere). If refinement OR symmetry failed AND no secondary was available → the gate outcome should be `inconclusive`.

### 2.4 The `HeldoutLeakDetected` hard-halt

`HeldoutLeakDetected` is the **only** path that aborts before any check runs. It fires when the pre-flight `_verify_no_holdout_leak(candidate.candidate_context_paths)` detects that the code-gen context included a path under `factory/validation/fixtures/symmetry/<domain>/`.

When this fires:

1. **The cycle hard-halts.** Do not retry. Do not loosen the leak detector. The defense itself is compromised.
2. **Audit the visibility configuration.** Run `python -m factory.validation verify-holdout-isolation` (CI step):
   ```bash
   python -m factory.validation verify-holdout-isolation
   ```
   Expected output on a healthy system:
   ```
   ok: symmetry fixture dir not in code-gen allowlist
   ok: no prompt template references symmetry directory
   ok: no committed candidate_context references symmetry directory
   ```
3. **Identify the leak source.** Compare the symmetry directory path to:
   - `factory/genver/config/code_gen_visible_paths.yaml` (or equivalent allowlist) — must not include the symmetry dir.
   - Any prompt template under `factory/genver/prompts/` — `grep -r 'symmetry' factory/genver/prompts/` should return nothing.
   - The candidate's recorded `candidate_context_paths` — read from `runs/<cycle-id>/validation/<candidate-id>/`.
4. **Remove the leak before any further G4 runs in this domain.** Until isolation is re-established, the held-out-symmetry defense is compromised across the whole domain. The state machine must refuse to run G4 for this domain until the next successful `verify-holdout-isolation` CI step.
5. **Quarantine prior validations in the same domain since the suspected leak time.** If a leak existed for N hours and M cycles ran G4 in that window, those M cycles' `SymmetryHeldOutFailed` PASS results are not trustworthy. C5 (program direction) should re-audit them.

### 2.5 Reproduce the failure in mock mode

```bash
python -m factory.validation run \
  --experiment-fixture sample_passing \
  --candidate-fixture <failing-candidate-fixture> \
  --mock-mode
```

Mock-mode candidates are committed under `factory/validation/fixtures/results/`:

- `passing_candidate.json` — all eight checks pass.
- `refinement_inconsistent.json` — two grids disagree past tolerance.
- `conservation_violated.json` — energy drift above tolerance.
- `symmetry_failed.json` — invariant-hacking signature.
- `cherry_picked_metric.json` — metric swap.
- `holdout_leak.json` — pre-flight `HeldoutLeakDetected`.

Reproducing against committed fixtures is the fastest way to confirm the check logic itself works; if mock mode passes the same fixture that live mode failed on, the bug is in the candidate-output pipeline (spec 008 → spec 009 handoff), not in the portfolio.

### 2.6 Run a single check in isolation

For triage you do not need to rerun the whole portfolio:

```bash
python -m factory.validation check \
  --check-id refinement \
  --experiment runs/<cycle-id>/artifacts/<experiment-hash>.json \
  --candidate runs/<cycle-id>/validation/<candidate-id>/candidate.json
```

Returns the same `CheckOutcome` as the full portfolio would have produced for that check.

## 3. Verification

After applying any fix, confirm:

1. **The `ValidationResult` for the new candidate passes.** Re-run the portfolio in mock mode against the corrected candidate fixture:
   ```bash
   python -m factory.validation run --experiment-fixture <fix> --candidate-fixture <fix> --mock-mode
   python -m factory.artifacts show runs/<new-cycle-id>/artifacts/<new-result-hash>.json
   ```
2. **All eight checks ran.** `jq '.check_outcomes | length' <result>.json` must equal 8. If less than 8, the no-short-circuit invariant was violated — file a bug.
3. **The verdict is consistent with the per-check outcomes.** `ValidationResult._verdict_consistent_with_checks` is a model validator that runs at artifact construction; a violation would have surfaced as an `ArtifactValidationError` at write time. If you see a result on disk that violates this invariant, the artifact was tampered with — see `artifacts-debugging.md`.
4. **`verify-holdout-isolation` still passes.** Especially after any change to prompt templates, allowlists, or fixture paths:
   ```bash
   python -m factory.validation verify-holdout-isolation
   ```
5. **No-LLM-dependency contract holds.** `factory/validation/` must not import any LLM SDK; enforced by `import-linter`:
   ```bash
   import-linter --config pyproject.toml
   ```
6. **Determinism preserved.** Re-running the same `(experiment, candidate)` produces the same `inputs_hash` and the same per-check pass/fail:
   ```bash
   pytest factory/validation/tests/test_validation_determinism.py -q
   ```
7. **CI step for held-out isolation still blocks merges.** Confirm by intentionally adding a symmetry-path reference to a prompt template and running the CI step; it must fail.
8. **Reweighting policy verified after policy change.** If you touched the cross-simulator reweighting, the test:
   ```bash
   pytest factory/validation/tests/test_cross_simulator.py -q
   ```

## 4. Troubleshooting

| Symptom | Likely cause | First action |
| :--- | :--- | :--- |
| `ValidationResult.check_outcomes` has fewer than 8 entries | Portfolio short-circuited on first failure (forbidden) | File a bug; the no-short-circuit invariant is mandatory for diagnostic completeness |
| `ConservationViolated` on `div_B` only | Magnetic-field divergence cleaning is broken in the candidate's blueprint | Check blueprint's solver step that cleans `∇·B`; if missing, the candidate is incorrect |
| `RefinementInconsistent` with `details.mode == "two_grid_relative"` but the spec wanted Richardson | Only two grids supplied; spec 008 should have shipped ≥3 for Richardson | File against spec 008 fidelity-ladder execution |
| `RefinementInconsistent` with `observed_order` very far from `expected_order` | Solver is not formally convergent at the expected order | Open question per spec 009 §9; for now, document the discrepancy and consider tightening `richardson_required_order` |
| `SymmetryHeldOutFailed` with all 5 cases failing | Strong sign of invariant hacking; possibly a leak | Run `verify-holdout-isolation` immediately; if it passes, accept the falsification |
| `SymmetryHeldOutFailed` with 1 of 5 cases failing | Could be a genuine partial-invariant violation; could be a fixture bug | Inspect the fixture's `transform_fn`; if the transform itself has a bug, fix and rerun |
| `StatisticalInvalid` with `reason: "metric_swap"` | Generator-Verifier loop computed a different metric than pre-registered | Audit spec 008's metric extraction; the pre-registered metric is the only allowed report |
| `StatisticalInvalid` with `reason: "excessive_variance"` after seeding with 3 | Phase A `min_seeds = 3` is the floor; some experiments need more | Bump `ExperimentSpec.seed_set` and rerun; do not loosen `max_relative_std` |
| `CrossSimulatorDisagreement` with primary and secondary values very close in absolute terms | Tolerance configured as relative; small absolute differences may be relatively large | Inspect `details.comparison_kind`; verify the equivalence-map's tolerance kind |
| `CrossSimulatorDisagreement` immediately after a Catalog update | Map version changed; old equivalence might have been invalidated | Inspect `details.equivalence_map_version`; relitigate if needed |
| `cross_simulator` check shows `secondary_simulator_id: null` and `reweighted_for_missing_cross_sim: false` | Domain config has `require_cross_simulator: true` and no secondary was available | The fail is correct; the operator must either install a secondary simulator or change the domain policy (a high-bar decision) |
| `cross_simulator` shows null secondary AND `reweighted_for_missing_cross_sim: true` AND refinement/symmetry tolerances at default values | Reweighting logic broken | File a bug |
| `ProvenanceIncomplete` mentions `container_sha` missing | Container build did not emit SHA | Spec 004 catalog onboarding bug |
| `ProvenanceIncomplete` mentions `seed` null | Experiment was seedless (forbidden in Phase A) | Spec 008 should never have run without a seed; file a bug |
| `HeldoutLeakDetected` raised on a normal-looking candidate | Code-gen prompt template was recently changed and now mentions the symmetry path | `grep -r 'symmetry' factory/genver/prompts/`; revert |
| `ValidationResult.verdict == PASS` but a downstream council still rejected | Council C3 (claim interpretation) operates on top of a passing G4; council decisions are not constrained by G4 PASS to also PASS | Read the council verdict; consult `runbooks/council-debugging.md` (if extant) |
| Portfolio took > 60 seconds | Cross-simulator re-run on the secondary; long runtime is the secondary's cost, not the portfolio's | Confirm via `duration_seconds` per check; if `cross_simulator` dominates, that is expected |
| Two cross-simulator runs in a row disagree, then agree | Non-determinism in the secondary (rare but observed) | File against the catalog entry's determinism guarantees |
| `ValidationError` raised but no `ValidationResult` written | Portfolio crashed mid-check before assembling the result | File a bug; the orchestrator's `run()` should always assemble a result, even on internal errors |
| `verify-holdout-isolation` passes locally but CI fails | Local checkout has a different code-gen allowlist than CI | Re-sync from main; ensure the CI step reads the same config the local tool does |
| All checks pass except `provenance` reports `env_hash` mismatch | The candidate ran in a different env from what was recorded | Spec 013 / spec 004 — env-hash provenance bug |

## 5. Related

- Spec 009 (Validation Portfolio G4) — owns every check listed in this runbook.
- Spec 002 (Typed Artifacts) — owns the `ValidationResult`, `CheckOutcome`, and `CrossSimComparison` shapes; consult `runbooks/artifacts-debugging.md` if the result artifact itself is malformed.
- Spec 003 (Gate State Machine) — owns the `pass`/`fail`/`inconclusive` mapping (§5.10 of spec 009) and the routing on `HeldoutLeakDetected`.
- Spec 004 (Simulator Catalog) — owns `cross_simulator_equivalence_map` quality; if the cross-simulator tolerance is wrong, that is the spec to update.
- Spec 008 (Generator-Verifier Loop) — produced the `CandidateRunOutput` G4 is consuming. If the candidate's diagnostics are malformed, see `runbooks/genver-debugging.md`.
- Spec 012 (Evidence Ledger) — destination for every `ValidationResult`; the ledger's `relitigate_if` triggers (cross-simulator gap, equivalence-map version) gate re-runs.
- `docs/specs/009-validation-portfolio.md` §5.4 (Held-out symmetry tests) — the architectural specification of the held-out access-isolation invariant.
- `docs/specs/009-validation-portfolio.md` §5.7.3 (Reweighting policy when cross-simulator is unavailable) — the precise definition of which tolerances tighten and by how much.
- `docs/specs/009-validation-portfolio.md` §5.10 (Mapping the verdict to a G4 gate outcome) — the only place the `inconclusive` branch is introduced.
- `SPEC.md` §10.3 (Invariant hacking) — the underlying failure mode the held-out symmetry check defends against.
- `SPEC.md` §8 (Validation Portfolio) — the row-by-row table of checks and what each catches.
- `factory/validation/tests/test_validation_typical_usage.py` — canonical pass-path test; copy this pattern for new check-coverage tests.
- `runbooks/operator-cli.md` — operator commands for inspecting validation results and arbitrating cross-simulator disagreements.
