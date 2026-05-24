# Spec 007: Literature Discovery (OpenAlex + Gap Miner)

> Status: ◐ in progress · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- This module is **Phase 0** of the factory: it takes a seed research question, walks the OpenAlex citation graph in a bounded traversal, ranks the resulting papers, promotes a small subset into the local **Paper Store** (OpenAlex snapshot + text/evidence + optional PDF + BibTeX), and emits `GapCandidate` artifacts for the Gap Miner. It is the only place external bibliographic data enters the factory.
- The 5 facts: (1) literature informs HOW to search, never WHERE — OpenAlex output cannot directly seed simulator parameters; (2) the **OpenAlexGraphStore** (nodes/edges/scores) and the **Paper Store** (full text + extracted evidence + BibTeX) are *distinct* persisted stores; (3) traversal is bounded by an explicit policy (`max_depth`, `max_nodes`, `branch_factor`, `max_pages`, wall-clock); (4) Gap Miner emits four `gap_type`s only — `structural_hole | methodology_transfer | contradiction | negative_result` (underscored form everywhere); (5) citation-graph holes are not automatically scientific gaps — every `GapCandidate` must still pass G1 conversion in the state machine.
- Open first: `factory/literature/api.py`, `factory/literature/tests/test_literature_typical_usage.py`, and `factory/literature/cli.py`.

## ENTRY POINTS
- Main module: `factory/literature/api.py`
- Typical-usage test: `factory/literature/tests/test_literature_typical_usage.py`
- CLI: `python -m factory.literature --help` (subcommands: `seed-search`, `traverse`, `rank`, `promote`, `mine-gaps`, `show-graph`)
- Mock-mode example: `python -m factory.literature --mock-mode mine-gaps --seed-query "QI stellarator coil simplicity"`
- Runbook: `docs/runbooks/literature-discovery.md`

## LOCAL DEBUG
- Instantiate without OpenAlex network access: use `InMemoryOpenAlexClient` with typed `OpenAlexWork` fixtures, or `PaperStore.mock()` for a deterministic promoted-paper store.
- Live mode requires **`OPENALEX_API_KEY`**. The historical polite-pool `mailto` behavior is obsolete for rate-limit behavior; `OPENALEX_EMAIL` must not be used.
- Common error signatures → recovery:
  - `OpenAlexAPIError` → transient API issue or 4xx; retry with exponential backoff; surface to operator if persistent.
  - `GraphStoreCorruption` → cache file mismatched its hash or schema; rebuild from scratch via `--rebuild-graph-store`.
  - `TraversalBudgetExhausted` → bounded traversal hit a limit before exploring requested seeds; tighten the policy or expand the budget.
  - `PaperPromoteFailed` → future OCR/extraction promotion failure; current abstract-backed promotion failures surface as `OpenAlexAPIError` or `PaperStoreLookupError`.
  - `GapMinerProducedNoCandidates` → ranked set yielded no gap pattern that meets the rationale threshold; treat as a non-fatal null run.
  - `EvidenceExtractionFailed` → promotion partially succeeded but evidence schema didn't validate; paper is quarantined.
  - `BibtexUnavailable` → BibTeX could not be synthesized for a promoted paper (e.g., missing year + authors); paper remains promoted but `has_bibtex(work_id)` returns `False`.
- Logs to inspect once state-machine telemetry is active: `runs/<cycle-id>/cycle.jsonl` filtered by `module=literature`. Local stores are the current source of truth: OpenAlex graph SQLite plus Paper Store entries at **`runs/_paper_store/<work_id>/`** (per FIX_PLAN §10).

## DEPENDENCIES
- **Hard:** Spec 002 (artifacts) — emits `GapCandidate`. That is the only inbound contract.
- **Soft:** Spec 014 (telemetry) — emits traversal + promotion events if available. Spec 013 (budget) — future OCR/extraction LLM costs tracked if a budget context is provided. Spec 011 (RAG writer) — *downstream* consumer of the Paper Store; not a runtime dep. The writer uses `PaperStore.get_bibtex(work_id)` to render citations.
- **Mocks available:** `InMemoryOpenAlexClient` with canned `get_work` / `search_works` / `get_backward_references` / `get_forward_citations` responses, the CLI `--mock-mode` fixture graph, and `PaperStore.mock()`.

---

## 1. Summary

