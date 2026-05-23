# Runbook: Surrogate Training & Calibration

> What this covers: training a new surrogate model from `EvidenceLedger` rows, calibrating the mandatory OOD detector, and activating the trained card for use at gate G3. Also covers retraining after the Ledger grows and rollback when a new model underperforms. · When to use: bootstrapping a surrogate for a new observable, retraining after ≥25 new Ledger rows have accumulated for an existing observable, or recovering from a `ModelLoadFailed` at startup. · Estimated time: 30 minutes to 2 hours including the operator-approval step and the live OOD calibration check. Training itself is minutes at Phase-A data sizes.

## 1. Prerequisites

Before training you need: (a) a populated `EvidenceLedger` (Spec 012) with at least `min_rows` (default 50) entries tagged with the target observable; query with `python -m factory.ledger count-observable --observable <name>` to confirm; (b) the surrogate package installed and the `surrogates/` store-root directory writable; (c) an operator-approval token — Phase A requires explicit human approval before any retrain runs; obtain via the operator interface (Spec 015) or by `python -m factory.surrogate request-approval --observable <name>`; (d) understanding of the observable's directionality (`lower_is_better` vs `higher_is_better`) — this lives in the catalog or observable registry, not invented at train time; (e) `[TBD-impl]` a frozen `feature_schema.json` for the observable — if the schema changes, **every** existing surrogate for that observable becomes invalid, and you should plan a coordinated rebuild rather than a casual retrain.

## 2. Steps

1. **Query the Ledger for training data.** Run `python -m factory.surrogate query-training-data --observable <name> --simulator-family <family> --min-rows 50`. Confirm the row count meets the minimum and inspect the distribution — if all rows come from one corner of `ExperimentSpec` space, your surrogate will be narrow; either widen the query or accept the limitation up front.
2. **Choose the surrogate kind.** Default is `random_forest` for general use, `gaussian_process` when calibrated uncertainty matters more than scalability, `mlp` for high-dimensional feature vectors. Phase A targets one trained model per observable. `[TBD-impl]` selection heuristic may move into a config file.
3. **Train.** `python -m factory.surrogate train --observable <name> --kind random_forest --query-min-rows 50 --operator-approval-token <token>`. The pipeline (i) verifies the token, (ii) extracts features via the versioned schema, (iii) fits the backend, (iv) fits the OOD detector on the same `X`, (v) runs held-out evaluation (RMSE / R² / calibration error), (vi) computes `training_set_hash = sha256(sorted provenance hashes)`, (vii) persists `model.bin`, `ood_detector.bin`, `card.json`, `training_set_hash.txt` under `surrogates/<observable>/<model_id>/`.
4. **Validate the held-out metrics.** Open the new `card.json` and confirm RMSE, R², and calibration error are within the spec-003 acceptance thresholds. `[TBD-impl]` thresholds per observable.
5. **Calibrate the OOD detector.** Run `python -m factory.surrogate ood-check --observable <name> --candidate-fixture <ood_probe_set>` against a synthetic OOD probe set. The escalation rate must be ≥95% on that probe set; otherwise tighten `ood_threshold_percentile` (e.g., from 0.95 to 0.90) or switch detector kind (Mahalanobis → kNN distance for multi-modal data) and re-train. Calibration is mandatory — never activate a card that hasn't passed.
6. **Inspect and activate.** `python -m factory.surrogate list-models --observable <name>` shows all cards. The new card defaults to `active=false`. Activate via `python -m factory.surrogate activate --observable <name> --model-id <id>`; the old card becomes `active=false` but stays on disk for audit.
7. **Comparison run before retiring the old model.** For ≥10 cycles after activation, watch the structured events stream for `factory.surrogate.escalation` and `factory.surrogate.predict` rates. If the new model escalates dramatically more than the old, you likely over-tightened OOD — rollback (step 4 of §4) and retune.

## 3. Verification

After training and activation you should observe: (a) `surrogates/<observable>/<new_model_id>/` exists and contains `model.bin`, `ood_detector.bin`, `card.json` (with `active=true`), `training_set_hash.txt`, `feature_schema.json`; (b) `python -m factory.surrogate predict --observable <name> --candidate-fixture sample_in_distribution --mock-mode` returns a `SurrogateProbeResult` with `ood_flag=False` and `pass_vs_baseline ∈ {pass, fail}`; (c) the same command with `--candidate-fixture sample_ood` returns `ood_flag=True` and `pass_vs_baseline="escalate"`; (d) the structured event `factory.surrogate.trained` appears in the operator telemetry stream with `{observable, model_id, n_training_examples, rmse, calibration_error}`; (e) `python -m factory.surrogate show-card --observable <name>` matches the `card.json` on disk.

## 4. Troubleshooting

- **`TrainingSetTooSmall`.** The Ledger does not yet have enough rows for this observable. Either wait for more cycles to populate the Ledger, relax `simulator_family` filter to include adjacent simulators (only if scientifically defensible — do not pollute training data), or postpone activating a surrogate for this observable; the state machine will simply route to oracle at G3.
- **High held-out RMSE on a high-dimensional MLP.** Phase-A data sizes are too small for MLP. Switch to random forest or GP. Do not tune the MLP harder — it is the wrong tool at this scale.
- **OOD escalation rate < 95% on synthetic probes.** Either the detector kind is wrong (try kNN distance if Mahalanobis fails on multi-modal data) or `ood_threshold_percentile` is too lax. Drop the percentile from 0.95 to 0.90 and re-evaluate; never relax it past 0.85 without operator review.
- **`ModelLoadFailed` at startup after a retrain.** Most often a `feature_schema_version` bump invalidated all on-disk cards. Inspect `card.json:feature_schema_version` vs `factory.surrogate.feature_schema.CURRENT_VERSION` — if mismatched, retrain. Do **not** silently fall back to the old card; the state machine should halt and surface the mismatch.
- **New model worse than old; rollback.** `python -m factory.surrogate activate --observable <name> --model-id <old_model_id>` reactivates the previous card. The new card stays on disk as `active=false` for audit but is not used; investigate why training degraded — usually new Ledger rows added noise or a feature-extraction bug.

## 5. Related

- Spec 010 (`docs/specs/010-surrogate-models.md`) — surrogate API, OOD detector specification, training pipeline.
- Spec 012 (`docs/specs/012-evidence-ledger.md`) — `EvidenceLedger` is the training-data substrate.
- Spec 002 (`docs/specs/002-artifacts.md`) — `SurrogateProbeResult` artifact schema; this module is the sole producer.
- SPEC.md §G3, §10.6 — the role of OOD detection in defending against training-set blind spots.
- Runbook: `docs/runbooks/telemetry-export.md` — exporting surrogate events for postmortem (`factory.surrogate.*`).
