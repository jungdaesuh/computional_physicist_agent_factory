# Runbook: Literature Discovery (OpenAlex + Gap Miner)

> What this covers: end-to-end operation of the Phase-0 literature pipeline — seed query → bounded OpenAlex traversal → ranking → Paper Store promotion → `GapCandidate` emission for the state machine. · When to use: bootstrapping research on a new topic, exploring an unfamiliar domain before designing experiments, or debugging an empty / low-signal Gap Miner run. · Estimated time: 10–30 minutes operator-attended, traversal itself ≤ 2 minutes wall clock under default policy.

## 1. Prerequisites

Before running literature discovery you need: (a) `factory.literature` installed and on the Python path; (b) for live mode, an `OPENALEX_API_KEY` env var set to a valid OpenAlex API key; (c) a writable directory for the local `OpenAlexGraphStore` SQLite cache (default `runs/_graph_store/`) and the `PaperStore` (default `runs/_paper_store/`); (d) at least one seed research question — either an operator-supplied prompt or an entry from the open-problems registry. Mock-mode requires none of the above beyond a checked-out repo. `OPENALEX_MAILTO` is obsolete for OpenAlex rate-limit behavior.

Mock mode uses the deterministic in-process OpenAlex fixture exposed by the CLI; the larger fixture catalog under `factory/literature/fixtures/` remains `[TBD-impl]`.

## 2. Steps

1. **Define the seed query.** Hand it to the CLI as a quoted string. Mock example: `python -m factory.literature --mock-mode mine-gaps --seed-query "QI stellarator coil simplicity"`.
2. **Inspect the seed-search results before traversal.** Run `python -m factory.literature seed-search --query "..."` to see which OpenAlex Works the query maps to. Look for at least 3–5 plausibly relevant seeds; if zero, broaden and rerun.
3. **Run a bounded traversal.** Either let `mine-gaps` orchestrate it end-to-end, or run it manually for inspection: `python -m factory.literature traverse --seed-ids W123,W456 --max-depth 2 --branch-factor 10 --max-nodes 500 --wall-clock-seconds 120`.
4. **Inspect the graph summary.** Run `python -m factory.literature show-graph --run-id <run-id>` to see cached counts for works, edges, traversal runs, and run-level accepted/visited counts.
5. **Promote the top-k papers to the Paper Store.** Either let `mine-gaps` auto-promote via `--promote-top-k`, or run `python -m factory.literature promote --work-ids W789,W101` manually. Promotion writes the OpenAlex snapshot, abstract-backed text, evidence placeholder, provenance, and BibTeX when metadata is sufficient; `--fetch-pdf` is explicit and requires a PDF fetcher.
6. **Review the emitted gap summary.** `mine-gaps` prints JSON with `gap_types`, `source_papers`, and `promoted`. The in-process Gap Miner returns typed `GapCandidate` objects for the state-machine surface; artifact persistence is owned by the surrounding cycle machinery.
7. **Hand off to the state machine.** Normal flow calls `factory.state_machine.run_literature_discovery(...)`, which returns source IDs, promoted IDs, gap types, and graph summary for G0/G1 scheduling.

## 3. Verification

After a successful CLI run you should see (a) a non-empty `OpenAlexGraphStore` SQLite at the configured path with rows in `works`, `edges`, and `traversal_runs`; (b) at least one promoted paper directory under `runs/_paper_store/<paper_id>/` containing `work.json`, `ocr.txt`, `evidence.json`, `PROVENANCE.json`, and `bibtex.bib` when metadata is sufficient; (c) JSON output listing the four canonical gap types: `structural_hole`, `methodology_transfer`, `contradiction`, and `negative_result`. Event persistence is handled by the outer state-machine/telemetry integration.

## 4. Troubleshooting

- **`OpenAlexAuthError` before the first call.** `OPENALEX_API_KEY` is missing, or stale `OPENALEX_EMAIL` is set. Export `OPENALEX_API_KEY` and remove `OPENALEX_EMAIL`. Persistent 5xx errors after backoff indicate an OpenAlex outage; switch to `--mock-mode` and resume later.
- **`TraversalBudgetExhausted` with no useful work.** Policy is too tight for the topic. Relax `max_depth` to 3 or raise `max_nodes`, but keep `wall_clock_s` finite. Alternatively, broaden the seed query so the priority-BFS converges faster.
- **Promotion errors on most papers.** Common causes: insufficient metadata for BibTeX (`BibtexUnavailable` on read), an unsafe/noncanonical Work ID (`PaperStoreLookupError`), or `--fetch-pdf` without a configured fetcher / reachable OA PDF (`OpenAlexAPIError`). Abstract-backed entries can still be promoted without PDF fetch.
- **`GapMinerProducedNoCandidates`.** Not a bug. The ranked set genuinely yielded no gap meeting the rationale threshold; either widen the seed query, run with a more permissive miner policy, or accept the null run and pick a different research direction.
- **`GraphStoreCorruption` at startup.** Cache hash mismatch — most often after a schema bump or interrupted write. Run with `--rebuild-graph-store` to scratch-rebuild. Per-paper data is not lost; the Paper Store is a separate, untouched store.

## 5. Related

- Spec 007 (`docs/specs/007-literature-discovery.md`) — full pipeline definition, OpenAlex client surface, traversal policy schema, Gap Miner contract.
- SPEC.md §6 — strategic role of literature discovery; hard boundary ("literature informs HOW, not WHERE").
- Spec 011 (`docs/specs/011-rag-writer.md`) — downstream consumer of the Paper Store at write time.
- Spec 002 (`docs/specs/002-artifacts.md`) — `GapCandidate` artifact schema.
- Spec 014 (`docs/specs/014-telemetry-and-audit.md`) — event taxonomy for literature events; useful for postmortem queries.
- Runbook: `docs/runbooks/telemetry-export.md` — exporting traversal + promotion events for offline analysis.
