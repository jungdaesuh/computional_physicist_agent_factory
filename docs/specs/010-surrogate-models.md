# Spec 010: Surrogate Models

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- The **Surrogate Models** module is the cheap-probe substrate behind gate **G3**. Given an `ExperimentSpec` candidate, a trained surrogate predicts the target observable plus a calibrated uncertainty, and a **mandatory OOD detector** decides whether that prediction is trustworthy. OOD candidates bypass the surrogate and escalate directly to the G4 oracle.
- The 5 facts: (1) surrogate-type pluggable (random forest, MLP, Gaussian process; one trained model per observable in Phase A); (2) training data is sourced from `EvidenceLedgerEntry` rows (queried via the spec 012 `EvidenceLedgerReader` narrow read view) tagged with the same observable + simulator family; (3) **OOD detection is required** — the surrogate never returns a pass for OOD inputs; (4) Phase A surrogates are *static* — retraining requires operator approval; (5) the public output is a `SurrogateProbeResult` artifact consumed by the gate state machine (spec 003).
- Open first: `factory/surrogate/api.py` and the typical-usage test.

## ENTRY POINTS
- Main module: `factory/surrogate/api.py`
- Typical-usage test: `factory/surrogate/tests/test_surrogate_typical_usage.py`
- CLI: `python -m factory.surrogate --help` (subcommands: `train`, `predict`, `ood-check`, `list-models`, `show-card`)
- Mock-mode example: `python -m factory.surrogate predict --observable max_elongation --candidate-fixture sample_experiment_spec --mock-mode`
- Runbook: `docs/runbooks/surrogate-training.md`

## LOCAL DEBUG
- Instantiate without trained models: `SurrogateRegistry.mock_registry()` returns a fixture registry whose `predict()` returns a deterministic `SurrogateProbeResult`.
- Live mode requires: a populated `Ledger` store (spec 012) reachable via an `EvidenceLedgerReader` handle, plus a `SurrogateModelStore` directory (default `surrogates/<observable>/<model_id>/`) containing `model.bin`, `card.json`, `training_set_hash.txt`.
- Common error signatures → recovery:
  - `NoTrainedSurrogate` → no model registered for the requested observable; state machine routes candidate directly to oracle.
  - `SurrogateConfidenceTooLow` → reserved class; never raised in production. The signal is carried on `SurrogateProbeResult.confidence_too_low=True` → state machine escalates to G4 oracle.
  - OOD signal → likewise carried as `SurrogateProbeResult.ood_flag=True`; `OODDetected` exists in `api.py` solely as a reserved class for a catastrophic-audit fail-fast hook, never raised by `predict()`.
  - `TrainingSetTooSmall` → too few ledger rows to train; raised by `train()` only; halts retraining.
  - `ModelLoadFailed` → on-disk artifact corrupt or schema-incompatible; surfaces at startup; halt rather than silently fall back.
- Logs to inspect: every prediction writes a structured event to `runs/<cycle-id>/cycle.jsonl` under `module=surrogate`, with `{observable, model_id, ood_flag, predicted_value, uncertainty, training_set_hash}`.

## DEPENDENCIES
- **Hard:** Spec 002 (artifacts) — consumes `ExperimentSpec`, emits `SurrogateProbeResult` (defined in spec 002 §4). Spec 012 (`Ledger` store, accessed via `EvidenceLedgerReader`) — training-data source.
- **Soft:** Spec 014 (telemetry) — emits events if available. Spec 013 (budget) — predict-time cost is negligible but tracked when a budget context is provided. `specs/016-strategy-archive.md` (Phase B active-learning hook, FIX_PLAN §26.4) — after a successful surrogate retrain, the archive may use the surrogate's posterior variance at a candidate point as a **fallback surprise signal** when the `GuideLLM` belief-elicitation path is unavailable. The hook is read-only from this module's perspective: the registry exposes the surrogate's `predict_with_uncertainty(...)` output and the archive maps `sigma` → surrogate-derived surprise via its own scaling rule. Not exercised in Phase A.
- **Mocks available:** `SurrogateRegistry.mock_registry()` returns a deterministic fixture registry; `MockSurrogateModel` exposes a configurable `predict` for downstream tests.

