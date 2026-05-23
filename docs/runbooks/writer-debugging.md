# Runbook: RAG Writer Debugging

> What this covers: diagnosing and recovering from common failures of the RAG writer — empty or low-citation Related Work, citation fabrication audit failures, LaTeX compile errors, context overflow, and missing council verdicts at G5. · When to use: a `RunReport` came out wrong (poor prose, missing citations, hedged negative-result discussion, fabricated citations), the writer raised an exception, or the orchestrator could not compile the emitted LaTeX. · Estimated time: 20 minutes for taxonomy-clear failures (missing Paper Store hits, missing verdicts); up to 2 hours for prompt-tuning or fabrication-audit recovery; rare overflow cases iterate longer.

## 1. Prerequisites

Before debugging you need: (a) the failed cycle's run directory at `runs/<cycle-id>/` and the corresponding `RunReport` directory at `runs/<cycle-id>/artifacts/runreport_<hash>/` (which may be partially written); (b) the input package that fed the writer: the `HypothesisSpec`, the `EvidenceLedgerEntry`, the C3 and C4 `CouncilVerdict`s, and the `figure_paths` list — confirm these exist via `python -m factory.writer show-bundle --cycle <id>`; (c) the Paper Store snapshot at `runs/_paper_store/` used during the writer call; (d) the structured event stream in `runs/<cycle-id>/cycle.jsonl` filtered by `module=writer` — every writer call emits `bundle_assembled`, `section_drafted` per section, `audit_passed` or `audit_failed`, and `report_emitted` events; (e) optionally, the mock writer for offline replay: `factory.writer.Writer.mock_writer()`.

## 2. Steps

1. **Identify the failure class.** Inspect the last event in `cycle.jsonl` under `module=writer` and the most recent exception in `runs/<cycle-id>/writer.log` (if present). Map to one of the five typed errors in Spec 011 §6: `PaperStoreEmpty`, `CitationFabrication`, `LatexCompileFailed`, `ContextOverflow`, `NoCouncilVerdictsToEmbed`. If the exception is none of these, the writer hit an unmodeled failure — file a bug.
2. **Replay the bundle assembly in mock mode.** Run `python -m factory.writer show-bundle --cycle <id>` to see exactly which Paper Store chunks made it into the drafting context. If the bundle is thin (≤ 2 papers), the issue is upstream — the Paper Store either did not have enough relevant material or the query-construction step (§5.1 of Spec 011) missed the topic. Go to step 3; otherwise step 4.
3. **Inspect Paper Store coverage.** Run `python -m factory.literature search --query "<hypothesis topic>"` against the Paper Store directly. If the corpus is genuinely sparse for this topic, re-run literature discovery (`docs/runbooks/literature-discovery.md`) with a widened seed query. If the corpus has the material but the writer's query missed it, the query-construction step is the bug — patch `factory/writer/queries.py` and re-run.
4. **Inspect the embedded verdicts.** Open the `RunReport` metadata at `runs/<cycle-id>/artifacts/runreport_<hash>/metadata.json` and confirm `embedded_council_verdict_hashes` references both C3 and C4 verdicts. If either is `None`, `NoCouncilVerdictsToEmbed` should have fired — this is a state-machine bug (G5 must run C3+C4 before invoking the writer); file against Spec 003.
5. **Inspect the generated LaTeX.** `report.tex` plus `references.bib`. Grep for `\cite{...}` and confirm every key resolves to either a Paper Store BibTeX entry or an `EvidenceLedger` internal-cycle reference (rendered as `[Internal Cycle #N, hash 7a3b2c1]`). A `CitationFabrication` failure means the audit caught a fabricated key; the writer attempts one re-draft of the offending section under a strict prompt, and only escalates on the second failure.
6. **For LaTeX compile failure:** the writer emits the source even when the optional smoke-compile fails — open `compile_diagnostics.txt` alongside `report.tex` to see the `pdflatex` / `tectonic` error. Most failures are upstream of the writer (missing figure paths, unsanitized special characters in extracted-evidence text). The orchestrator owns the real compile; the writer only emits a best-effort smoke-compile signal.
7. **Re-run the writer in isolation.** `python -m factory.writer write --hypothesis-fixture <cycle-id> --replay`. Replay reads the original input package and re-drafts; useful when the fix is in prompt templates (`factory/writer/sections/*.md`) or in the audit logic and you want to verify before re-orchestrating.

## 3. Verification

After remediation a clean writer run should produce: (a) `runs/<cycle-id>/artifacts/runreport_<hash>/report.tex` non-empty with ≥1 paragraph per configured section; (b) `references.bib` populated with ≥`min_papers_for_related_work` (default 3) entries, every BibTeX key matching a Paper Store record; (c) `bundle.json` audit-trail of the retrieval bundle used, listing chunk source paper IDs and rerank scores; (d) `metadata.json` with both C3 and C4 verdict hashes in `embedded_council_verdict_hashes` and preserved-dissent text rendered as LaTeX side-notes in `report.tex`; (e) for falsified or inconclusive hypotheses, a non-trivial Negative-Result Discussion section that names the failure without hedging; (f) `cycle.jsonl` events ending with `audit_passed` and `report_emitted`.

## 4. Troubleshooting

- **`PaperStoreEmpty` even though literature ran.** The literature traversal happened, but for a different cycle or a different seed query. Confirm via `python -m factory.literature show-graph --cycle <cycle-id>` that the traversal IDs match this cycle. If not, re-run literature discovery (see `docs/runbooks/literature-discovery.md`).
- **`CitationFabrication` on every re-draft attempt.** The drafting LLM is hallucinating a canonical paper (e.g., a famous textbook) that is not in the local Paper Store. Either onboard the missing paper into the Paper Store via `factory.literature promote`, or strip the offending claim from the section prompt. Do **not** disable the audit — that is the entire point of the writer's RAG-only contract.
- **`ContextOverflow` even after trim policy ran.** Either the drafting LLM's context window is genuinely too small for the topic's corpus, or the bundle assembly is over-packing. Inspect `bundle.json` — if a single paper consumes >30% of the budget, the chunker is too coarse; tune `factory/writer/types.py:RetrievalConfig.max_bundle_tokens` or use a longer-context model.
- **Negative-Result section reads as hedged / soft.** The drafting prompt template at `factory/writer/sections/negative_result_discussion.md` is under-tuned. Edit it to explicitly forbid hedging language and require naming the failed kill criterion; re-run with `--replay`. `[TBD-impl]` empirical prompt tuning is PRD-003 work.
- **`NoCouncilVerdictsToEmbed`.** Always a state-machine bug — G5 should have produced C3+C4 verdicts before the writer was invoked. Open Spec 003 and confirm the gate sequence; do not work around by feeding stub verdicts.

## 5. Related

- Spec 011 (`docs/specs/011-rag-writer.md`) — full writer API, retrieval pipeline, audit logic.
- Spec 007 (`docs/specs/007-literature-discovery.md`) — Paper Store; the only legal citation source.
- Spec 012 (`docs/specs/012-evidence-ledger.md`) — internal cross-references and prior `EvidenceLedgerEntry` lookups.
- Spec 003 (gate state machine) — G5 orchestration of C3 → C4 → Writer.
- SPEC.md §9 — RAG-grounded writing principles; SPEC.md §10 #4 — negative-result reports as anti-p-hacking defense.
- Runbook: `docs/runbooks/literature-discovery.md` — when Paper Store coverage needs to be expanded.
