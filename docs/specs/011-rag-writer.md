# Spec 011: RAG Writer

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- The **RAG Writer** turns a completed (or falsified) `HypothesisSpec` plus its `EvidenceLedgerEntry`, `CouncilVerdict`s (C3, C4), validation outputs, and Paper Store hits into a `RunReport` artifact: LaTeX source + figure paths + BibTeX + summary metadata. PDF compile is the orchestrator's job (deferred). Invoked by the state machine at G5 *after* C3 (Claim Interpretation) and C4 (Peer Review) emit verdicts.
- The 5 facts: (1) **RAG is local-only** — every citation comes from the Paper Store (spec 007); zero web calls at write time; (2) every hypothesis (including falsified ones) gets a `RunReport` — Negative-Result Discussion is a first-class section, not an afterthought (`SPEC.md` §10 #4) and is the anti-p-hacking defense; (3) BibTeX is generated *only* from cached Paper Store records — fabricated citations are caught by an audit pass that fails the build; (4) C3 + C4 verdicts are embedded into the report with preserved dissent so the UI sidebar (`UI_DESIGN.md` §8) can surface violet markers; (5) the LLM that drafts prose has no awareness of the corpus beyond the retrieved bundle — prompts are a strict contract, not a wish.
- Open first: `factory/writer/api.py` for the `Writer.write_report(...)` signature and the typical-usage test.

## ENTRY POINTS
- Main module: `factory/writer/api.py`
- Typical-usage test: `factory/writer/tests/test_writer_typical_usage.py`
- CLI: `python -m factory.writer --help` (subcommands: `write`, `audit-citations`, `show-bundle`, `replay`)
- Mock-mode example: `python -m factory.writer write --hypothesis-fixture sample_passed --mock-mode`
- Runbook: `docs/runbooks/writer-debugging.md` (TODO)

## LOCAL DEBUG
- Mock-mode: `Writer(paper_store=PaperStore.mock(), llm=MockLLMClient()).write_report(...)` — returns a fixture `RunReport` keyed on the fixture hypothesis. No API keys required.
- Fixture artifacts to feed it: `factory/writer/fixtures/sample_passed/`, `factory/writer/fixtures/sample_falsified/`, `factory/writer/fixtures/sample_inconclusive/` — each contains a `HypothesisSpec`, `EvidenceLedgerEntry`, `CouncilVerdict_C3`, `CouncilVerdict_C4`, and a stub Paper Store snapshot.
- Common error signatures → recovery:
  - `PaperStoreEmpty` → Phase 0 literature discovery (spec 007) never ran for this hypothesis topic; route back to Gap Miner or accept a degraded "no Related Work" report (config flag).
  - `CitationFabrication` → audit pass found a `\cite{key}` not present in the cached BibTeX; halt; drop the offending paragraph and re-draft once, then escalate.
  - `LatexCompileFailed` → only raised by the optional smoke-compile (mock-mode skips); orchestrator owns the real compile, so surface diagnostics but emit the source anyway.
  - `ContextOverflow` → assembled retrieval bundle exceeds the drafting LLM's context window; bundle-trimmer must drop lowest-rank chunks until under limit; failure to fit any bundle escalates.
  - `NoCouncilVerdictsToEmbed` → caller did not pass C3/C4 verdicts; report cannot be finalized without them; state machine must have run G5 first.
- Logs to inspect: `runs/<cycle-id>/cycle.jsonl` filtered by `module=writer`. Every write emits `bundle_assembled`, `section_drafted` (one per section), `audit_passed`, and `report_emitted` events.

## DEPENDENCIES
- **Hard:**
  - Spec 002 (Typed Artifacts) — consumes `HypothesisSpec`, `EvidenceLedgerEntry`, `CouncilVerdict`; emits `RunReport`.
  - Spec 007 (Literature Discovery / Paper Store) — the RAG corpus. Exports `PaperStore` from `factory.literature` (spec 007 §3). Reads `PaperStore.query(...)`, `PaperStore.get(work_id)`, `PaperStore.get_bibtex(work_id)`, and `PaperStore.has_bibtex(work_id)`. No other source of citations is permitted.
  - Spec 012 (Evidence Ledger) — instantiates `Ledger` (the canonical storage backend; the per-row artifact is `EvidenceLedgerEntry`). Reads prior entries via `ledger.get_by_id(hypothesis_id)`, `ledger.get_by_hash(entry_hash)`, and `ledger.query(LedgerQuery(...))` when the report needs to cite "what we previously concluded internally" (the local-grounded equivalent of self-citation).
- **Soft:**
  - Spec 014 (Telemetry) — structured events emitted if available; degrades to stdlib logging.
  - Spec 013 (Budget) — drafting cost accrues to the hypothesis budget if a budget context is passed; otherwise the writer runs uncapped (with a config-defined safety cap).
- **Mocks available:** `PaperStore.mock()` ships a 20-paper fixture corpus across two domains. `MockLLMClient` returns deterministic per-section drafts. `Writer.mock_writer()` wires both together for tests.

---

## 1. Summary

The Writer is a **retrieval-augmented, local-only manuscript generator**. Given a closed hypothesis and its evidence package, it (a) retrieves relevant papers from the Paper Store, (b) assembles a context bundle, (c) drafts the manuscript section-by-section with the drafting LLM, (d) audits every emitted citation against the Paper Store, (e) generates BibTeX from cached records, (f) embeds C3 and C4 verdicts (with preserved dissent), and (g) emits a `RunReport` artifact. Crucially, **falsified hypotheses produce a report**: the Negative-Result Discussion section is the anti-p-hacking defense (`SPEC.md` §10 #4, §1 #7).

The Writer is *not* a fact-checker, novelty arbitrator, or peer reviewer. Those are the validation portfolio (G4) and Council (C3/C4) jobs respectively. The Writer is a faithful narrator over an already-adjudicated evidence package.

## 2. Scope

**In scope:**
- Local RAG pipeline: query → rerank → bundle assembly → context-window fit.
- Section-by-section drafting with per-section prompt templates (Abstract, Introduction, Related Work, Method, Experiment, Results, Limitations, Negative-Result Discussion, Conclusion, Provenance Appendix).
- Citation-fabrication audit: every `\cite{key}` in the LaTeX must resolve to a Paper Store record OR to an internal `EvidenceLedgerEntry` (the latter rendered as a non-academic provenance citation).
- BibTeX synthesis directly from Paper Store records.
- Embedding `CouncilVerdict` (C3, C4) JSON into the `RunReport` artifact and rendering UI-friendly margin markers per `UI_DESIGN.md` §8.
- Negative-Result Discussion section generation when `EvidenceLedgerEntry.result ∈ {falsified, inconclusive}`.
- Mock mode: full pipeline with fixture Paper Store and deterministic LLM output.
- CLI: `write`, `audit-citations`, `show-bundle`, `replay`.

**Out of scope:**
- PDF compilation (the orchestrator owns `pdflatex` / `tectonic`; the Writer emits source only).
- Web search, live arXiv lookup, or any non-local citation source (forbidden by `SPEC.md` §9).
- Figure generation (figures are produced upstream by validation / experiment modules; the Writer references existing paths only).
- External publication routing (G6 / arXiv handoff lives in the operator interface, spec 015).
- Style / journal-template customization (Phase B).
- Schema migration of older `RunReport`s (Phase B).

## 3. Public Interface

> Skeleton-level: signatures are the contract. Bodies are TODO. Prompt-template content for the drafting LLM is also TODO and tuned during PRD-002/003.

> **LLM access (FIX_PLAN §25.2).** Section drafting uses the shared OpenRouter client
> (`openai` SDK, base URL `https://openrouter.ai/api/v1`) with
> `model="google/gemini-3.5-flash"`. There is no Gemini-direct SDK import; the only
> LLM env var is `OPENROUTER_API_KEY`. Cost + tokens are populated from the
> OpenRouter response's `usage` block and passed to `BudgetTracker.record(...)`.
> (§25 supersedes §24's Gemini-only constraint; council multi-vendor is restored in
> spec 001, but section drafting remains single-model — `google/gemini-3.5-flash`
> is the cheap agentic default.)

```python
# factory/writer/api.py

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from factory.artifacts import (
    ArtifactHash, CouncilVerdict, EvidenceLedgerEntry, HypothesisSpec, RunReport,
)
from factory.literature import PaperStore        # spec 007 (exported per FIX_PLAN §18)
from factory.ledger import Ledger, LedgerQuery   # spec 012 (canonical class is Ledger)

class WriterError(FactoryError): ...
class PaperStoreEmpty(WriterError): ...
class CitationFabrication(WriterError): ...
class LatexCompileFailed(WriterError): ...
class ContextOverflow(WriterError): ...
class NoCouncilVerdictsToEmbed(WriterError): ...


@dataclass(frozen=True)
class RetrievalConfig:
    top_k: int = 12                          # retrieved chunks per query
    rerank_top_k: int = 8                    # post-rerank survivors
    max_bundle_tokens: int = 60_000          # drafting LLM context budget
    min_papers_for_related_work: int = 3     # below threshold → degraded report

@dataclass(frozen=True)
class WriterConfig:
    retrieval: RetrievalConfig = RetrievalConfig()
    drafting_model_id: str = "google/gemini-3.5-flash"   # FIX_PLAN §25.5 agentic default (OpenRouter)
    safety_cost_cap_usd: float = 2.00
    sections: Sequence[str] = (
        "abstract", "introduction", "related_work", "method", "experiment",
        "results", "limitations", "negative_result_discussion", "conclusion",
        "provenance_appendix",
    )
    omit_negative_result_section_if_passed: bool = True

class Writer:
    """Local-only RAG manuscript generator."""

    def __init__(
        self,
        paper_store: PaperStore,
        ledger: Ledger,
        llm: "LLMClient",                    # any decision_client; mocked in tests
        config: WriterConfig = WriterConfig(),
        mock_mode: bool = False,
    ) -> None: ...

    def write_report(
        self,
        hypothesis: HypothesisSpec,
        evidence: EvidenceLedgerEntry,
        c3_verdict: CouncilVerdict,
        c4_verdict: CouncilVerdict,
        figure_paths: Sequence[Path],
        cycle_id: str,
    ) -> RunReport:
        """Produce a RunReport artifact.

        EVERY hypothesis that reaches G5 — including falsified, inconclusive,
        and intractable terminations — produces a RunReport. This is the
        anti-p-hacking invariant (`SPEC.md` §10 #4). When
        `evidence.result != passed`, the Negative-Result Discussion section
        (§5.5) is mandatory and non-trivial.

        Steps:
          1. Build query set from hypothesis.if_then + measurable_metric + domain tags.
          2. Retrieve from PaperStore → rerank → fit-to-context (raises ContextOverflow).
          3. Draft sections in order; each section prompt sees only the relevant bundle slice.
          4. Audit every \\cite{key} against PaperStore + Ledger (self-audit pass — see §5.6).
          5. Synthesize BibTeX from PaperStore.get_bibtex(work_id) only.
          6. Embed c3_verdict and c4_verdict (preserved dissent untouched).
          7. Emit RunReport artifact and persist alongside cycle artifacts.

        Raises:
          PaperStoreEmpty           — corpus has zero matches and degraded mode is off.
          CitationFabrication       — audit caught a citation key not in the Paper Store
                                      (Writer self-audit; every citation must trace back
                                      to a Paper Store entry).
          ContextOverflow           — bundle cannot fit even after trimming.
          NoCouncilVerdictsToEmbed  — c3_verdict / c4_verdict missing.
        """
        raise NotImplementedError  # TODO

    def audit_citations(self, latex_source: str, bibtex: str) -> "CitationAuditReport":
        """Standalone audit: every \\cite{key} present in bibtex AND every bibtex key
        traces back to one of:
          - PaperStore.has_bibtex(work_id) — academic citation; OR
          - ledger.get_by_id(hypothesis_id) / ledger.get_by_hash(entry_hash) — rendered as
            an internal-provenance reference, never as a journal-style citation.
        """
        raise NotImplementedError  # TODO

    @classmethod
    def mock_writer(cls) -> "Writer":
        """Deterministic mock for downstream tests."""
        raise NotImplementedError  # TODO


@dataclass(frozen=True)
class CitationAuditReport:
    cited_keys: list[str]
    bibtex_keys: list[str]
    fabricated_keys: list[str]               # in latex, missing from bibtex
    orphan_keys: list[str]                   # in bibtex, never cited
    passed: bool
```

### 3.1 Output schema — Negative-Result Discussion (anti-p-hacking invariant)

The Writer's contract guarantees that **every** invocation emits a `RunReport`,
including for hypotheses with `evidence.result ∈ {falsified, inconclusive,
intractable}`. This is the explicit anti-p-hacking defense from `SPEC.md` §10
#4: the factory does not get to publish only its wins.

The emitted `RunReport.latex_source` is contractually required to contain the
**Negative-Result Discussion** section as a named, non-empty section whenever
any of the following hold:

- `evidence.result ∈ {falsified, inconclusive}`, OR
- `c4_verdict.chairman_decision == "reject"`, OR
- `evidence.result == intractable` (G2.5 dry-run kill or budget exhaustion).

The section's required content is fixed (see §5.5): pre-registered hypothesis
statement, kill criterion that was hit, residual effect size + CI, an explicit
"we did not find what we expected" sentence drafted without hedging, and at
least one re-litigation trigger drawn from `evidence.relitigate_if`. The
section MUST appear in `RunReport.section_index` with `kind="negative_result"`
and a stable anchor `sec:negative_result`. Reports for passed hypotheses MAY
omit the section per `WriterConfig.omit_negative_result_section_if_passed`.

Downstream consumers (the operator UI per `UI_DESIGN.md` §8, the C5 audit
pass per spec 001) join on this anchor + kind to surface negative-result
findings without parsing prose.

## 4. Data Structures / Schemas

The Writer emits one persistent artifact — `RunReport` (defined in spec 002). Module-local types live in `factory/writer/types.py` and include `RetrievalConfig`, `WriterConfig`, `CitationAuditReport`, and a transient `ContextBundle` used during drafting (not persisted).

`RunReport.embedded_council_verdict_hashes` references the C3 + C4 `CouncilVerdict` artifacts by hash; the verdicts themselves remain immutable artifacts on disk. The UI sidebar (`UI_DESIGN.md` §8) joins on these hashes to render dissent markers.

JSON Schema for `RunReport` is auto-emitted by spec 002's CI step; no Writer-specific schema needed.

> TODO: define on-disk layout for `runs/<cycle-id>/artifacts/runreport_<hash>/`:
> - `report.tex` (LaTeX source)
> - `references.bib` (BibTeX)
> - `figures/` (symlinks or copies of upstream figure paths)
> - `bundle.json` (audit-trail of the retrieval bundle used to draft)
> - `metadata.json` (RunReport artifact JSON)

## 5. Algorithms / Logic

> Skeleton-level: section stubs only. Bodies are TODO and will land during the PRD-003 first-end-to-end implementation.

### 5.1 Query construction
> TODO: build queries from `hypothesis.if_then`, `measurable_metric`, `pre_registered_metric`, simulator domain tag, and any `relitigate_if` triggers that reference prior literature. One query per (topic, sub-claim). Domain-specific stop-word lists configurable.

### 5.2 Retrieval and rerank
> TODO: dense-vector ANN search inside `PaperStore` returns `top_k` chunks; a lightweight LLM rerank pass narrows to `rerank_top_k`. Chunk dedup by paper-id. Fallback to BM25 if the Paper Store has no embeddings (spec 007 controls availability).

### 5.3 Bundle assembly and context-fit
> TODO: pack chunks into the drafting LLM's context budget (`max_bundle_tokens`), preserving paper-level grouping. Greedy descending-score packing with a tail-trim policy. Raise `ContextOverflow` if even the top single paper exceeds budget.

### 5.4 Section drafting
> TODO: per-section prompt templates under `factory/writer/sections/<section>.md`. Each template receives the relevant bundle slice + structured evidence + verdicts. Sections drafted in dependency order: method/experiment first (factual), then results, then introduction/related_work (which depend on positioning), then abstract (which depends on everything). Conclusion last.

### 5.5 Negative-Result Discussion
> TODO: triggered when `evidence.result ∈ {falsified, inconclusive}` OR when `c4_verdict.chairman_decision == "reject"`. Section content: what was tested, what the kill criteria were, which one was hit, residual-effect-size CI, and at least one suggested re-litigation trigger drawn from `evidence.relitigate_if`. No hedging language permitted by the prompt; failure is named.

### 5.6 Citation-fabrication audit (Writer self-audit)
> TODO: regex-extract every `\cite{key}` and `\citep{key}` from the assembled LaTeX. Cross-check against:
> - `PaperStore.has_bibtex(key)` for academic citations.
> - `ledger.get_by_hash(key)` for internal cross-references that name an `EvidenceLedgerEntry` provenance hash directly.
> - `ledger.get_by_id(hypothesis_id) -> list[EvidenceLedgerEntry]` for internal cross-references that name a hypothesis (any entry in the returned list resolves the key).
> - For broader filtering — e.g., "internal results in the same simulator family" — call `ledger.query(LedgerQuery(simulator_id=..., result=EvidenceResult.passed))` and resolve the cited key against any entry hash in the returned list.
> Internal references render as `[Internal Cycle #N, hash 7a3b2c1]` in plain text — never in BibTeX. Any unresolved key raises `CitationFabrication`. The Writer re-drafts the offending section ONCE with a strict prompt; second failure escalates to the state machine. This audit is the Writer's own contract: every citation it emits must trace to a Paper Store entry or to a Ledger entry; nothing else is permitted.

### 5.7 BibTeX synthesis
> TODO: for each citation key, call `PaperStore.get_bibtex(work_id)` which returns a frozen BibTeX entry from the cached OpenAlex record (spec 007 owns the cache; the Writer never mutates BibTeX).

### 5.8 Verdict embedding
> TODO: serialize `c3_verdict` and `c4_verdict` JSON inline in the `RunReport` artifact (via `embedded_council_verdict_hashes`); render LaTeX side-notes for any `preserved_dissents` entry, anchored to the paragraph it most likely contests (heuristic: cosine similarity between dissent text and paragraph). The UI consumes the verdict JSON, not the LaTeX side-notes, but both are present for offline reading.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `PaperStoreEmpty(WriterError)` | No Paper Store results for any query AND degraded mode disabled | State machine routes back to Gap Miner (spec 007); alternatively re-enable `--allow-empty-related-work` config flag (Phase B). |
| `CitationFabrication(WriterError)` | Writer self-audit finds a `\cite{key}` that does not trace to a Paper Store entry (`PaperStore.has_bibtex`) or to a Ledger entry (`ledger.get_by_hash` / `ledger.get_by_id`) | Re-draft the offending section ONCE with strict prompt; second failure halts the report, surfaces to operator, hypothesis flagged for human review. Every emitted citation must trace to one of those two sources — no exceptions. |
| `LatexCompileFailed(WriterError)` | Optional smoke-compile pass failed (orchestrator owns real compile) | Emit source anyway; attach `compile_diagnostics.txt`; orchestrator decides whether to retry compile or surface to user. |
| `ContextOverflow(WriterError)` | Even minimal bundle exceeds drafting LLM's context window | Trim policy escalates: drop lowest-rerank chunks → drop oldest papers → drop figures from inline-discussion. If still over, escalate; report cannot be drafted at this fidelity. |
| `NoCouncilVerdictsToEmbed(WriterError)` | `c3_verdict` or `c4_verdict` is `None` | State machine bug — G5 must run C3+C4 before invoking Writer; abort with explicit error pointing at spec 003. |

## 7. Testing

> Skeleton-level: ≥1 test per concern is required at typical-usage time; full coverage is PRD-003 work.

**Mock-mode unit tests** (`factory/writer/tests/`):
- `test_writer_typical_usage.py` — REQUIRED. Mock Paper Store + mock LLM + sample passed-hypothesis fixture; assert `RunReport` shape, citation audit passes, BibTeX is non-empty, C3/C4 hashes embedded.
- `test_negative_result_report.py` — feeds a `result=falsified` fixture; asserts Negative-Result Discussion section is present and non-trivial; asserts report STILL emits.
- `test_citation_fabrication_audit.py` — injects a fake `\cite{fabricated_key}` into a mock LLM response; verifies the audit raises `CitationFabrication` and that the re-draft path is exercised.
- `test_context_overflow.py` — Paper Store fixture too large for mock context window; verifies trim policy and (in pathological case) `ContextOverflow`.
- `test_paper_store_empty.py` — mock Paper Store returns zero hits; verifies `PaperStoreEmpty` in strict mode AND degraded-mode fallback in permissive mode.
- `test_verdict_embedding.py` — feeds a C4 verdict with `preserved_dissents`; verifies dissent text survives into the LaTeX side-notes AND into the artifact JSON.

**Live-mode tests** (`@pytest.mark.live`, gated):
- `test_live_smoke_report.py` — single end-to-end run against a real (small) Paper Store and a real LLM client; asserts `total_cost_usd < $2.00` and a non-trivial Related Work section emerges.

**Manual verification** (one-time, runbook): inspect one falsified-hypothesis `RunReport` by hand to confirm the Negative-Result Discussion is not hedging or cherry-picking.

## 8. Performance & Budget

- Per `RunReport`: target ≤180 s wall clock, ≤ $2.00 cost at default config (10 sections × drafting LLM calls + retrieval + audit). Configurable via `WriterConfig.safety_cost_cap_usd`.
- Retrieval is sub-second against a 20–200 paper local Paper Store (spec 007 owns indexing).
- The Writer NEVER calls the network at write time. Live mode talks to the drafting LLM only; the corpus is on disk.
- Drafting LLM call count is bounded by `len(WriterConfig.sections)` + at most one rewrite per section on citation-audit failure.

## 9. Open Questions

- **Per-section prompt-template tuning.** Skeleton spec keeps prompts as TODO. Empirical tuning happens in PRD-002/003. Risk: an under-tuned prompt for Related Work produces generic prose that *looks* RAG-grounded but cites the same 2 papers everywhere. Calibration probes (analogous to council §5.5) may be needed.
- **Internal cross-references vs. academic citations.** The factory's `Ledger` (spec 012) records — typed `EvidenceLedgerEntry` artifacts — are *not* peer-reviewed literature; citing them like journal articles would be intellectually dishonest. Skeleton policy: render internal references as `[Internal Cycle #N, hash <7-char>]` in plain text, NOT in BibTeX. Policy to finalize during PRD-003.
- **Negative-result tone calibration.** A drafting LLM tuned for confident scientific writing may soften failure language. The Negative-Result Discussion prompt must explicitly forbid hedging — this needs empirical testing.
- **Citation-density bounds.** A pathological RAG bundle could produce a Related Work section with 80 citations on a single claim. Should there be a per-claim citation cap? Deferred to Phase B.
- **Re-litigation citations.** When a `RunReport` supersedes a prior internal finding (per `relitigate_if`), should the new report cite the old one explicitly? Probably yes; spec defers the rendering decision.

## 10. TODO Checklist

- [ ] Scaffold `factory/writer/` from the canonical module template (api / cli / mock / errors / types / fixtures / tests).
- [ ] Define `WriterConfig`, `RetrievalConfig`, `CitationAuditReport` in `factory/writer/types.py`.
- [ ] Implement `Writer.__init__` taking `paper_store: PaperStore` (spec 007) + `ledger: Ledger` (spec 012 canonical class) + LLM injection and config validation.
- [ ] Implement query construction (§5.1) from `HypothesisSpec` fields.
- [ ] Wire `PaperStore.query(...)` + rerank + bundle assembly (§5.2–§5.3).
- [ ] Author per-section prompt templates (`factory/writer/sections/*.md`) — all 10 sections, with the Negative-Result Discussion prompt explicitly forbidding hedging language.
- [ ] Implement section drafting pipeline (§5.4) including the mandatory Negative-Result branch (§5.5) for `evidence.result ∈ {falsified, inconclusive, intractable}` and `c4.chairman_decision == "reject"`.
- [ ] Implement Writer-self-audit citation-fabrication pass + re-draft loop (§5.6) using `PaperStore.has_bibtex` and `ledger.get_by_hash` / `ledger.get_by_id` / `ledger.query(LedgerQuery(...))`.
- [ ] Implement BibTeX synthesis pulling from `PaperStore.get_bibtex` only (§5.7); internal references render as plain text, never as BibTeX entries.
- [ ] Implement C3 + C4 verdict embedding with preserved-dissent margin anchoring (§5.8).
- [ ] Implement `MockLLMClient` returning deterministic section drafts.
- [ ] Author 3 fixture hypothesis-evidence packages (passed / falsified / inconclusive) + a 20-paper mock Paper Store snapshot.
- [ ] Build CLI: `write`, `audit-citations`, `show-bundle`, `replay`.
- [ ] Write the 6 mock-mode tests listed in §7.
- [ ] Write `test_live_smoke_report.py` (live; manual gate).
- [ ] Write `factory/writer/README.md` (≤1 page; mock-mode example).
- [ ] Write `docs/runbooks/writer-debugging.md`.
- [ ] Verify `mypy --strict factory/writer/` passes.
- [ ] Verify `python -m factory.writer write --hypothesis-fixture sample_passed --mock-mode` works on a fresh checkout.
- [ ] PRD-003 acceptance: one autonomously generated `RunReport` (positive or defensibly-null) passes citation audit and embeds preserved C4 dissent. A falsified-hypothesis `RunReport` must carry a non-empty Negative-Result Discussion section.