---

## 1. Summary

This module is the **cheap-probe substrate** of the factory: it sits between the tractability dry-run (G2.5) and the expensive validation portfolio (G4). For each `ExperimentSpec` candidate, the surrogate predicts the target observable plus a calibrated uncertainty, and a distance-to-training-distribution OOD detector decides whether that prediction is trustworthy at all. OOD candidates *do not* get a surrogate-pass — they route directly to the G4 oracle. This is the central defense against the failure mode in `SPEC.md` §10.6 (surrogate inherits training-set blind spots).

## 2. Scope

**In scope:**
- A `SurrogateRegistry` mapping `observable → trained model(s)` with metadata cards.
- Pluggable surrogate types: random forest, MLP, Gaussian process (Phase A targets one trained model per observable).
- Training pipeline: query `EvidenceLedgerEntry` rows via `EvidenceLedgerReader.query_observable(...)` (spec 012 narrow read view), extract `(input_features, true_value)` pairs, train, persist model + `SurrogateCard` (metadata + training-set hash).
- Inference: given an `ExperimentSpec`, return `SurrogateProbeResult(predicted_value, uncertainty, ood_flag, pass_vs_baseline)`.
- **OOD detection (mandatory):** distance-to-training-distribution percentile threshold; configurable per observable. OOD candidates are flagged, never silently accepted.
- Retraining cadence: configurable; default = monthly OR when the `Ledger` store has ≥`N_new_entries_threshold` new `EvidenceLedgerEntry` rows for the observable; Phase A requires **operator approval before retrain runs**.
- CLI with `train`, `predict`, `ood-check`, `list-models`, `show-card` subcommands.
- Mock mode for offline development.

**Out of scope:**
- Active learning / acquisition-function selection of next experiments (Phase B).
- Online incremental updates (Phase B; Phase A retrains as a batch with operator approval).
- Multi-fidelity / co-Kriging surrogates (Phase B).
- Replacement of the G4 portfolio (the surrogate is a *probe*, not a verifier).
- Probabilistic-programming or Bayesian-deep-learning backends beyond a vanilla GP (Phase B).

## 3. Public Interface