The Literature Discovery module is the factory's only bridge to the external academic graph. It is bounded, read-only, and emits typed `GapCandidate` artifacts — never simulator parameters. The pipeline composes a typed OpenAlex client, a local OpenAlex graph cache, a bounded traversal engine, a ranker, a **`PaperStore`** with text/evidence, optional PDF capture, and BibTeX, and a Gap Miner that turns ranked literature into candidate research directions.

## 2. Scope

**In scope:**
- Typed `OpenAlexClient` wrapping the public OpenAlex API for the required methods (forward citations via the `/works?filter=cites:<work_id>` filter endpoint exclusively).
- `OpenAlexGraphStore`: local cache of works, edges, traversal runs, ranking scores — kept separate from `EvidenceLedger`.
- `TraversalEngine`: bounded BFS / priority-BFS over backward + forward citation edges.
- `PaperRanker`: multi-factor scoring with MMR diversity; returns ranked list with per-paper rationale.
- `PaperStore`: persisted OpenAlex snapshots, text/evidence, optional PDFs, provenance, and synthesized BibTeX for promoted papers only, exposed as a typed public class (§3).
- `GapMiner`: emits `GapCandidate` artifacts in the four supported `gap_type`s.
- Agent-facing tool surface (5 tools — see §3).
- Traversal policy CLI flags. A YAML loader remains a tracked TODO.
- Mock mode covering every component.

**Out of scope:**
- Hypothesis refinement from `GapCandidate` (spec 003).
- The Worthiness council C1 (spec 001).
- Writing the manuscript — RAG writer (spec 011) reads `PaperStore` and consumes its BibTeX accessors.
- Autonomous traversal-policy tuning (Phase B).
- Vendor-locked databases (Scopus, WoS); only OpenAlex in Phase A.

## 3. Public Interface

