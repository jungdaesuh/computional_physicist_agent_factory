# Runbook: Telemetry Export & Audit

> What this covers: exporting per-cycle event logs for offline analysis, postmortem investigation, sharing with stakeholders, and aggregating cost-by-module reports. Covers both the per-cycle JSONL stream and the optional Aggregator's rolled-up metrics. · When to use: postmortem after a failed cycle, weekly C5 program-direction briefing prep, ad-hoc audit (e.g., "show me every council deliberation where sycophancy was detected last month"), cost accounting, or sharing a sanitized event stream with collaborators. · Estimated time: 5 minutes for single-cycle export, 20–60 minutes for multi-cycle audit queries depending on disk size.

## 1. Prerequisites

Before exporting you need: (a) the factory installed with `factory.telemetry` on the Python path; (b) read access to `runs/` — per-cycle logs at `runs/<cycle-id>/cycle.jsonl` and the optional Aggregator output at `runs/_aggregator/metrics.jsonl` and `runs/_aggregator/state.json`; (c) the closed event taxonomy in `factory/telemetry/events.py` to know which event names exist — free-text event names are rejected at emit time, so the taxonomy is the complete query vocabulary; (d) for hypothesis-anchored queries, a working `EvidenceLedger` (Spec 012) so that `AuditQuery.by_hypothesis(hypothesis_id)` can resolve the hypothesis to its cycle directories; (e) `[TBD-impl]` an Aggregator process actually running if you want pre-computed rates — Phase A may run Aggregator on demand rather than as a sidecar.

## 2. Steps

1. **Identify the scope of the export.** Single cycle, time range, hypothesis-anchored, or event-name-anchored. Each maps to a different CLI invocation. Use `python -m factory.telemetry --help` to see all subcommands.
2. **Single-cycle export.** `python -m factory.telemetry export --cycle <cycle-id> --format jsonl --out /tmp/<cycle-id>.jsonl` streams the entire `runs/<cycle-id>/cycle.jsonl` to the output file. If you want stdout, omit `--out`. Add `--filter-event <event-name>` to restrict to one taxonomy entry.
3. **Time-range export across cycles.** `python -m factory.telemetry export --since 2026-05-01 --until 2026-05-23 --format jsonl --out /tmp/may.jsonl`. Walks `runs/*/cycle.jsonl` in cycle-id-sorted order and emits every record with `ts` in range.
4. **Hypothesis-anchored audit.** `python -m factory.telemetry query --by-hypothesis <hypothesis-id>`. This first resolves `hypothesis_id` → list of cycle IDs via the `EvidenceLedger` index (a hypothesis may span multiple cycles after relitigation), then concatenates filtered streams. Output is JSONL by default; add `--format table` for a human-readable summary.
5. **Event-name-anchored audit across all cycles.** `python -m factory.telemetry query --by-event-name factory.council.sycophancy_detected --since 2026-05-01`. Useful for failure-mode auditing.
6. **Aggregate metrics report.** `python -m factory.telemetry aggregate --window 30d --out /tmp/metrics.jsonl` runs the Aggregator (or reads its cached output if it has been running) and produces rolled-up rates: sycophancy rate, OOD escalation rate, dollar burn by module. `[TBD-impl]` exact CLI flag set for windowing.
7. **Cost-by-module report.** `python -m factory.telemetry aggregate --metric dollar_burn_by_module --window 30d`. Aggregator sums `payload.cost_usd` across every event that carries it, grouped by `module`. Output is a JSONL with one record per module per window.
8. **Tail a live cycle (during a run).** `python -m factory.telemetry tail --cycle <cycle-id>` streams events as they are appended. Useful during a cycle that is exhibiting symptoms; combine with `--filter-event` to narrow.
9. **Sanitize before sharing externally.** Telemetry events may include `payload.cost_usd`, internal cycle IDs, or other operator-private data. Run `python -m factory.telemetry export ... --sanitize` (`[TBD-impl]`) to strip dollar amounts and replace internal IDs with stable hashes before sharing.

## 3. Verification

A successful export produces: (a) a JSONL file (or stdout stream) where every line is a valid JSON object with the required fields `{ts, cycle_id, module, level, event, payload}`; (b) every `event` value matches an entry in the closed taxonomy (free-text events are impossible by construction); (c) `ts` values are RFC3339 UTC and monotonic per cycle (cycle.jsonl is append-only); (d) the export count matches the line count in the source `cycle.jsonl` minus any `JSONLineCorrupted` skips — these are noted in a side-channel `factory.telemetry.line_corrupted` event with `byte_offset`; (e) for hypothesis-anchored exports, every record's `cycle_id` is in the set returned by `EvidenceLedger.cycles_for(hypothesis_id)`; (f) for aggregate reports, totals reconcile with manual `jq` sums on the raw stream.

## 4. Troubleshooting

- **`EventTaxonomyViolation` in the export reader.** A record in the source log uses an unknown `event` name. This means an emitter wrote outside the taxonomy — should be impossible since emit-time validation rejects unknown names; if it happens, the log was edited by hand or the taxonomy was narrowed after the log was written. Inspect the offending line; either widen the taxonomy or quarantine the line.
- **`JSONLineCorrupted` on multiple lines in one cycle.** The cycle's writer crashed mid-flush. Per-line corruption is recovered (skipped + side-logged), but if many lines are corrupted the cycle's observability is compromised. The factory's source-of-truth artifacts (`EvidenceLedger`, `RunReport`) are still authoritative; treat the telemetry gap as a postmortem caveat, not as data loss for the cycle's outcome.
- **`AggregatorBacklog`, "Aggregator is N events behind tail".** Either the Aggregator was paused (check `runs/_aggregator/state.json` for last-processed offset) or downstream consumers (UI, C5 council) are blocking it. Restart with `python -m factory.telemetry aggregate --resume`. If backlog persists, run Aggregator on-demand for the specific window rather than as a continuous tail.
- **Empty query result on a hypothesis you know ran.** Two common causes: (i) `EvidenceLedger` index is stale (run `python -m factory.ledger reindex` and retry); (ii) the hypothesis ID was renamed during relitigation — check `hypothesis_id` history in `EvidenceLedger`.
- **`RetentionPolicyConflict` when trying to delete per-cycle logs.** Per-cycle logs are kept **indefinitely** by invariant — auditability over disk economy. If disk pressure is real, archive the logs to cold storage and replace with a symlink; do not delete in place. If the request was a misconfigured retention rule, reject and document in the runbook.

## 5. Related

- Spec 014 (`docs/specs/014-telemetry-and-audit.md`) — telemetry API, event taxonomy, Aggregator design.
- Spec 012 (`docs/specs/012-evidence-ledger.md`) — hypothesis → cycles index used by hypothesis-anchored queries.
- Spec 013 (Budget) — dollar-burn-by-module surfaces complement `Budget` ledgers but do not replace them.
- Spec 015 (Operator Interface) — the UI consumes Aggregator output; CLI is the operator-facing equivalent.
- SPEC.md §2 (Typed Artifacts) — telemetry is observability, not state; the source-of-truth artifacts live elsewhere.
- ARCHITECTURE.md §1.4, §3.2 — per-cycle JSONL invariant and the "modules talk to telemetry, never each other for status" rule.