```python
# factory/surrogate/api.py

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence
from factory.artifacts import (
    ExperimentSpec, SurrogateProbeResult, ArtifactHash, HypothesisId,
)
from factory.ledger import EvidenceLedgerReader, LedgerTrainingRow  # narrow read view exported by spec 012

class SurrogateError(FactoryError): ...
class NoTrainedSurrogate(SurrogateError): ...
class OODDetected(SurrogateError): ...           # USUALLY carried as a flag, not raised
class SurrogateConfidenceTooLow(SurrogateError): ...
class TrainingSetTooSmall(SurrogateError): ...
class ModelLoadFailed(SurrogateError): ...

SurrogateKind = Literal["random_forest", "mlp", "gaussian_process"]

@dataclass(frozen=True)
class SurrogateCard:
    """Metadata for a trained surrogate. Persisted alongside model.bin as card.json."""
    model_id: str
    observable: str
    surrogate_kind: SurrogateKind
    training_set_hash: ArtifactHash      # hash of the (sorted) EvidenceLedgerEntry provenance hashes used
    n_training_examples: int
    feature_schema_version: int
    trained_at: str                      # ISO8601
    metrics: dict[str, float]            # held-out RMSE, R^2, calibration error
    ood_detector_kind: Literal["knn_pca", "mahalanobis", "isolation_forest"]
    ood_threshold_percentile: float      # canonical field; default 0.95 → false-positive rate 1-p
    ood_pca_components: int              # effective reduced dimension (≤ 20 in Phase A)
    ood_knn_k: int                       # k for knn_pca detector; default 5
    confidence_floor: float              # uncertainty above this → escalate to oracle
    notes: str

@dataclass(frozen=True)
class TrainingDataQuery:
    observable: str
    simulator_family: str | None = None
    min_provenance_complete: bool = True
    min_rows: int = 50
    max_rows: int | None = None

class SurrogateRegistry:
    """Lookup + lifecycle for trained surrogates."""

    def __init__(
        self,
        store_root: Path = Path("surrogates"),
        evidence_ledger_handle: EvidenceLedgerReader | None = None,
        mock_mode: bool = False,
    ) -> None: ...

    def predict(
        self,
        observable: str,
        candidate: ExperimentSpec,
        baseline_value: float | None = None,
    ) -> SurrogateProbeResult:
        """Return predicted value + uncertainty + ood_flag + pass/fail vs baseline.

        Raises NoTrainedSurrogate if no surrogate exists for this observable.
        Never raises OODDetected — instead sets ood_flag=True on the result.
        Never raises SurrogateConfidenceTooLow — instead sets confidence_too_low=True.
        """

    def train(
        self,
        observable: str,
        kind: SurrogateKind,
        query: TrainingDataQuery,
        operator_approval_token: str,    # Phase A guard
    ) -> SurrogateCard:
        """Train a new surrogate from EvidenceLedgerEntry rows. Persists to store_root."""

    def list_models(self) -> Sequence[SurrogateCard]:
        """Return cards for every registered surrogate."""

    def ood_check(
        self,
        observable: str,
        candidate: ExperimentSpec,
    ) -> "OODReport":
        """Run only the OOD check; no value prediction. Used by spec 003 for diagnostics."""

    @classmethod
    def mock_registry(cls) -> "SurrogateRegistry":
        """Deterministic fixture registry for tests."""

@dataclass(frozen=True)
class OODReport:
    observable: str
    model_id: str
    ood_flag: bool
    distance_metric: str                  # "knn_k5_pca", "mahalanobis", "isolation_forest"
    distance_value: float                 # candidate's score under distance_metric
    threshold_distance: float             # the percentile-derived cutoff (numeric distance corresponding to card.ood_threshold_percentile)
    nearest_training_indices: list[int]   # top-k for diagnostics

# EvidenceLedgerReader and LedgerTrainingRow are defined in spec 012 §3 as the
# narrow read view that the Ledger module exposes to surrogate training. This
# spec is a pure consumer: it calls `reader.query_observable(q)` and receives
# `Sequence[LedgerTrainingRow]`. The Ledger module owns the type definitions,
# the SQLite-backed implementation, and the live-vs-mock toggle.
```

### 3.1 `SurrogateProbeResult` (defined in spec 002 §4)

This module is the sole producer of `SurrogateProbeResult`. The artifact carries: `observable`, `model_id`, `predicted_value`, `uncertainty`, `ood_flag: bool`, `confidence_too_low: bool`, `pass_vs_baseline: Literal["pass", "fail", "escalate"]`, `baseline_value`, `training_set_hash`, and the usual provenance fields. The state machine at G3 reads `pass_vs_baseline`:

- `pass` → continue to G4 with surrogate-blessed status.
- `fail` → kill candidate; emit `EvidenceLedgerEntry(result="falsified")`.
- `escalate` → either `ood_flag=True` or `confidence_too_low=True`; state machine routes directly to G4 oracle, bypassing surrogate verdict.

## 4. Data Structures / Schemas

The Pydantic `SurrogateProbeResult` lives in spec 002. Module-local types in `factory/surrogate/types.py`:

```text
SurrogateCard          — metadata + training_set_hash + OOD config
TrainingDataQuery      — narrow query parameter object passed to EvidenceLedgerReader.query_observable
LedgerTrainingRow      — (feature_vector, true_value, provenance_hash)
OODReport              — diagnostic output of ood_check()
FeatureSchema          — TBD: canonical mapping ExperimentSpec → feature vector
```

**Persistence layout:**