> **LLM access (FIX_PLAN §27.2).** All LLM calls in this module — Gap Miner heuristic
> analysis, evidence extraction from OCR'd PDFs, paper summarization, and any future
> LLM-driven helper — go through `from factory.llm_client import OpenRouterClient`
> (spec 018) with `model="google/gemini-3.5-flash"`. The literature module never imports
> the `openai` SDK directly; the shared client owns the base URL, the env var
> (`OPENROUTER_API_KEY`), and the retry / pricing / rate-limit policy. (§27 layers
> spec 018 on top of §25's single-env-var invariant.)

```python
# factory/literature/api.py

from __future__ import annotations
from pathlib import Path
from typing import Literal, NewType, Sequence
from pydantic import BaseModel, ConfigDict, Field
from factory.artifacts import GapCandidate, ArtifactHash, FactoryError

# --- Errors ---------------------------------------------------------------

class LiteratureError(FactoryError): ...
class OpenAlexAPIError(LiteratureError): ...
class GraphStoreCorruption(LiteratureError): ...
class TraversalBudgetExhausted(LiteratureError): ...
class PaperPromoteFailed(LiteratureError): ...
class GapMinerProducedNoCandidates(LiteratureError): ...
class EvidenceExtractionFailed(LiteratureError): ...
class BibtexUnavailable(LiteratureError): ...

# --- Typed identifiers ----------------------------------------------------

OpenAlexWorkId = NewType("OpenAlexWorkId", str)   # canonical "W..." identifier
WorkId = OpenAlexWorkId                            # retained alias

# --- OpenAlex Work response (typed slice) ---------------------------------

class OpenAccess(BaseModel):
    """Nested representation of OpenAlex Work.open_access.

    NOTE on `is_oa` dual representation:
      - In query strings, use the Works filter `open_access.is_oa:true`.
      - In Work response bodies, the flag is nested as `open_access.is_oa`.
    The Pydantic model below mirrors the response shape; the query-string
    form is handled by OpenAlexClient.search_works(filters=...).
    """
    model_config = ConfigDict(frozen=True)
    is_oa: bool
    oa_status: Literal["gold", "green", "hybrid", "bronze", "closed"] | None = None
    oa_url: str | None = None

class OpenAlexAuthor(BaseModel):
    model_config = ConfigDict(frozen=True)
    display_name: str
    orcid: str | None = None

class OpenAlexWork(BaseModel):
    """Typed slice of an OpenAlex /works response.

    Note: forward citations are NOT exposed as a `cited_by_api_url` field on
    this model. Use OpenAlexClient.get_forward_citations(work_id), which
    calls the canonical filter endpoint /works?filter=cites:<work_id>.
    """
    model_config = ConfigDict(frozen=True)
    id: OpenAlexWorkId
    title: str
    publication_year: int | None
    venue_display_name: str | None
    authors: list[OpenAlexAuthor]
    abstract: str | None
    open_access: OpenAccess                      # is_oa lives at open_access.is_oa
    cited_by_count: int
    referenced_works: list[OpenAlexWorkId] = Field(default_factory=list)

# --- Policy / traversal ---------------------------------------------------

class ScoringWeights(BaseModel):
    model_config = ConfigDict(frozen=True)
    relevance_weight: float
    citation_weight: float
    recency_weight: float
    oa_pdf_weight: float
    bridge_weight: float
    diversity_lambda: float

class BranchFactor(BaseModel):
    model_config = ConfigDict(frozen=True)
    backward: int
    forward: int

class TraversalPolicy(BaseModel):
    """Loaded from YAML; see §4.2."""
    model_config = ConfigDict(frozen=True)
    provider: Literal["openalex"]
    max_depth: int
    max_nodes: int
    branch_factor: BranchFactor
    max_pages: int            # forward-citation pagination cap
    wall_clock_s: float
    filters: dict[str, str | int | bool]   # passed through to OpenAlex filter syntax
    scoring: ScoringWeights
    promote_top_k_to_paper_store: int

class TraversalRun(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: str
    seed_ids: tuple[OpenAlexWorkId, ...]
    node_count: int
    edge_count: int
    wall_clock_s: float

class RankedPaper(BaseModel):
    model_config = ConfigDict(frozen=True)
    work_id: OpenAlexWorkId
    score: float
    rationale: str

class PromotionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    promoted: list[OpenAlexWorkId]
    failed: list[tuple[OpenAlexWorkId, str]]      # (id, reason)

# --- Extracted evidence (v1 schema TBD; carried on PaperStoreEntry) -------

class ExtractedEvidence(BaseModel):
    """v1 frozen evidence record; field set TBD during implementation.

    Captures stated claims, methods used, simulators referenced, datasets
    referenced, numerical results (with units), and explicit limitations /
    negative results. Consumed by spec 011 (RAG writer).
    """
    model_config = ConfigDict(frozen=True)
    # Fields TBD — see §4.3 / Open Questions §9.

# --- PaperStore -----------------------------------------------------------

class PaperStoreEntry(BaseModel):
    """A single promoted paper, with on-disk asset paths and extracted evidence."""
    model_config = ConfigDict(frozen=True)
    work_id: OpenAlexWorkId
    title: str
    authors: list[OpenAlexAuthor]
    year: int | None
    venue: str | None
    abstract: str | None
    pdf_path: Path | None                  # None if OA PDF unavailable but evidence extracted from abstract
    extracted_evidence: ExtractedEvidence
    bibtex: str | None                     # synthesized BibTeX entry (None if BibtexUnavailable)

class PaperStore:
    """Public, persisted store of promoted papers.

    Filesystem layout per FIX_PLAN §10:
        runs/_paper_store/<work_id>/
            work.json
            pdf.pdf              # optional; only present when explicitly fetched
            ocr.txt
            evidence.json
            bibtex.bib            # absent when metadata cannot form BibTeX
            PROVENANCE.json

    All public methods are read-only EXCEPT `promote`. Mutation goes through
    the staging-then-atomic-rename pattern (§5.4).
    """

    def __init__(self, root: Path) -> None: ...

    # --- Public surface (FIX_PLAN §18) ---
    def query(self, topic: str, limit: int) -> list[PaperStoreEntry]:
        """Topic-keyword query against locally promoted papers (no network)."""
        ...

    def get(self, work_id: OpenAlexWorkId) -> PaperStoreEntry:
        """Fetch a single entry by Work ID. Raises KeyError if not promoted."""
        ...

    def get_bibtex(self, work_id: OpenAlexWorkId) -> str:
        """Return the BibTeX entry for a promoted paper.

        Raises BibtexUnavailable if the entry exists but BibTeX synthesis
        failed (e.g., insufficient metadata). Raises KeyError if the paper
        is not in the store.
        """
        ...

    def has_bibtex(self, work_id: OpenAlexWorkId) -> bool:
        """Cheap predicate; never raises for known entries."""
        ...

    def promote(self, work_ids: list[OpenAlexWorkId], *, fetch_pdf: bool = False) -> list[PaperStoreEntry]:
        """Promote one or more Work IDs from the graph into the Paper Store.

        Internally: write an OpenAlex snapshot, abstract-backed text, evidence
        placeholder, provenance, optional fetched PDF, and synthesized BibTeX
        when metadata is sufficient. Writes are atomic per Work ID.
        """
        ...

    @classmethod
    def mock(cls) -> "PaperStore":
        """Return a fixture-backed PaperStore with deterministic entries."""
        ...

# --- OpenAlex client ------------------------------------------------------

class OpenAlexClient:
    """Typed wrapper over the public OpenAlex /works API.

    Forward citations are served exclusively via the filter endpoint
    `/works?filter=cites:<work_id>` per FIX_PLAN §18. There is no separate
    cited_by_api_url surface on this client.
    """

    def get_work(self, work_id: OpenAlexWorkId) -> OpenAlexWork: ...
    def search_works(
        self,
        query: str,
        filters: dict[str, str | int | bool],   # e.g. `open_access.is_oa=True`
    ) -> list[OpenAlexWork]: ...
    def get_backward_references(self, work_id: OpenAlexWorkId) -> list[OpenAlexWorkId]: ...
    def get_forward_citations(
        self,
        work_id: OpenAlexWorkId,
        max_pages: int,
    ) -> list[OpenAlexWorkId]:
        """Calls `/works?filter=cites:<work_id>` with cursor pagination capped at max_pages."""
        ...
    def batch_get_works(
        self,
        work_ids: Sequence[OpenAlexWorkId],
    ) -> list[OpenAlexWork]: ...

# --- LiteratureDiscovery facade ------------------------------------------

class LiteratureDiscovery:
    """Top-level facade. Composes client, graph store, traversal, ranker, paper store, gap miner."""

    def __init__(
        self,
        policy: TraversalPolicy,
        graph_store_path: Path,
        paper_store: PaperStore,
        mock_mode: bool = False,
    ) -> None: ...

    # Agent-facing tool surface (matches SPEC.md §6.4)
    def openalex_seed_search(
        self,
        query: str,
        filters: dict[str, str | int | bool],
    ) -> list[OpenAlexWorkId]: ...
    def openalex_expand(
        self,
        work_id: OpenAlexWorkId,
        direction: Literal["backward", "forward"],
        limit: int,
    ) -> list[OpenAlexWorkId]: ...
    def openalex_traverse(
        self,
        seed_ids: Sequence[OpenAlexWorkId],
        policy: TraversalPolicy,
    ) -> TraversalRun: ...
    def openalex_graph_summary(self, run_id: str) -> dict[str, int | float | str]: ...
    def promote_papers_to_paper_store(
        self,
        work_ids: Sequence[OpenAlexWorkId],
    ) -> PromotionResult:
        """Thin wrapper over `PaperStore.promote` that returns a typed
        success/failure split instead of raising on first failure."""
        ...

    # Top-level convenience used by the state machine
    def mine_gaps(
        self,
        seed_query: str,
        cycle_id: str,
    ) -> list[GapCandidate]:
        """End-to-end: seed search → traverse → rank → promote top-k → emit GapCandidates."""
        ...

    @classmethod
    def from_mock(cls, fixture: str) -> "LiteratureDiscovery": ...
```

## 4. Data Structures / Schemas

> Concrete `ExtractedEvidence` field list and Gap Miner heuristic policy are TBD during implementation; the contracts in §3 are fixed.

### 4.1 `OpenAlexGraphStore` schema (TBD)

- Backing store: SQLite at `<graph_store_path>/graph.sqlite` (default) or a JSON-shard layout for small fixtures.
- Tables: `works`, `edges` (with `edge_kind ∈ {backward, forward, related}`), `traversal_runs`, `ranking_scores`.
- Explicitly **not** the same store as `EvidenceLedger` (spec 012) — external paper nodes are reference-only and never act as run-provenance anchors.

### 4.2 `TraversalPolicy` YAML schema

```yaml
literature_discovery:
  provider: openalex
  max_depth: 2
  max_nodes: 500
  branch_factor:
    backward: 20
    forward: 20
  max_pages: 5                  # forward-citation pagination cap
  wall_clock_s: 120
  filters:
    type: article
    open_access.is_oa: true
    publication_year_min: 2015
  scoring:
    relevance_weight: 0.45
    citation_weight: 0.20
    recency_weight: 0.15
    oa_pdf_weight: 0.10
    bridge_weight: 0.10
    diversity_lambda: 0.5       # MMR trade-off
  promote_top_k_to_paper_store: 25
```

The `open_access.is_oa: true` line is the Works filter form. The same flag appears as `open_access.is_oa` in OpenAlex Work response bodies — see `OpenAlexWork.open_access` and `OpenAccess` in §3 for the nested representation.

### 4.3 Paper Store layout (canonical)

Per FIX_PLAN §10, the Paper Store root is **`runs/_paper_store/`**:

```
runs/_paper_store/<work_id>/
├── work.json              # OpenAlex Work record snapshot
├── pdf.pdf                # OA PDF if explicitly fetched and available
├── ocr.txt                # OCR / parsed text; abstract-backed until OCR is wired
├── evidence.json          # Extracted-evidence schema instance (TBD)
├── bibtex.bib             # Synthesized BibTeX entry when metadata is sufficient
└── PROVENANCE.json        # provider, Work ID, promotion time, work hash
```

- The `ExtractedEvidence` v1 schema captures: stated claims, methods used, simulators referenced, datasets referenced, numerical results (with units), and explicit limitations / negative results. RAG writer (spec 011) reads these files.
- `bibtex.bib` is synthesized at promote time from the `OpenAlexWork` record (authors + year + title + venue). If required fields are missing, the file is absent and `PaperStore.has_bibtex(work_id)` returns `False`; `get_bibtex(work_id)` raises `BibtexUnavailable`.

### 4.4 `GapCandidate` emission

`GapCandidate` is defined in spec 002 — this module emits, does not redefine. Each emitted candidate carries:
- `gap_type` ∈ {`structural_hole`, `methodology_transfer`, `contradiction`, `negative_result`} (underscored form, canonical per SPEC.md §6.6).
- `source_papers` = list of promoted OpenAlex Work IDs. The CLI promotes the configured top-k subset before gap emission and only passes those promoted papers to the miner.
- `rationale` linking the gap to specific paper evidence retrievable via `PaperStore.get(work_id)`.
- `confidence` ∈ [0, 1].
- `seed_query` carried through from the inbound request.
- `parent_hashes` may include the traversal-run identifier as a non-artifact provenance reference (TBD).

## 5. Algorithms / Logic

### 5.1 OpenAlex client

- Pagination via `cursor=*`; field selection via `select=`.
- `OPENALEX_API_KEY` is appended to every request as `api_key=<key>`. The historical `mailto` polite-pool parameter is obsolete and not part of the live request contract.
- Forward citations use **only** the filter endpoint: `GET /works?filter=cites:<work_id>` with cursor pagination capped at `policy.max_pages`. No `cited_by_api_url` field is read or surfaced.
- Cache-on-write into `OpenAlexGraphStore` so identical calls are local-only on repeat.
- Vendoring vs direct HTTPS: TBD; both yield the same surface.

### 5.2 Bounded traversal

- Current implementation uses deterministic bounded BFS over backward references, forward citations, and related-work edges. It cache-writes every visited work and observed edge into `OpenAlexGraphStore`.
- Termination conditions are explicit: `max_depth`, `max_nodes`, `branch_factor`, `max_pages`, and `wall_clock_s`. Wall-clock exhaustion raises `TraversalBudgetExhausted`; node/depth/branch limits return the partial ranked set.
- Repeat traversals prefer cached works and cached forward edges, so identical calls can run local-only after the graph has been written.

### 5.3 Paper ranking

- Current implementation ranks deterministically by open-access status, citation count, publication year, and Work ID. This keeps promotion order reproducible while the richer policy-weighted ranker is still TBD.
- TBD: factor weighting per policy YAML; baseline factors are relevance × citation count × recency × OA-PDF availability × graph role × diversity (MMR).
- TBD: graph-role tagging — `bridge | seminal | extension | leaf` — derived from the local subgraph topology only (no external metric source).

### 5.4 Paper Store promotion

- Optional OA PDF fetcher with byte cap; `fetch_pdf=True` requires a configured content fetcher.
- OCR pipeline and extractor are TBD; current `ocr.txt` is abstract/title-backed and `evidence.json` is a typed placeholder.
- BibTeX synthesis from the typed `OpenAlexWork` record (authors + year + title + venue + DOI when present). If required fields are missing, `bibtex.bib` is absent, `has_bibtex(work_id)` returns `False`, and `get_bibtex(work_id)` raises `BibtexUnavailable`.
- All writes go through a staging-then-atomic-rename pattern (`runs/_paper_store/.<work_id>.staging` → `runs/_paper_store/<work_id>/`) so partial promotions do not leave a half-built final directory.

### 5.5 Gap Miner (baseline heuristic)

- **Input** (fixed contract): promoted ranked papers. Production evidence scoring from `PaperStore.get(work_id)` remains TODO until `ExtractedEvidence` v1 is frozen.
- **Output** (fixed contract): list of `GapCandidate`, each tagged with one of the four `gap_type`s. Internal scoring is implementation-time policy; the contract above is the binding surface.
- Hard rule (per SPEC.md §6.6): a citation-graph hole is not automatically a gap — every candidate must carry a rationale that survives G1 conversion in the state machine (`gap → falsifiable hypothesis → measurable metric → available simulator/data → baseline → stop condition`).
- If no promoted papers are available, raise `GapMinerProducedNoCandidates`; the state machine treats this as a non-fatal null run and may widen the seed query.

### 5.6 Hard boundary enforcement

```
Literature informs HOW to search.
Experiment DB informs WHERE to search.
```

This module never writes simulator config values. The state machine (spec 003) is responsible for enforcing that any numeric simulator parameter has either an evidence link in the Paper Store or a record in the local experiment database. `GapCandidate.rationale` may reference numeric ranges from papers; downstream gates decide whether those become candidate parameters.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `OpenAlexAPIError(LiteratureError)` | Network failure, 4xx/5xx from OpenAlex, malformed response | Retry with exponential backoff; cache hits remain valid; persistent failure surfaces to operator and pauses cycle entry |
| `GraphStoreCorruption(LiteratureError)` | Hash / schema check on cache fails | Quarantine the store; trigger `--rebuild-graph-store`; do not proceed to traversal |
| `TraversalBudgetExhausted(LiteratureError)` | Policy limit hit before useful coverage achieved | State machine treats current run as partial; may relax policy or expand seed set on retry |
| `PaperPromoteFailed(LiteratureError)` | Future OCR/extractor promotion failures once those stages are wired | Paper remains a graph node only; not added to Paper Store; logged for human spot-check |
| `GapMinerProducedNoCandidates(LiteratureError)` | Ranked set yielded no gap meeting threshold | Non-fatal; state machine may retry with a widened seed query or escalate to operator |
| `EvidenceExtractionFailed(LiteratureError)` | Promotion succeeded textually but `evidence.json` failed schema | Paper is quarantined under `runs/_paper_store/_quarantine/`; logged with full extractor output |
| `BibtexUnavailable(LiteratureError)` | BibTeX synthesis missing year + authors or otherwise non-renderable | Paper stays promoted; `has_bibtex(work_id)` returns False; writer (spec 011) handles the missing-citation case |

## 7. Testing

**Mock-mode** (in CI):
- `test_literature_typical_usage.py` — REQUIRED. End-to-end mock run: seed query → traversal → rank → promotion → ≥1 `GapCandidate` emitted. Verifies artifact shape and hash stability.
- `test_openalex_client_typed.py` — every client method returns the declared type against fixture responses; covers nested `open_access.is_oa` parsing AND `open_access.is_oa:true` filter encoding.
- `test_openalex_forward_citations_filter_endpoint.py` — asserts `get_forward_citations` hits `/works?filter=cites:<work_id>` and never reads a `cited_by_api_url` field.
- `test_traversal_bounds.py` — each policy limit (`max_depth`, `max_nodes`, `branch_factor`, `max_pages`, `wall_clock_s`) is independently enforced.
- `test_ranker_determinism.py` — ranking order is stable for open-access, citation-count, publication-year, and Work-ID tie breaks.
- `test_paper_store_atomic_promote.py` — repeated promotion atomically replaces the per-work directory and removes stale assets.
- `test_paper_store_public_api.py` — `PaperStore.query / get / get_bibtex / has_bibtex / promote / mock()` all return / raise per §3; `BibtexUnavailable` raised correctly when metadata insufficient.
- `test_gap_miner_four_types.py` — fixture inputs produce at least one example of each underscored `gap_type`.
- `test_hard_boundary.py` — module never writes simulator parameter values to any artifact.
- `test_openalex_api_key_env.py` — client requires `OPENALEX_API_KEY`, rejects stale `OPENALEX_EMAIL`, and does not depend on `OPENALEX_MAILTO`.

**Live-mode** (`@pytest.mark.live`, gated):
- `test_live_seed_search.py` — single low-cost query against the real OpenAlex API.
- `test_live_promote_one_oa_paper.py` — `[TBD-impl]` fetch + OCR + extract + BibTeX-synthesize a known OA paper once OCR/extraction is wired.

## 8. Performance & Budget

- Mock-mode end-to-end: < 2 s for a fixture run.
- Live traversal: policy-bounded; default policy targets ≤ 2 minutes wall clock and ≤ 500 nodes per run.
- Paper promotion: current abstract-backed promotion is local filesystem work plus optional PDF fetch; future OCR + LLM extraction costs are budgeted by spec 013.
- All persistent stores are local; no per-cycle cloud spend beyond OpenAlex calls (free) and the extraction LLM.

## 9. Open Questions

- **Provider abstraction.** Phase A is OpenAlex-only. A `LiteratureProvider` protocol is plausible later but speculative now.
- **`ExtractedEvidence` canonicality.** The v1 field list (§4.3) needs to be frozen before spec 011 (RAG writer) can finalize.
- **Graph-store eviction.** Unbounded cache growth is fine in Phase A; eviction policy is Phase B.
- **Gap Miner calibration.** Whether the four `gap_type`s have balanced emission rates in practice is empirical; track over the first ~20 cycles.
- **Cross-cycle traversal reuse.** A traversal run done in cycle N may be reusable in cycle N+1 with a related seed; reuse policy is TBD.
- **BibTeX synthesis fallbacks.** Whether to call out to a secondary metadata source (e.g., Crossref) when OpenAlex metadata is insufficient is TBD.

## 10. TODO Checklist

- [x] Scaffold `factory/literature/` from the canonical module template.
- [x] Implement `OpenAlexClient` typed wrapper with API-key support and forward citations via `/works?filter=cites:<work_id>` only.
- [x] Implement `OpenAlexGraphStore` (SQLite backing) with corruption check.
- [x] Implement traversal with policy enforcement.
- [x] Implement deterministic paper ranking.
- [x] Implement `PaperStore` class with the public surface in §3 (`query`, `get`, `get_bibtex`, `has_bibtex`, `promote`, `mock`), backed by `runs/_paper_store/<work_id>/`.
- [x] Implement atomic promotion (staging-then-rename) and BibTeX synthesis.
- [ ] Freeze `ExtractedEvidence` v1 schema; coordinate with spec 011.
- [x] Implement baseline `GapMiner` producing `GapCandidate` artifacts in all four underscored `gap_type`s.
- [ ] Implement evidence-scored production Gap Miner rationales from PaperStore evidence.
- [ ] Implement the 5 agent-facing tools matching SPEC.md §6.4 verbatim.
- [ ] Author default `TraversalPolicy` YAML in `factory/literature/config/` and loader.
- [ ] Author mock fixtures (graph snippet + canned PDF + canned evidence + canned BibTeX) under `factory/literature/fixtures/`.
- [x] Write `factory/literature/cli.py` with all subcommands listed in ENTRY POINTS.
- [x] Write the mock-mode tests listed in §7 for the implemented surfaces.
- [ ] Write the 2 live-mode tests behind `@pytest.mark.live` (seed search is implemented; live PDF/OCR promotion remains TBD).
- [x] Write `docs/runbooks/literature-discovery.md`.
- [x] Write `factory/literature/README.md` (≤ 1 page, mock-mode example).
- [x] Verify `mypy --strict factory/literature/` passes.
- [x] Verify `python -m factory.literature --mock-mode mine-gaps --seed-query "QI stellarator coil simplicity"` works on a fresh checkout.
- [ ] Confirm hard-boundary test (§7 `test_hard_boundary.py`) blocks any direct simulator-parameter emission.
- [x] Confirm env-var test (§7 `test_openalex_api_key_env.py`) requires `OPENALEX_API_KEY` and rejects `OPENALEX_EMAIL`.
