# Runbook: Literature Discovery (OpenAlex + Gap Miner)

> What this covers: end-to-end operation of the Phase-0 literature pipeline — seed query → bounded OpenAlex traversal → ranking → Paper Store promotion → `GapCandidate` emission for the state machine. · When to use: bootstrapping research on a new topic, exploring an unfamiliar domain before designing experiments, or debugging an empty / low-signal Gap Miner run. · Estimated time: 10–30 minutes operator-attended, traversal itself ≤ 2 minutes wall clock under default policy.

## 1. Prerequisites

Before running literature discovery you need: (a) `factory.literature` installed and on the Python path; (b) for live mode, an `OPENALEX_MAILTO` env var set to a working email address so OpenAlex routes you through the polite pool, and optionally `OPENALEX_API_KEY` for higher rate limits; (c) a writable directory for the local `OpenAlexGraphStore` SQLite cache (default `runs/_graph_store/`) and the `PaperStore` (default `runs/_paper_store/`); (d) at least one seed research question — either an operator-supplied prompt or an entry from the open-problems registry. Mock-mode requires none of the above beyond a checked-out repo.

Fixtures live under `factory/literature/fixtures/`; the canonical mock fixture is `qi_stellarator` which contains a 25-node OpenAlex subgraph, three pre-OCR'd PDFs, and a stub extracted-evidence file. `[TBD-impl]` Concrete fixture catalog will be authored alongside the OpenAlex client.

## 2. Steps

1. **Define the seed query.** Hand it to the CLI as a quoted string. Example: `python -m factory.literature mine-gaps --seed-query "QI stellarator coil simplicity" --cycle-id cyc-0001`. Mock-mode runs append `--mock-mode`.
2. **Inspect the seed-search results before traversal.** Run `python -m factory.literature seed-search --query "..."` to see which OpenAlex Works the query maps to. Look for at least 3–5 plausibly-relevant seeds; if zero, the query is too narrow — broaden and rerun.
3. **Run a bounded traversal.** Either let `mine-gaps` orchestrate it end-to-end, or run it manually for inspection: `python -m factory.literature traverse --seed-ids W123,W456 --policy factory/literature/config/default_policy.yaml`. The default policy caps the run at `max_depth=2`, `max_nodes=500`, and `wall_clock_s=120`.
4. **Inspect the graph summary.** Run `python -m factory.literature show-graph --run-id <run-id>` to see bridge papers, seminal ancestors, recent extensions, and apparent gaps in the local subgraph. This is the human-readable view of `OpenAlexGraphStore`.
5. **Promote the top-k papers to the Paper Store.** Either let `mine-gaps` auto-promote per the policy's `promote_top_k_to_paper_store`, or run `python -m factory.literature promote --work-ids W789,W101` manually. Promotion triggers OA PDF fetch, OCR, and evidence extraction; per-paper budget is enforced if a `Budget` context is provided.
6. **Review the emitted `GapCandidate` list.** `mine-gaps` prints a summary; the JSON artifacts live at `runs/<cycle-id>/literature/gap_candidates/<hash>.json`. Each candidate carries its `gap_type`, `source_papers`, `rationale`, and `confidence`. `[TBD-impl]` Gap Miner heuristic ordering is policy-time configurable.
7. **Hand off to the state machine.** Either via the orchestrator (normal flow) or via `factory.state_machine submit-gaps <cycle-id>` for manual injection. Candidates enter at G0.

## 3. Verification

After a successful run you should see (a) a non-empty `OpenAlexGraphStore` SQLite at the configured path with rows in `works`, `edges`, and `traversal_runs`; (b) ≥1 promoted paper directory under `runs/_paper_store/<paper_id>/` containing `work.json`, `pdf.pdf` (if OA was available), `ocr.txt`, `evidence.json`, and `PROVENANCE.json`; (c) ≥1 emitted `GapCandidate` artifact at `runs/<cycle-id>/literature/gap_candidates/` with `gap_type ∈ {structural_hole, methodology_transfer, contradiction, negative_result}`; (d) a structured event stream in `runs/<cycle-id>/cycle.jsonl` filtered by `module=literature` showing `traversal_started`, `traversal_complete`, `paper_promoted`, and `gap_candidate_emitted` events. Negative result is acceptable — a non-fatal `GapMinerProducedNoCandidates` is logged and the state machine widens the seed query on retry.

## 4. Troubleshooting

- **`OpenAlexAPIError` on every call.** The polite-pool email is missing or invalid. Set `OPENALEX_MAILTO`. Persistent 5xx errors after backoff indicate an OpenAlex outage; switch to `--mock-mode` and resume later.
- **`TraversalBudgetExhausted` with no useful work.** Policy is too tight for the topic. Relax `max_depth` to 3 or raise `max_nodes`, but keep `wall_clock_s` finite. Alternatively, broaden the seed query so the priority-BFS converges faster.
- **`PaperPromoteFailed` on most papers.** Two common causes: (i) the topic is dominated by paywalled venues with no OA PDF — accept graph-node-only entries and rely on extracted-from-abstract evidence; (ii) the OCR pipeline is misconfigured — check `runs/<cycle-id>/literature/ocr_diagnostics.log`. `[TBD-impl]` exact diagnostic path.
- **`GapMinerProducedNoCandidates`.** Not a bug. The ranked set genuinely yielded no gap meeting the rationale threshold; either widen the seed query, run with a more permissive miner policy, or accept the null run and pick a different research direction.
- **`GraphStoreCorruption` at startup.** Cache hash mismatch — most often after a schema bump or interrupted write. Run with `--rebuild-graph-store` to scratch-rebuild. Per-paper data is not lost; the Paper Store is a separate, untouched store.

## 5. Related

- Spec 007 (`docs/specs/007-literature-discovery.md`) — full pipeline definition, OpenAlex client surface, traversal policy schema, Gap Miner contract.
- SPEC.md §6 — strategic role of literature discovery; hard boundary ("literature informs HOW, not WHERE").
- Spec 011 (`docs/specs/011-rag-writer.md`) — downstream consumer of the Paper Store at write time.
- Spec 002 (`docs/specs/002-artifacts.md`) — `GapCandidate` artifact schema.
- Spec 014 (`docs/specs/014-telemetry-and-audit.md`) — event taxonomy for literature events; useful for postmortem queries.
- Runbook: `docs/runbooks/telemetry-export.md` — exporting traversal + promotion events for offline analysis.