```
surrogates/
  <observable>/
    <model_id>/
      model.bin            backend-specific (sklearn .joblib, torch .pt, gpytorch .pt)
      card.json            SurrogateCard
      training_set_hash.txt
      feature_schema.json
      ood_detector.bin     fitted detector (Mahalanobis params, kNN index, etc.)
```

The active model per observable is selected by `card.json:active=true` (one and only one). Older trained models are kept for audit but inactive.

## 5. Algorithms / Logic

### 5.1 Feature extraction from `ExperimentSpec`

TODO — define canonical mapping. Sketch:
- Flatten `control_definition` numeric fields (coefficients, geometric parameters) into a fixed-order vector keyed by `feature_schema_version`.
- Hash + version the schema so a schema change invalidates every existing surrogate.
- Non-numeric fields (simulator_id, kill_criteria strings) are excluded or one-hot encoded as documented in `feature_schema.json`.

### 5.2 Training pipeline (`train`)

```text
1. Verify operator_approval_token (Phase A guard).
2. q = TrainingDataQuery(observable, simulator_family, ...)
3. rows = evidence_ledger.query_observable(q)
   if len(rows) < q.min_rows → raise TrainingSetTooSmall.
4. X, y = stack(feature_vectors), stack(true_values)
5. Fit chosen backend (sklearn RF / torch MLP / gpytorch GP).
6. OOD detector pipeline (in order):
     a. Fit PCA on X; retain top components ≥0.95 cumulative variance, cap at `pca_max_components=20`. Persist transform.
     b. Project X → X_pca.
     c. Fit detector on X_pca (default `knn_pca` with `k=5`).
     d. Compute training leave-one-out distances on X_pca; cache `threshold_distance = quantile(loo_distances, card.ood_threshold_percentile)` inside the detector blob.
7. Held-out eval (k-fold or fixed split): RMSE, R^2, calibration error.
8. Compute training_set_hash = sha256(sorted(row.provenance_hash for row in rows)).
9. Persist model.bin + ood_detector.bin (includes PCA + detector + cached threshold_distance) + card.json + training_set_hash.txt.
10. Emit telemetry event: {observable, model_id, n_training_examples, metrics}.
```

### 5.3 Inference pipeline (`predict`)

```text
1. Resolve active card for observable. If none → raise NoTrainedSurrogate.
2. x = featurize(candidate, card.feature_schema_version).
3. ood_detector loads its cached training-percentile cutoff:
     threshold_distance = quantile(train_loo_distances, card.ood_threshold_percentile).
   (Computed and persisted at train time alongside `ood_detector.bin`.)
4. ood = ood_detector.score(x); ood_flag = ood.distance > threshold_distance.
5. y_pred, sigma = model.predict_with_uncertainty(x).
6. confidence_too_low = (sigma > card.confidence_floor).
7. If ood_flag or confidence_too_low → pass_vs_baseline = "escalate".
   Else if baseline_value is None → pass_vs_baseline = "escalate" (defensive).
   Else compare y_pred ± k·sigma vs baseline_value with the observable's directionality (lower-is-better vs higher-is-better) →
     "pass" if predicted-with-margin strictly beats baseline, else "fail".
8. Build SurrogateProbeResult, persist, return.
```

The detector never reads `card.ood_threshold_percentile` directly at predict-time; the cached `threshold_distance` is the load-bearing value. The percentile is metadata that lets retraining reproduce the cutoff.

### 5.4 OOD detection (mandatory — do NOT skip)

The OOD detector is fit at training time and persisted alongside the model.

**Dimensionality first.** ConStellaration-class problems have ~80 raw boundary-coefficient features. Mahalanobis distance degrades sharply in high dimensions: the covariance matrix becomes ill-conditioned, sample distances concentrate (curse of dimensionality), and the 95th-percentile cutoff loses discriminative power. Phase A therefore standardizes on a **PCA-reduced feature space** for OOD scoring:

- At train time, fit PCA on the training feature matrix; retain the top components covering ≥0.95 cumulative variance, capped at `pca_max_components = 20`. The PCA transform is persisted alongside `ood_detector.bin`.
- All detector scoring (predict-time and the leave-one-out training-distribution build) operates in the PCA-reduced space.
- The reduced-dimension cap is the same knob that gates which detector is admissible.

Supported detectors:

- **kNN distance with k=5** in PCA-reduced space — **Phase A default**. Non-parametric, robust to multi-modal training clouds, well-behaved at d ≤ 20.
- **Mahalanobis distance** — opt-in **only** for low-d feature sets (effective PCA-reduced dimension < 20 AND covariance condition number under a configured threshold). Documented as a default-off backstop for elliptical training clouds.
- **Isolation Forest** decision-function score — opt-in; robust to scale; harder to calibrate; reserved for cases where kNN PCA performs poorly on held-out audits.

**Threshold semantics.** Threshold is a **training-percentile**, not an absolute distance, and `ood_threshold_percentile` is the canonical field name (drop any prior `ood_threshold_value` usage). Default: `ood_threshold_percentile = 0.95`. The numeric cutoff is the `p`-th percentile of the **training-set leave-one-out kNN distance** distribution: for each training point, remove it, score it against the remaining `n-1`, record the distance; then take `quantile(distances, p)`. This is computed once at train time and cached as `threshold_distance` inside the detector blob.

Pinning the cutoff at the `p`-th training percentile **hardcodes the false-positive rate at `1 - p`** (≈5% in-distribution candidates are incorrectly flagged at `p=0.95`). The percentile is per-observable configurable in `surrogates/<observable>/<model_id>/card.json`; raise it (e.g., 0.99) when in-distribution false-positives are too costly and lower it when missing true OOD is worse.

**Phase A rule:** OOD candidates *never* earn a surrogate-pass. They escalate to oracle. No exceptions, no override flag. This is the architectural defense against `SPEC.md` §10.6.

### 5.5 Retraining cadence

TODO — flesh out. Sketch:
- Default trigger: monthly cron OR `evidence_ledger.count_new_rows_since(card.trained_at) >= N_new_entries_threshold` (default `N=25`).
- Phase A: trigger only proposes a retrain; an operator must call `surrogate train ... --operator-approval-token <token>` to actually retrain. Static surrogates by default; no silent retrains.
- Retrain produces a new `model_id`; the old card stays on disk as `active=false` until a comparison run shows the new model is no worse.

### 5.6 Pass / fail logic and directionality

Each observable has a directionality stored in its card (`lower_is_better` or `higher_is_better`). Pass requires the predicted value with a `k=2` uncertainty margin to strictly beat the baseline in the correct direction. Tight margins flip to `escalate` rather than `pass`, since the surrogate's job is to *cheaply rule out* candidates, not to certify them.

TODO — pin down the margin multiplier `k` and the tight-margin escalation band per observable; expose both on `SurrogateCard` so they are auditable and configurable.

### 5.7 Provenance contract

Every `SurrogateProbeResult` carries `parent_hashes=[experiment_spec_hash]` and embeds `training_set_hash` and `model_id` so downstream Ledger entries can reproduce the exact prediction.

TODO — wire the `factory.artifacts.verify-chain` walker (spec 002 §5.3) to follow the `SurrogateProbeResult → ExperimentSpec` edge AND to optionally resolve the `training_set_hash` against the `Ledger` store (spec 012) for full ancestry audit.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `NoTrainedSurrogate(SurrogateError)` | `predict()` called for an observable with no registered model | State machine routes candidate directly to G4 oracle; record `surrogate=skipped` on the `EvidenceLedgerEntry` |
| `SurrogateConfidenceTooLow(SurrogateError)` | Carried as `confidence_too_low=True` on the result (not raised in production) — reserved as a class for diagnostic tooling and tests | State machine sees `pass_vs_baseline="escalate"` and routes to oracle |
| `TrainingSetTooSmall(SurrogateError)` | `train()` finds `< min_rows` matching ledger rows | Halt retraining; operator must wait for more evidence or relax `simulator_family` filter |
| `ModelLoadFailed(SurrogateError)` | Registry init cannot deserialize `model.bin` / `ood_detector.bin` / `card.json` | Halt startup; mark observable as having no surrogate; do NOT silently fall back |

**`OODDetected` is NEVER raised in production.** It is reserved exclusively as a catastrophic-audit-hook class (e.g., a future `--strict-ood` audit mode in `python -m factory.surrogate ood-check`); production `predict()` carries the signal on `SurrogateProbeResult.ood_flag` so the gate state machine has a uniform always-returns-an-artifact contract. The class therefore appears in `api.py` but does not appear in the failure-modes table — its only legitimate use is intentional fail-fast during a manual audit, not error-handling in the normal cycle.

## 7. Testing

**Mock-mode unit tests** (`factory/surrogate/tests/`):
- `test_surrogate_typical_usage.py` — REQUIRED. Mock registry, fixture `ExperimentSpec`, verifies `SurrogateProbeResult` shape + provenance + `ood_flag` plumbing.
- `test_ood_routing.py` — feed a candidate far outside the fixture training distribution; verify `ood_flag=True` and `pass_vs_baseline="escalate"`. **OOD must never produce `pass`.**
- `test_confidence_floor.py` — feed a candidate with high model uncertainty; verify `confidence_too_low=True` and `pass_vs_baseline="escalate"`.
- `test_training_set_hash_stability.py` — same ledger rows in different orders produce the same `training_set_hash`.
- `test_no_trained_surrogate.py` — `predict()` for an unregistered observable raises `NoTrainedSurrogate`.
- `test_directionality.py` — lower-is-better vs higher-is-better both pass/fail correctly with margin.

**Live-mode tests** (`@pytest.mark.live`, gated):
- `test_live_training_smoke.py` — train a small RF on real `EvidenceLedgerEntry` rows pulled via `EvidenceLedgerReader`; assert held-out RMSE finite.
- `test_live_ood_calibration.py` — verify OOD-percentile threshold is honored on a held-out set.

**Acceptance check** (Phase A milestone):
- For ≥1 observable in the initial domain, training on the first N seeded `EvidenceLedgerEntry` rows produces a card with held-out RMSE below the spec-003 acceptance threshold AND OOD escalation rate on a synthetic out-of-distribution probe is ≥95%.

## 8. Performance & Budget

- Predict: < 50 ms per candidate (RF and GP at Phase-A training-set sizes); MLP comparable on CPU.
- Train: minutes (Phase A training-set sizes ~10²–10³); never blocks a cycle — runs offline under operator approval.
- OOD check: < 10 ms; fit once, persisted alongside model.
- Disk: each surrogate < 50 MB (Phase A); registry keeps ≤2 cards per observable (active + previous).
- Cost: predict-time LLM cost = $0. Train-time cost = $0 (local CPU). The whole point is to be cheap relative to G4 oracle calls.

## 9. Open Questions

- **Feature extraction is the load-bearing design choice.** A wrong `feature_schema_version` silently degrades every downstream surrogate. Open: should the schema be auto-derived from `ExperimentSpec`'s Pydantic model, or hand-written per observable for explicit control? Phase A: hand-written, version-pinned.
- **OOD detector choice per observable.** Phase A default is `knn_pca` (k=5 in PCA-reduced space, dim ≤ 20). Whether Isolation Forest is needed for multi-modal training clouds in some domains is empirical; Mahalanobis stays an opt-in backstop for low-d, elliptical training clouds only. Detector kind is a per-observable knob on the card.
- **Calibration of the uncertainty estimate.** RF uncertainty (forest variance) and MLP uncertainty (MC-dropout / deep ensemble) are differently calibrated; GP is best-calibrated but most expensive. Need a `calibration_error` field on the card and a hard floor for usability.
- **Multi-observable surrogates.** Phase A: one model per observable. Phase B may consider joint models. Open whether the savings justify the coupling.
- **Retraining authorization.** Phase A requires an explicit operator-approval token. Phase B may relax to "auto-retrain if held-out improves AND old card has been active ≥ X cycles". Pure Phase A: do not relax.
- **Phase B active-learning hook for the Strategy Archive (FIX_PLAN §26.4).** After a surrogate is retrained, `specs/016-strategy-archive.md` may consume the surrogate's posterior variance at a candidate point as a **fallback surprise signal** when the primary `GuideLLM`-driven Bayesian-surprise path is unavailable (rate-limited, offline, or cost-capped). Open questions: (a) what scaling rule maps `sigma` to a comparable surprise magnitude vs. the Dirichlet-KL signal (the archive's own concern, not this module's); (b) whether the surrogate's calibration error (already on `SurrogateCard.metrics`) should gate eligibility — a poorly-calibrated surrogate cannot back a surprise estimate; (c) whether OOD-flagged candidates should be excluded from the fallback (likely yes, since OOD `sigma` is uninformative). Not exercised in Phase A.

## 10. TODO Checklist

- [ ] Scaffold `factory/surrogate/` from the canonical module template.
- [ ] Implement `SurrogateRegistry`, `SurrogateCard`, `TrainingDataQuery`, `LedgerTrainingRow` (`api.py`, `types.py`).
- [ ] Implement feature extractor with a versioned schema; persist `feature_schema.json`.
- [ ] Implement at least one backend (random forest via scikit-learn) end-to-end; stub MLP + GP behind same interface.
- [ ] Implement OOD detector pipeline: PCA reduction (cap dim ≤ 20) + kNN (k=5) default; cache leave-one-out percentile cutoff as `threshold_distance`; persist alongside model.
- [ ] Implement `predict()` returning `SurrogateProbeResult`, including `pass_vs_baseline` directional logic.
- [ ] Implement `train()` with operator-approval token guard.
- [ ] Implement `ood_check()` returning `OODReport` for diagnostics.
- [ ] Consume the `EvidenceLedgerReader` narrow read view exported by spec 012 (see §3 import contract); no schema work owned by this spec.
- [ ] Consume the `SurrogateProbeResult` Pydantic model exported by spec 002 §4 (this spec is the sole producer; the artifact definition lives in spec 002 per FIX_PLAN §1).
- [ ] Author fixtures: ≥1 trained mock surrogate (`fixtures/<observable>/<model_id>/...`), an in-distribution candidate, an OOD candidate, a low-confidence candidate.
- [ ] Write `factory/surrogate/cli.py` with `train`, `predict`, `ood-check`, `list-models`, `show-card` subcommands.
- [ ] Write 6 mock-mode tests including the OOD escalation test (REQUIRED — defends `SPEC.md` §10.6).
- [ ] Write live-mode smoke tests gated by `@pytest.mark.live`.
- [ ] Write `factory/surrogate/README.md` (≤ 1 page, mock-mode example).
- [ ] Write `docs/runbooks/surrogate-training.md` covering retrain triggers, operator-approval workflow, rollback if new model worse.
- [ ] Verify `mypy --strict factory/surrogate/` passes.
- [ ] Verify `python -m factory.surrogate predict --mock-mode` works on a fresh checkout.
- [ ] Acceptance: OOD synthetic probe set shows ≥95% escalation rate; in-distribution probes show held-out RMSE below spec-003 threshold.
- [ ] (Phase B) Expose the active-learning hook for `specs/016-strategy-archive.md` (FIX_PLAN §26.4): on retrain completion, surface the new `SurrogateCard.metrics.calibration_error` and a public `predict_with_uncertainty(...)` path the archive can call to obtain posterior variance as a fallback surprise signal when `GuideLLM` is unavailable. The archive owns the `sigma → surprise` scaling; this module owns only the variance + calibration surface. Excluded from Phase A.
