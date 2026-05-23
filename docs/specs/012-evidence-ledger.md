# Spec 012: Evidence Ledger

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- The **Evidence Ledger** is the factory's persistent memory of outcomes. Every `EvidenceLedgerEntry` (defined in spec 002) lives here: result, provenance, uncertainty, relitigation triggers, and links to the source `CouncilVerdict`s and `RunReport`. It is the substrate against which the state machine (spec 003) decides whether a hypothesis is fresh, the surrogate (spec 010) draws training rows, the RAG writer (spec 011) cites internal prior work, and the C5 council (spec 001) audits compounding internal hallucinations.
- The 5 facts: (1) backend is **SQLite with WAL** for Phase A — single-writer per cycle, lock-free readers; (2) every entry is **immutable** once committed — re-litigation produces a new entry whose `parent_hashes` chain back to the prior one; (3) every entry carries a **`provenance_hash`** the ledger re-verifies on read; (4) entries also persist as flat JSON under `runs/<cycle-id>/artifacts/<hash>.json` — SQLite is the **index**, JSON is the **source of truth for the artifact** (Phase A invariant 1.3 + 1.8); (5) the audit query "top-K most-cited high-uncertainty internal findings" exists specifically as **the front-line defense against internal hallucination compounding (SPEC §10.4)**.
- Open first: `factory/ledger/api.py` for the CRUD contract, then `factory/ledger/tests/test_ledger_typical_usage.py`.

## ENTRY POINTS
- Main module: `factory/ledger/api.py`
- Typical-usage test: `factory/ledger/tests/test_ledger_typical_usage.py`
- CLI: `python -m factory.ledger --help` (subcommands: `insert`, `get`, `query`, `audit`, `verify`, `export`, `restore`, `evaluate-triggers`, `mark-stale`)
- Mock-mode example: `python -m factory.ledger query --result falsified --simulator-id vmecpp --limit 5 --mock-mode`
- Runbook: `docs/runbooks/ledger-audit.md`

## LOCAL DEBUG
- Instantiate in-memory in a REPL: `Ledger(db_path=":memory:", mock_mode=True).insert_entry(EvidenceLedgerEntry.from_fixture("typical_passed"))`. Returns the canonical `EvidenceLedgerEntry` round-tripped from SQLite.
- Live mode requires a writable filesystem path: `Ledger(db_path=Path("runs/ledger.db"))`. WAL files (`*.db-wal`, `*.db-shm`) are created automatically; never check them in.
- Common error signatures → recovery:
  - `LedgerWriteFailed` → SQLite raised `OperationalError` (locked / disk full / read-only). State machine pauses the cycle; operator inspects `runs/<cycle-id>/cycle.jsonl` for the underlying message.
  - `LedgerCorruption` → entry's stored `provenance_hash` does not match recomputation. Treat the entry as **poisoned**: quarantine via `mark_stale`, do not feed it into surrogate training or RAG retrieval, surface to C5.
  - `EntryNotFound` → caller queried a hash that has no row; usually a typo or a cycle whose JSON was deleted without ledger sync.
  - `RelitigateCheckFailed` → `evaluate_triggers` could not import or run a `check_fn`. The trigger stays `currently_satisfied=False` and the failure is logged; the entry is **not** flagged stale on this alone.
  - `DowngradedDueToStaleness` → C5 or a manual call has flagged an entry stale; downstream queries that opt into `include_stale=False` (the default) will skip it.
  - `LedgerSchemaMismatch` → DB schema version on disk differs from code; Phase A pins schema and refuses to open mismatched DBs.
- Logs to inspect: every CRUD call emits a structured event to `runs/<cycle-id>/cycle.jsonl` with `module=ledger`. The DB itself records nothing beyond table rows; logs are the audit trail.

## DEPENDENCIES
- **Hard:** Spec 002 (artifacts) — `EvidenceLedgerEntry`, `ProvenanceBlock`, `RelitigationTrigger`, `EvidenceResult`, hash helpers. Nothing else.
- **Soft:** Spec 014 (telemetry) — structured events; this module registers three event names in `events.py` (see §3.2). Spec 013 (budget) — **in Phase A budget runs JSON-only** and does NOT add tables to this DB file (per FIX_PLAN §4); a Phase B option to share the DB file is explicitly deferred. Both fall back to no-op cleanly.
- **Mocks:** `Ledger(mock_mode=True, db_path=":memory:")` returns an in-memory SQLite instance pre-seeded with fixture entries from `factory/ledger/fixtures/seed_entries.jsonl`.
- **Consumers** (FYI only — these specs read from ledger; they do not write through any path other than the public API): spec 003 state machine (G0 freshness check, `evaluate_triggers` before re-litigation), spec 010 surrogate (training-set queries), spec 011 RAG writer (internal-citation queries), spec 001 C5 council (audit queries for re-audit).

---

## 1. Summary

The Evidence Ledger is the single durable memory of factory outcomes. Every passed, falsified, intractable, or inconclusive hypothesis lands here as an immutable `EvidenceLedgerEntry`, with a content-addressed provenance hash, an uncertainty block, and zero or more `RelitigationTrigger`s. The ledger is queried by every downstream module that needs to know "what has the factory already learned?" — and it is audited by C5 to detect **internal hallucination compounding** before false findings shape new hypotheses.

The Phase A design choices follow the architecture invariants (ARCHITECTURE.md §1) tightly: (a) SQLite with WAL gives single-writer durability with lock-free reads, sufficient for one-cycle-at-a-time writes; (b) entries persist twice — once as a row, once as the canonical JSON under the cycle's artifact directory — so the JSON file is the source of truth and the DB is the index; (c) all writes go through the typed public API in `factory.ledger`, never through raw SQL from another module; (d) JSON Lines export and restore are first-class to make the ledger reproducible and forklift-able to another host.

## 2. Scope

**In scope:**
- SQLite-backed durable store with WAL mode and connection-per-cycle isolation.
- Public CRUD API: `insert_entry`, `get_by_id`, `get_by_hash`, `query`, `update_relitigate_status`, `mark_stale`.
- Audit-query API for C5: `top_cited_entries`, `high_uncertainty_with_dependents`, `flagged_stale_entries`.
- Re-litigation trigger evaluation: background-callable `evaluate_triggers` that updates `currently_satisfied` per trigger.
- Provenance verification on every read: stored `provenance_hash` is recomputed and compared.
- Reference-existence verification: optional `verify(entry, deep=True)` that re-reads the referenced JSON files for `council_verdict_hashes` and `run_report_hash` from disk and confirms they exist with matching hashes.
- Backup / restore: `ledger export --format jsonl` dumps all entries to JSON Lines; `ledger restore --from <file.jsonl>` rebuilds a fresh DB from the dump.
- CLI: `insert`, `get`, `query`, `audit`, `verify`, `export`, `restore`, `evaluate-triggers`, `mark-stale`.
- Mock mode with in-memory DB + pre-seeded fixtures.

**Out of scope:**
- Schema migrations. Phase A pins the schema; if a field is added later, that's a Phase B concern handled by spec versioning of `EvidenceLedgerEntry` itself (see spec 002 §9).
- Multi-writer concurrency. Cycles run serially in Phase A; SQLite WAL is sufficient. Multi-cycle parallelism is Phase C and would migrate to a different backend.
- Direct write access from any other module. Spec 003 state machine is the **only** caller of `insert_entry` and `update_relitigate_status` (it can delegate to the cycle's recorder, but the call site lives behind one boundary).
- Heavy analytics (cross-cycle dashboards, time-series joins). The export-to-JSONL path lets external tooling do that; the ledger itself stays small and focused.
- Storing full `RunReport` LaTeX or figures. The ledger stores the hash; the artifact JSON stores the metadata; the LaTeX and figures live in `runs/<cycle-id>/artifacts/`.

## 3. Public Interface

```python
# factory/ledger/api.py

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Literal, Sequence
from factory.artifacts import (
    EvidenceLedgerEntry,
    EvidenceResult,
    RelitigationTrigger,
    ArtifactHash,
    HypothesisId,
    CycleId,
    FactoryError,
)

class LedgerError(FactoryError): ...
class LedgerWriteFailed(LedgerError): ...
class LedgerCorruption(LedgerError): ...
class EntryNotFound(LedgerError): ...
class RelitigateCheckFailed(LedgerError): ...
class DowngradedDueToStaleness(LedgerError): ...
class LedgerSchemaMismatch(LedgerError): ...

@dataclass(frozen=True)
class LedgerQuery:
    """Filter set for `query`. Fields are AND-combined; None means 'don't filter'."""
    hypothesis_id: HypothesisId | None = None
    result: EvidenceResult | None = None
    simulator_id: str | None = None
    cycle_id: CycleId | None = None
    has_dissent: bool | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    include_stale: bool = False
    limit: int = 100
    order_by: Literal["created_at_desc", "created_at_asc", "citation_count_desc"] = "created_at_desc"

@dataclass(frozen=True)
class AuditTopCited:
    entry_hash: ArtifactHash
    hypothesis_id: HypothesisId
    citation_count: int        # number of downstream artifacts that reference this entry's hash
    max_downstream_uncertainty: float
    is_stale: bool

@dataclass(frozen=True)
class AuditHighUncertainty:
    entry_hash: ArtifactHash
    hypothesis_id: HypothesisId
    primary_uncertainty: float
    downstream_dependent_count: int
    is_stale: bool

@dataclass(frozen=True)
class AuditHighSurprise:
    """C5 audit row for the `top_high_surprise_with_dependents` query (FIX_PLAN §26.4).

    Ranks entries by `surprise_bits × downstream_citation_count`. Entries whose
    `surprise_bits` is NULL (the strategy archive never scored them) sort **last**
    so the audit always promotes scored surprising findings ahead of unscored ones.
    """
    entry_hash: ArtifactHash
    hypothesis_id: HypothesisId
    surprise_bits: float | None              # NULL until the strategy archive scores
    downstream_citation_count: int
    composite_score: float                   # surprise_bits * downstream_citation_count; 0.0 when surprise NULL
    is_stale: bool

@dataclass(frozen=True)
class TriggerEvaluationReport:
    entry_hash: ArtifactHash
    trigger_index: int
    condition: str
    previous_state: bool
    new_state: bool
    error: str | None             # set if the check_fn raised

@dataclass(frozen=True)
class TrainingDataQuery:
    """Narrow filter set used by spec 010 surrogate training. Distinct from `LedgerQuery`
    so the surrogate read path cannot accidentally widen into mutation territory."""
    observable: str                                # ObservableName the surrogate is learning
    simulator_id: str | None = None
    min_seeds: int = 1
    include_stale: bool = False                    # surrogate MUST default to False
    created_after: datetime | None = None
    limit: int = 10_000

@dataclass(frozen=True)
class LedgerTrainingRow:
    """The minimal, denormalized row the surrogate consumes. Carries the provenance hash
    so the surrogate can record exactly which Ledger entry every training point came from."""
    hypothesis_id: HypothesisId
    feature_vector: Sequence[float]                # extracted from the originating ExperimentSpec
    true_value: float                              # the observable's reported value
    uncertainty: float                             # primary_uncertainty scalar from the entry
    provenance_hash: ArtifactHash                  # = EvidenceLedgerEntry.provenance_hash

class EvidenceLedgerReader:
    """Narrow, read-only view over the Ledger used by spec 010 (surrogate training data
    queries). Exists so the surrogate module never imports the full `Ledger` write surface
    and so spec 010's contract is a small, stable shape. The live implementation composes
    a full `Ledger` underneath; the mock implementation returns fixture rows.
    """

    def __init__(self, ledger: "Ledger") -> None: ...

    def query_observable(self, q: TrainingDataQuery) -> Sequence[LedgerTrainingRow]:
        """Return training rows for the requested observable. Stale entries are excluded
        unless `q.include_stale=True`. Provenance is re-verified on read (delegates to the
        underlying `Ledger.get_by_hash` path). Raises `LedgerCorruption` if any row's
        artifact JSON fails verification — surrogate training is allowed to fail loud
        rather than train on poisoned data.
        """


# Public exports — both names ship from `factory.ledger`:
#   from factory.ledger import Ledger, EvidenceLedgerReader
class Ledger:
    """Durable, typed, content-verified Evidence Ledger."""

    def __init__(
        self,
        db_path: Path | str = Path("runs/ledger.db"),
        cycle_id: CycleId | None = None,
        artifact_root: Path = Path("runs"),
        mock_mode: bool = False,
        verify_on_read: bool = True,
    ) -> None: ...

    # ------------- CRUD -------------

    def insert_entry(self, entry: EvidenceLedgerEntry) -> ArtifactHash:
        """Persist a new entry. Returns its provenance_hash. Idempotent on identical hash.
        Raises LedgerWriteFailed on any SQLite OperationalError.
        Raises LedgerCorruption if entry.verify_self() fails before insert.
        The artifact JSON is also written to runs/<cycle_id>/artifacts/<hash>.json
        within the same transaction-equivalent unit (see §5.3).
        """

    def get_by_hash(self, entry_hash: ArtifactHash) -> EvidenceLedgerEntry:
        """Load and verify an entry. Raises EntryNotFound or LedgerCorruption."""

    def get_by_id(self, hypothesis_id: HypothesisId) -> list[EvidenceLedgerEntry]:
        """Return every entry for this hypothesis, newest first. A hypothesis may have
        multiple entries when re-litigated (each new entry's parent_hashes points back).
        """

    def query(self, q: LedgerQuery) -> list[EvidenceLedgerEntry]:
        """Filtered query. See LedgerQuery for filter semantics."""

    def update_relitigate_status(
        self,
        entry_hash: ArtifactHash,
        trigger_index: int,
        currently_satisfied: bool,
    ) -> None:
        """Mutate ONLY the trigger evaluation state of an entry. The entry itself stays
        immutable (its provenance_hash does not change); trigger state lives in a sibling
        table (see §4.2) and is not part of the hashed content.
        """

    def mark_stale(self, entry_hash: ArtifactHash, reason: str, marked_by: str) -> None:
        """Flag an entry stale (e.g., C5 spot-check found a flaw). Stale entries are
        excluded from default queries; surrogate training (spec 010) MUST honor stale flag.
        """

    # ------------- Audit (C5 surface) -------------

    def top_cited_entries(self, k: int = 20, min_uncertainty: float = 0.0) -> list[AuditTopCited]:
        """Top-K entries by downstream citation count. The first-line defense against
        internal hallucination compounding (SPEC §10.4): the most-cited internal findings
        are exactly the entries whose error would propagate widest.
        """

    def high_uncertainty_with_dependents(
        self,
        uncertainty_threshold: float,
        min_dependents: int = 1,
    ) -> list[AuditHighUncertainty]:
        """Entries above the uncertainty threshold that have at least one downstream
        dependent. C5's re-audit shortlist.
        """

    def top_high_surprise_with_dependents(self, k: int) -> list[AuditHighSurprise]:
        """C5 audit query (FIX_PLAN §26.4): rank entries by
        `surprise_bits × downstream_citation_count` and return the top K.

        Entries whose `surprise_bits` is NULL (no strategy-archive score yet) sort
        **last** so scored surprising findings are always promoted ahead of unscored
        ones in the audit context document. Used by C5 program-direction (spec 003 §5.5)
        to surface high-leverage surprising findings whose error would compound widest.
        """

    def update_surprise(self, entry_hash: ArtifactHash, bits: float) -> None:
        """Write the `surprise_bits` column on an existing entry (FIX_PLAN §26.4).

        Called by `specs/016-strategy-archive.md` after attributing Bayesian surprise
        to a cycle's `EvidenceLedgerEntry`. The entry's `provenance_hash` is **not**
        affected (surprise lives outside the immutable artifact, like trigger state
        and stale flag — see §4.2). Raises `EntryNotFound` if no row.
        """

    def flagged_stale_entries(self) -> list[EvidenceLedgerEntry]:
        """All entries currently marked stale."""

    # ------------- Verification -------------

    def verify(self, entry_hash: ArtifactHash, deep: bool = False) -> None:
        """Recompute provenance_hash; raise LedgerCorruption on mismatch.
        If deep=True, also confirm every referenced CouncilVerdict and RunReport JSON
        file exists on disk under artifact_root and has its expected hash.
        """

    # ------------- Re-litigation -------------

    def evaluate_triggers(
        self,
        entry_hashes: Sequence[ArtifactHash] | None = None,
    ) -> list[TriggerEvaluationReport]:
        """Re-run every RelitigationTrigger.check_fn on the given entries (or every active
        entry if None). Updates currently_satisfied. Designed to be called by a periodic
        scheduler (e.g., spec 003 weekly hook) or on demand by the state machine before
        G0 re-attempts a hypothesis.
        """

    # ------------- Backup / Export -------------

    def export(self, dst: Path, format: Literal["jsonl"] = "jsonl") -> int:
        """Stream every entry (including trigger state and stale flags) to a JSONL file.
        Returns count exported. The dump is deterministic given the same DB state.
        """

    def restore(self, src: Path, format: Literal["jsonl"] = "jsonl") -> int:
        """Rebuild a fresh DB from a JSONL dump. Refuses to run against a non-empty DB.
        Re-verifies every entry's provenance_hash on the way in.
        """

    # ------------- Lifecycle -------------

    def close(self) -> None:
        """Close the SQLite connection. Idempotent."""

    def __enter__(self) -> "Ledger": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
```

### 3.1 Public API stability surface

The following methods on `Ledger` are stable, name-pinned, and consumed by other specs.
They cannot be renamed or removed without a Phase B contract change:

| Method | Stability | Primary consumer |
| :--- | :--- | :--- |
| `insert_entry`              | stable | spec 003 (cycle terminal) |
| `get_by_id`                 | stable | spec 003 (G0 freshness check) |
| `get_by_hash`               | stable | spec 011 (RAG citation lookup), spec 003 |
| `query`                     | stable | spec 003, spec 011, operator CLI |
| `top_cited_entries`         | stable | spec 001 (C5 audit) |
| `top_high_surprise_with_dependents` | stable | spec 003 §5.5 (C5 program-direction audit); FIX_PLAN §26.4 |
| `update_surprise`           | stable | `specs/016-strategy-archive.md` (writes `surprise_bits` per cycle); FIX_PLAN §26.4 |
| `evaluate_triggers`         | stable | spec 003 (called at G0 before re-litigation; per FIX_PLAN §3) |
| `update_relitigate_status`  | stable | spec 003, internal callers of `evaluate_triggers` |
| `mark_stale`                | stable | spec 001 (C5 quarantine path) |

`EvidenceLedgerReader.query_observable` is on the same stability tier as the above; it is
spec 010's only entry point into the Ledger.

### 3.2 Registered events (`factory/ledger/events.py`)

Per FIX_PLAN §8 (extensible-by-namespace taxonomy) and spec 014, the `factory.ledger`
namespace registers exactly the following event names. Any `telemetry.emit(...)` call
inside this module that uses a name not in this list raises `EventTaxonomyViolation`
at startup (spec 014's aggregator reads this registry).

```python
# factory/ledger/events.py
from factory.telemetry import EventName

REGISTERED_EVENTS: frozenset[EventName] = frozenset({
    EventName("factory.ledger.entry_inserted"),           # emitted by insert_entry (§5.1 step 6)
    EventName("factory.ledger.trigger_check_failed"),     # emitted per-trigger on check_fn raise (§5.5)
    EventName("factory.ledger.evaluate_triggers_complete"),  # emitted after every evaluate_triggers run
})
```

Payload shapes (documented for the taxonomy registry; full schemas live in spec 014):

- `factory.ledger.entry_inserted` →
  `{entry_hash: ArtifactHash, hypothesis_id: HypothesisId, result: str, cycle_id: CycleId}`
- `factory.ledger.trigger_check_failed` →
  `{entry_hash: ArtifactHash, trigger_index: int, check_fn: str, error: str}`
- `factory.ledger.evaluate_triggers_complete` →
  `{evaluated_count: int, failed_count: int, flipped_to_true_count: int, cycle_id: CycleId | None}`

Spec 014's fixer extends the taxonomy module to import this set; the canonical module-template
contract in ARCHITECTURE.md §3 makes `events.py` the single declaration site per namespace.

## 4. Data Structures / Schemas

The artifact `EvidenceLedgerEntry` and its sub-types (`ProvenanceBlock`, `RelitigationTrigger`, `EvidenceResult`) are defined in spec 002. The ledger does **not** redefine them; it indexes them.

### 4.1 SQLite schema (Phase A, pinned — no migrations)

> **Scope note (per FIX_PLAN §4).** This DDL block contains **no `budget_ledger` table**.
> Phase A budget persistence is JSON-only (spec 013); the Evidence Ledger SQLite file stores
> exclusively the cycle/result tables listed below. If a future Phase B brings budget into
> SQLite, it will live in its own DB file or in a separately-scoped schema — never as a
> sibling table inside this file. Spec 013's fixer aligns its persistence claim to match.

```sql
-- Schema version pin; Phase A refuses to open a DB with a different value.
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Seeded once on first open: ("schema_version", "1"), ("phase", "A").

CREATE TABLE IF NOT EXISTS entries (
    entry_hash         TEXT PRIMARY KEY,          -- = EvidenceLedgerEntry.provenance_hash
    hypothesis_id      TEXT NOT NULL,
    result             TEXT NOT NULL CHECK (result IN
                            ('passed','falsified','intractable','inconclusive')),
    simulator_id       TEXT,                       -- nullable (e.g., G2.5 intractable kills before sim choice)
    cycle_id           TEXT NOT NULL,
    has_dissent_flag   INTEGER NOT NULL DEFAULT 0, -- 1 if any council_verdict in chain has preserved_dissents
    primary_uncertainty REAL,                      -- summary scalar pulled from entry.uncertainty for indexing
    surprise_bits      REAL,                       -- nullable; FIX_PLAN §26.4 — Bayesian surprise in bits,
                                                   -- written by specs/016-strategy-archive.md via update_surprise().
                                                   -- NULL until the archive scores the entry; never part of the
                                                   -- immutable artifact's provenance_hash (see §4.2).
    run_report_hash    TEXT,                       -- nullable
    is_stale           INTEGER NOT NULL DEFAULT 0,
    stale_reason       TEXT,
    stale_marked_by    TEXT,
    stale_marked_at    TEXT,                       -- ISO8601
    created_at         TEXT NOT NULL,              -- ISO8601 from the artifact itself
    json_path          TEXT NOT NULL               -- relative path under artifact_root, see §5.3
);

CREATE INDEX IF NOT EXISTS idx_entries_hypothesis ON entries (hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_entries_result     ON entries (result);
CREATE INDEX IF NOT EXISTS idx_entries_simulator  ON entries (simulator_id);
CREATE INDEX IF NOT EXISTS idx_entries_created    ON entries (created_at);
CREATE INDEX IF NOT EXISTS idx_entries_dissent    ON entries (has_dissent_flag);
CREATE INDEX IF NOT EXISTS idx_entries_stale      ON entries (is_stale);
CREATE INDEX IF NOT EXISTS idx_entries_surprise   ON entries (surprise_bits);  -- supports top_high_surprise_with_dependents (FIX_PLAN §26.4)

-- Provenance block expanded for queryability. Source of truth remains the entry JSON;
-- this is a denormalized projection for the audit query path.
CREATE TABLE IF NOT EXISTS provenance_blocks (
    entry_hash         TEXT PRIMARY KEY REFERENCES entries(entry_hash) ON DELETE CASCADE,
    code_hash          TEXT NOT NULL,
    env_hash           TEXT NOT NULL,
    input_hash         TEXT NOT NULL,
    seed               INTEGER,
    simulator_version  TEXT,
    container_sha      TEXT
);

-- Trigger state lives outside the immutable artifact; updating it does not change
-- the entry's provenance_hash.
CREATE TABLE IF NOT EXISTS relitigate_triggers (
    entry_hash             TEXT NOT NULL REFERENCES entries(entry_hash) ON DELETE CASCADE,
    trigger_index          INTEGER NOT NULL,
    condition              TEXT NOT NULL,
    check_fn               TEXT NOT NULL,         -- dotted path
    last_evaluated_at      TEXT,                  -- ISO8601, nullable
    currently_satisfied    INTEGER NOT NULL DEFAULT 0,
    last_error             TEXT,
    PRIMARY KEY (entry_hash, trigger_index)
);

CREATE INDEX IF NOT EXISTS idx_triggers_satisfied
    ON relitigate_triggers (currently_satisfied);

-- Edge table from entry → referenced CouncilVerdict artifact hashes.
CREATE TABLE IF NOT EXISTS council_verdict_refs (
    entry_hash       TEXT NOT NULL REFERENCES entries(entry_hash) ON DELETE CASCADE,
    verdict_hash     TEXT NOT NULL,
    council_id       TEXT NOT NULL,                -- C1/C2/C3/C4/C5
    PRIMARY KEY (entry_hash, verdict_hash)
);

CREATE INDEX IF NOT EXISTS idx_verdict_refs_verdict
    ON council_verdict_refs (verdict_hash);

-- Edge table from entry → RunReport.
CREATE TABLE IF NOT EXISTS run_report_refs (
    entry_hash       TEXT PRIMARY KEY REFERENCES entries(entry_hash) ON DELETE CASCADE,
    run_report_hash  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_report_refs_report
    ON run_report_refs (run_report_hash);

-- Reverse citation index: which entries reference this entry as a parent? Populated
-- on every insert by walking the new entry's parent_hashes. Used by top_cited_entries.
CREATE TABLE IF NOT EXISTS entry_citations (
    cited_hash       TEXT NOT NULL,                -- the older entry being cited
    citing_hash      TEXT NOT NULL REFERENCES entries(entry_hash) ON DELETE CASCADE,
    PRIMARY KEY (cited_hash, citing_hash)
);

CREATE INDEX IF NOT EXISTS idx_citations_cited  ON entry_citations (cited_hash);
CREATE INDEX IF NOT EXISTS idx_citations_citing ON entry_citations (citing_hash);
```

PRAGMAs set on every connection open:

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;       -- WAL + NORMAL is durable across process crash
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;         -- 5 s; cycles serial in Phase A so contention should be rare
```

### 4.2 What lives in SQLite vs. what lives in JSON

- **JSON file (`runs/<cycle-id>/artifacts/<hash>.json`)** is the canonical, hashed source of truth for the artifact content (`EvidenceLedgerEntry` exactly as defined in spec 002). This is what `compute_hash` runs over.
- **SQLite rows** are a **denormalized projection** for query and audit. Every column either (a) lives unchanged on the artifact (e.g., `hypothesis_id`, `result`, `created_at`, `provenance_hash`), or (b) is an indexed summary computed from the artifact at insert time (e.g., `has_dissent_flag`, `primary_uncertainty`).
- **Mutable trigger state** (`last_evaluated_at`, `currently_satisfied`, `last_error`) does **not** belong on the artifact (artifacts are immutable). It lives only in SQLite.
- **Stale flag and reason** are also SQLite-only mutable state.
- **Surprise bits** (`surprise_bits`, FIX_PLAN §26.4) are SQLite-only mutable state written by `specs/016-strategy-archive.md` via `Ledger.update_surprise(entry_hash, bits)`. NULL until the archive scores the entry. Not part of the artifact's `provenance_hash`. Surfacing in the C5 audit via `top_high_surprise_with_dependents` (§5).

The two stay in sync because (a) `insert_entry` writes both atomically (see §5.3); (b) `get_by_hash` re-reads the JSON file and verifies its hash on every read by default; (c) `verify(deep=True)` walks the edge tables and confirms every referenced JSON file still exists on disk.

## 5. Algorithms / Logic

### 5.1 Insert flow

```python
def insert_entry(self, entry: EvidenceLedgerEntry) -> ArtifactHash:
    # 1. Pre-verify: artifact must be internally consistent.
    entry.verify_self()                  # raises ArtifactProvenanceMismatch if tampered

    # 2. Idempotency: same hash already present → return existing hash, no-op.
    if self._row_exists(entry.provenance_hash):
        return entry.provenance_hash

    # 3. Compute the denormalized projection.
    has_dissent = self._compute_has_dissent(entry)         # walks council_verdict_hashes
    primary_uncertainty = self._summarize_uncertainty(entry.uncertainty)
    json_rel_path = self._artifact_json_path(entry)

    # 4. Write JSON FIRST. The file is the source of truth; if we crash between (4) and (5),
    #    the file is orphaned (recoverable) but never the row (which would lie about content).
    self._write_artifact_json(entry, json_rel_path)        # atomic temp+rename

    # 5. SQLite write — wrap in a single transaction so all five tables move together.
    with self._conn:                     # implicit BEGIN/COMMIT; rollback on exception
        self._conn.execute(INSERT_ENTRY_SQL, (...))
        self._conn.execute(INSERT_PROVENANCE_SQL, (...))
        for i, t in enumerate(entry.relitigate_if):
            self._conn.execute(INSERT_TRIGGER_SQL, (entry.provenance_hash, i, t.condition,
                                                    t.check_fn,
                                                    t.last_evaluated_at, t.currently_satisfied))
        for v_hash in entry.council_verdict_hashes:
            council_id = self._lookup_council_id(v_hash)   # reads the verdict JSON
            self._conn.execute(INSERT_VERDICT_REF_SQL, (entry.provenance_hash, v_hash, council_id))
        if entry.run_report_hash is not None:
            self._conn.execute(INSERT_RUN_REPORT_REF_SQL, (entry.provenance_hash, entry.run_report_hash))
        for parent_hash in entry.parent_hashes:
            # Reverse-citation index: only populate edges where the parent is itself an entry.
            if self._row_exists(parent_hash):
                self._conn.execute(INSERT_CITATION_SQL, (parent_hash, entry.provenance_hash))

    # 6. Emit telemetry event (registered name per §3.2).
    telemetry.emit("factory.ledger.entry_inserted",
                   {"entry_hash": entry.provenance_hash,
                    "hypothesis_id": entry.hypothesis_id,
                    "result": entry.result.value,
                    "cycle_id": self._cycle_id})

    return entry.provenance_hash
```

If step 5 raises `OperationalError`, the JSON file from step 4 is left on disk. A subsequent retry of `insert_entry` with the same artifact is idempotent and will repair the row. A `restore` from JSONL also rebuilds from the file. Orphaned files are not deleted automatically; they show up cleanly in `ledger verify --orphans`.

### 5.2 Read + verify flow

```python
def get_by_hash(self, entry_hash: ArtifactHash) -> EvidenceLedgerEntry:
    row = self._conn.execute(SELECT_ENTRY_SQL, (entry_hash,)).fetchone()
    if row is None:
        raise EntryNotFound(entry_hash)
    if row["is_stale"] and not self._allow_stale:
        raise DowngradedDueToStaleness(entry_hash)

    artifact_path = self._artifact_root / row["json_path"]
    entry = EvidenceLedgerEntry.from_json(artifact_path.read_bytes())

    if self._verify_on_read:
        recomputed = entry.compute_hash()
        if recomputed != entry.provenance_hash:
            raise LedgerCorruption(f"hash mismatch: stored={entry.provenance_hash} "
                                   f"recomputed={recomputed}")
        if recomputed != entry_hash:
            raise LedgerCorruption(f"row points to {entry_hash} but file hashes to {recomputed}")

    return entry
```

Trigger state and stale flag are *not* part of the returned artifact (they live outside the hash). Callers that need trigger state use `query(...)` which joins `entries` and `relitigate_triggers`, or call `evaluate_triggers` to refresh.

### 5.3 Atomicity across SQLite + filesystem

Phase A treats the JSON file as the source of truth, the row as the index. The atomicity contract:

- **Forward direction (file before row):** `_write_artifact_json` uses atomic temp-write + `os.replace`. Then SQLite WAL commits the row group in one transaction. If the SQLite commit fails, the file is on disk but no row; the next retry inserts cleanly (idempotent on hash). If the process crashes between file write and SQLite commit, recovery is to re-run `insert_entry`.
- **No partial rows:** Step 5 is a single `with self._conn:` block. Either every related row across five tables lands, or none do.
- **No stale rows:** A row whose JSON file vanished is detected by `verify(deep=True)` and surfaced. Reads that need the JSON (every default read) raise `EntryNotFound` if the file is missing.
- **No multi-cycle writes to the same entry:** Per-cycle isolation (§5.4) plus immutability (artifacts have content hashes) plus idempotency makes this safe.

This deliberately avoids two-phase commit: SQLite is the easier rollback target, the JSON file is the harder one, so we order writes to make the file the "win or do nothing" side.

### 5.4 Concurrency model

Phase A runs one cycle at a time. Each cycle constructs a `Ledger` with its own SQLite connection. WAL mode lets read-only callers (a UI server, the surrogate's training loop, a manual `ledger query` invocation) open separate read connections concurrently with the writer; the writer holds a single connection.

Rules:

1. There is exactly one writer connection at any moment. The state machine (spec 003) is responsible for that singleton.
2. Read connections open with `?mode=ro&immutable=0` URI and never call write methods. The library refuses write calls from a read-only handle (checked via `PRAGMA query_only`).
3. The writer's SQLite connection lives for the duration of the cycle and is closed on `Ledger.close()` or `__exit__`.
4. No module other than `factory.ledger` opens the SQLite file directly. Boundary enforced by `import-linter` (ARCHITECTURE.md §1.7).

### 5.5 Trigger evaluation

Each `RelitigationTrigger` carries a `check_fn` field whose value is a dotted Python path (e.g., `factory.ledger.triggers.simulator_version_changed`). Resolved at evaluation time, never at insert. `evaluate_triggers`:

```python
def evaluate_triggers(self, entry_hashes=None):
    rows = self._select_triggers(entry_hashes)
    reports = []
    for r in rows:
        try:
            fn = self._resolve_dotted(r["check_fn"])
            new_state = bool(fn(entry_hash=r["entry_hash"],
                                cycle_id=self._cycle_id,
                                artifact_root=self._artifact_root))
            err = None
        except Exception as e:
            new_state = False        # do NOT auto-flag; preserve previous state value below
            err = f"{type(e).__name__}: {e}"

        # Only persist `new_state` when the check succeeded; on error, keep prior state.
        persisted_state = r["currently_satisfied"] if err else new_state

        self._conn.execute(UPDATE_TRIGGER_SQL,
                           (datetime.utcnow().isoformat(),
                            int(persisted_state), err,
                            r["entry_hash"], r["trigger_index"]))
        reports.append(TriggerEvaluationReport(
            entry_hash=r["entry_hash"],
            trigger_index=r["trigger_index"],
            condition=r["condition"],
            previous_state=bool(r["currently_satisfied"]),
            new_state=persisted_state,
            error=err,
        ))
        if err:
            telemetry.emit("factory.ledger.trigger_check_failed",
                           {"entry_hash": r["entry_hash"], "trigger_index": r["trigger_index"],
                            "check_fn": r["check_fn"], "error": err})

    # Single summary event at the end of the batch (registered name per §3.2).
    telemetry.emit("factory.ledger.evaluate_triggers_complete",
                   {"evaluated_count": len(reports),
                    "failed_count": sum(1 for r in reports if r.error is not None),
                    "flipped_to_true_count": sum(
                        1 for r in reports if r.error is None and not r.previous_state and r.new_state
                    ),
                    "cycle_id": self._cycle_id})
    return reports
```

Built-in `check_fn`s in `factory/ledger/triggers.py` for Phase A:

- `simulator_version_changed(entry_hash, ...)` — true if the simulator referenced in the entry's `ProvenanceBlock.simulator_version` differs from the catalog's current version.
- `container_sha_changed(...)` — true if `container_sha` differs.
- `surrogate_retrained_after(entry_hash, ...)` — true if the spec 010 surrogate has a newer training timestamp than the entry's `created_at`.
- `domain_scope_expanded(...)` — true if the active `DomainScope` now allows a simulator capable of cross-validating this entry's observable.

Failures of `check_fn` are non-fatal at the ledger layer. They are visible to the state machine and to C5 via `evaluate_triggers` reports and via the `ledger.trigger_check_failed` telemetry event. A trigger that fails consistently is an actionable item for human review, not a reason to mistrust the entry itself.

### 5.6 The C5 audit query path — defense against internal hallucination compounding

This is the section that earns the spec its keep. SPEC §10.4 names *internal hallucination compounding* as a top failure mode: a false internal finding shapes later hypotheses, then is "confirmed" by downstream cycles. Two queries front this defense.

#### 5.6.1 `top_cited_entries(k, min_uncertainty)`

Ranks entries by how often their hash appears as a `parent_hash` on downstream artifacts. The reverse index `entry_citations` makes this an O(k log N) SQL query:

```sql
SELECT e.entry_hash,
       e.hypothesis_id,
       COUNT(c.citing_hash)         AS citation_count,
       MAX(child.primary_uncertainty) AS max_downstream_uncertainty,
       e.is_stale
  FROM entries        AS e
  JOIN entry_citations AS c    ON c.cited_hash = e.entry_hash
  JOIN entries        AS child ON child.entry_hash = c.citing_hash
 WHERE e.is_stale = 0
   AND e.primary_uncertainty >= :min_uncertainty
 GROUP BY e.entry_hash
 ORDER BY citation_count DESC
 LIMIT :k;
```

The C5 council receives this list each weekly cadence and re-audits the top entries: it re-reads the artifact, re-runs `verify(deep=True)`, and may issue a fresh deliberation on whether the entry should be marked stale.

#### 5.6.2 `high_uncertainty_with_dependents(uncertainty_threshold, min_dependents)`

Surfaces the second front: entries that are *both* high-uncertainty *and* already cited downstream. These are entries the factory is about to compound on:

```sql
SELECT e.entry_hash,
       e.hypothesis_id,
       e.primary_uncertainty,
       COUNT(c.citing_hash) AS downstream_dependent_count,
       e.is_stale
  FROM entries        AS e
  LEFT JOIN entry_citations AS c ON c.cited_hash = e.entry_hash
 WHERE e.is_stale = 0
   AND e.primary_uncertainty >= :uncertainty_threshold
 GROUP BY e.entry_hash
HAVING COUNT(c.citing_hash) >= :min_dependents
 ORDER BY (e.primary_uncertainty * COUNT(c.citing_hash)) DESC;
```

Together these two queries define the C5 shortlist: high-leverage entries (top cited) plus high-risk entries (high uncertainty with already-existing dependents). They are the smallest set whose correctness most affects the factory's belief state.

#### 5.6.3 `top_high_surprise_with_dependents(k)` — surprise × citation audit (FIX_PLAN §26.4)

The third audit path closes the loop with the Strategy Archive (`specs/016-strategy-archive.md`). The archive writes `surprise_bits` per cycle via `Ledger.update_surprise(entry_hash, bits)`. C5 then queries the top-K entries by the composite `surprise_bits × downstream_citation_count`. Entries whose `surprise_bits IS NULL` sort **last** so the audit always promotes scored surprising findings ahead of unscored ones:

```sql
SELECT e.entry_hash,
       e.hypothesis_id,
       e.surprise_bits,
       COALESCE(COUNT(c.citing_hash), 0)                          AS downstream_citation_count,
       COALESCE(e.surprise_bits * COUNT(c.citing_hash), 0.0)      AS composite_score,
       e.is_stale
  FROM entries        AS e
  LEFT JOIN entry_citations AS c ON c.cited_hash = e.entry_hash
 WHERE e.is_stale = 0
 GROUP BY e.entry_hash
 ORDER BY (e.surprise_bits IS NULL) ASC,    -- NULL last
          composite_score DESC
 LIMIT :k;
```

C5 program-direction (spec 003 §5.5) consumes this list alongside `top_cited_entries` and `high_uncertainty_with_dependents`. High-surprise findings cited downstream are exactly the entries whose error would compound widest *and* whose Bayesian update was the most informative — the strongest signal both for re-audit and for `DomainScope` change deliberation.

### 5.7 Provenance summary scalar

`primary_uncertainty` indexes `entry.uncertainty` which is a `dict[str, ...]` keyed by metric. Phase A rule: the summary is the maximum half-width of any 1σ confidence interval reported on the entry's `pre_registered_metric` (pulled from the originating `HypothesisSpec`). If the entry's `uncertainty` dict is empty or malformed, `primary_uncertainty` is stored as `NULL` and queries that filter on it skip the row. The full uncertainty object is always available via the artifact JSON; the scalar exists only for indexed filtering.

### 5.8 Export / restore

`export(dst, format="jsonl")` writes one JSON object per line. Each object contains the full `EvidenceLedgerEntry` (read back through `get_by_hash` so it goes through verification), plus a small `_ledger_state` sidecar object holding the mutable trigger state and the stale-flag fields. The dump is sorted by `created_at` for determinism.

`restore(src, format="jsonl")` refuses to run if `entries` is non-empty (it would mix histories). For each line: re-validate the artifact, re-verify the hash, write the JSON file (recreating `runs/<cycle-id>/artifacts/` as needed), insert the row group, and re-establish trigger state and stale flag from `_ledger_state`. After restore, run `verify(deep=False)` on every entry and `verify(deep=True)` on a configurable sample (default 5%) — full deep-verify would re-walk every referenced council verdict and report and is expensive.

### 5.9 Strategy Archive integration (FIX_PLAN §26.4)

`specs/016-strategy-archive.md` writes `surprise_bits` onto existing entries via `Ledger.update_surprise(entry_hash, bits)` after attributing Bayesian surprise to a cycle. The write is SQLite-only (§4.2): it does **not** change the entry's `provenance_hash` because surprise lives outside the immutable artifact. `top_high_surprise_with_dependents` (§5.6.3) is the C5 read path that consumes these scores. The `_ledger_state` sidecar in `export` (§5.8) carries `surprise_bits` so restore is round-trippable.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `LedgerWriteFailed(LedgerError)` | SQLite `OperationalError` on insert/update (locked, disk full, read-only mount) | State machine pauses the cycle; operator inspects the underlying SQLite message; retry once after addressing the cause. JSON-file write may have already succeeded — `insert_entry` is idempotent on retry. |
| `LedgerCorruption(LedgerError)` | `provenance_hash` recomputation does not match either the artifact's own `provenance_hash` or the row's `entry_hash` | Halt the cycle; mark the entry stale via direct SQL only via the `mark_stale` API path; quarantine the artifact JSON; surface to C5 immediately; do not feed into surrogate training. |
| `EntryNotFound(LedgerError)` | Caller queries a hash with no row, or the referenced JSON file is missing | Return the typed error; caller (usually state machine G0) treats the hypothesis as fresh, not as ledger-trusted. |
| `RelitigateCheckFailed(LedgerError)` | A trigger's `check_fn` could not be imported or raised | Trigger row's `last_error` is set; `currently_satisfied` keeps its previous value (does not flip to True or to False). The state machine MUST treat "error" as "not currently satisfied" for the purpose of G0 re-litigation decisions. |
| `DowngradedDueToStaleness(LedgerError)` | Default-mode read hits an entry with `is_stale=1` | Return typed error; consumers (spec 010 surrogate, spec 011 RAG writer) must skip stale entries. State machine routes the hypothesis through fresh G2/G3 if it needs the data. |
| `LedgerSchemaMismatch(LedgerError)` | `schema_meta.schema_version != "1"` at open | Refuse to open. Phase A pins schema; this is a Phase B upgrade trigger, handled by `ledger restore` from an export plus the new code. |
| `ArtifactValidationError` (from spec 002, re-raised) | Artifact JSON on disk no longer matches `EvidenceLedgerEntry` schema (e.g., software downgrade) | Halt; same quarantine treatment as `LedgerCorruption`. |
| `OperationalError` not classified above | Any other SQLite error | Wrap in `LedgerWriteFailed` with the original message preserved. |

## 7. Testing

**Mock-mode unit tests** (`factory/ledger/tests/`, all must pass in CI without external services):

- `test_ledger_typical_usage.py` — REQUIRED. Open in-memory DB; insert a fixture entry; round-trip through `get_by_hash`; verify hash; query with one filter; close.
- `test_insert_idempotent.py` — inserting the same entry twice produces no duplicate row and no exception.
- `test_insert_writes_json_and_row_together.py` — confirm both artifact JSON and SQLite row exist after `insert_entry`; confirm that a synthetic SQLite-commit failure (monkey-patched) leaves the JSON file on disk and that a re-insert recovers cleanly.
- `test_provenance_verification.py` — corrupt the artifact JSON on disk after insert; `get_by_hash` raises `LedgerCorruption`.
- `test_deep_verify_walks_refs.py` — delete a referenced `CouncilVerdict` JSON; `verify(deep=True)` raises.
- `test_query_filters.py` — every `LedgerQuery` field exercised at least once; `include_stale=False` excludes stale rows; ordering honored.
- `test_top_cited_and_high_uncertainty.py` — build a chain of 10 entries with synthetic citation edges and uncertainty values; assert audit-query outputs match expected ranking. **This is the C5 audit-path test; it MUST stay green.**
- `test_relitigate_status_does_not_change_hash.py` — `update_relitigate_status` toggles a trigger; re-read the entry; `provenance_hash` unchanged.
- `test_evaluate_triggers_built_ins.py` — wire each built-in `check_fn` against a stub catalog/surrogate; confirm true/false outcomes and that `last_evaluated_at` advances.
- `test_evaluate_triggers_failure_preserves_state.py` — a `check_fn` that raises does NOT flip `currently_satisfied`; `last_error` is set; the next successful run clears `last_error`.
- `test_mark_stale_blocks_default_reads.py` — `mark_stale` then `get_by_hash` (default mode) raises `DowngradedDueToStaleness`; `query(include_stale=True)` returns the row.
- `test_export_restore_roundtrip.py` — insert N entries; `export` to a temp JSONL; open a fresh DB; `restore` from the JSONL; assert every entry hash and trigger state matches. Determinism: re-export from the restored DB; byte-identical to the first export.
- `test_concurrency_single_writer.py` — open one writer connection plus three read-only connections; the reads run concurrently with a stream of writes; no exceptions, no missed rows.
- `test_schema_version_pin.py` — set `schema_meta.schema_version` to "0"; open raises `LedgerSchemaMismatch`.
- `test_orphan_json_detection.py` — write an artifact JSON without a row; `verify --orphans` lists it.
- `test_no_direct_sqlite_from_other_modules.py` — `import-linter` (or pytest equivalent) confirms no `factory.*` module other than `factory.ledger` imports `sqlite3` against the ledger DB.
- `test_reader_query_observable.py` — instantiate `EvidenceLedgerReader(Ledger(...))`; seed fixtures with two observables and one stale entry; assert `query_observable(TrainingDataQuery(observable="X"))` returns the non-stale rows for X only and carries the correct `provenance_hash` on every row. **This is spec 010's contract test; it MUST stay green.**
- `test_registered_events_match_emits.py` — collect every `telemetry.emit(...)` literal name from `factory/ledger/`; assert the set equals `REGISTERED_EVENTS` from `events.py`. Guards against drift between §3.2 and the implementation.

**Live-mode tests** (`@pytest.mark.live`, gated):

- `test_live_disk_durability.py` — insert N entries, simulate `os._exit(0)` during a write batch, reopen; entries committed before the crash survive; no partial rows.
- `test_live_wal_concurrency.py` — write N entries while another process runs continuous queries against the same DB file; no `database is locked` errors at `busy_timeout=5000`.

**Manual verification step** (one-time, documented in runbook):

- Insert 100 synthetic entries; run `top_cited_entries(k=10)` and confirm the ranking visually matches the citation graph drawn from the test fixture.

## 8. Performance & Budget

- `insert_entry` typical size (entry JSON ≤ 50 KB): < 10 ms in WAL mode on local SSD. Hard cap target: < 50 ms p99.
- `get_by_hash` with `verify_on_read=True`: < 5 ms (single primary-key lookup + file read + SHA-256).
- `query` with three filters and `limit=100`: < 20 ms over a DB of ≤ 100k entries (the Phase A working size).
- `top_cited_entries(k=20)`: < 50 ms over the Phase A working size, given the `idx_citations_cited` index.
- `evaluate_triggers` over all entries: bounded by user-provided `check_fn` cost; the ledger overhead is < 1 ms per trigger.
- `export` to JSONL: streaming; bounded by disk throughput.
- DB size: ≤ 200 MB for ≤ 100k entries (rows are small; the JSON files dominate cycle disk usage).
- No external calls; all I/O local.

## 9. Open Questions

- **`primary_uncertainty` summary rule.** The Phase A rule (max 1σ half-width on the pre-registered metric) is one summary; some entries may want a different scalar (e.g., max half-width across all reported metrics). Tune empirically during PRD-001 acceptance.
- **Citation-graph definition.** Currently `entry_citations` captures only direct `parent_hashes` that resolve to other entries. Should it also include verdicts that cite a prior entry by reference inside their `context`? Likely yes in Phase B; not in Phase A.
- **Per-trigger telemetry retention.** `last_error` is overwritten on every evaluation. A separate audit table that retains the last K failures per trigger would help C5 detect drift. Deferred.
- **Cross-cycle DB sharding.** Phase A uses one DB file for all cycles. If the DB grows beyond Phase A bounds, sharding by quarter (`ledger-2026Q3.db`) is a Phase B option that does not break the public API.
- **Stale-flag semantics under re-litigation.** When a re-litigated entry passes, should the older entry be auto-flagged stale or only manually? Phase A leaves it manual to keep the audit trail visible.

## 10. TODO Checklist

- [ ] Scaffold `factory/ledger/` from the canonical module template (`api.py`, `types.py`, `cli.py`, `mock.py`, `errors.py`, `triggers.py`, `events.py`, `fixtures/`, `tests/`, `README.md`).
- [ ] Author `factory/ledger/events.py` registering exactly the three event names from §3.2: `factory.ledger.entry_inserted`, `factory.ledger.trigger_check_failed`, `factory.ledger.evaluate_triggers_complete`.
- [ ] Implement `EvidenceLedgerReader` skeleton in `factory/ledger/api.py` (composes a `Ledger`; exposes only `query_observable`); export from package init as `from factory.ledger import Ledger, EvidenceLedgerReader`.
- [ ] Verify the SQL DDL in `factory/ledger/schema.sql` contains **no `budget_ledger`** table (per FIX_PLAN §4 — Phase A budget is JSON-only).
- [ ] Implement `Ledger.__init__` with WAL PRAGMA setup, schema bootstrap, schema-version pin.
- [ ] Author the SQL DDL block (§4.1) into `factory/ledger/schema.sql`; load on first open.
- [ ] Implement `insert_entry` with file-before-row ordering and the five-table transaction (§5.1).
- [ ] Implement `get_by_hash` and `get_by_id` with verify-on-read (§5.2).
- [ ] Implement `query` with the full `LedgerQuery` filter set.
- [ ] Implement `update_relitigate_status` and `mark_stale`.
- [ ] Implement audit queries `top_cited_entries`, `high_uncertainty_with_dependents`, `flagged_stale_entries` (§5.6).
- [ ] Implement `verify` (shallow) and `verify(deep=True)` walking council-verdict and run-report refs.
- [ ] Implement `evaluate_triggers` with per-trigger error isolation (§5.5).
- [ ] Implement the four Phase A built-in `check_fn`s in `factory/ledger/triggers.py`.
- [ ] Implement `export` (deterministic JSONL) and `restore` (refuses non-empty DB).
- [ ] Implement `__enter__` / `__exit__` / `close`.
- [ ] Write `factory/ledger/mock.py` returning an in-memory ledger pre-seeded from `fixtures/seed_entries.jsonl`.
- [ ] Author `factory/ledger/cli.py` with `insert`, `get`, `query`, `audit`, `verify`, `export`, `restore`, `evaluate-triggers`, `mark-stale` subcommands.
- [ ] Author ≥ 6 fixture entries in `factory/ledger/fixtures/` spanning passed / falsified / intractable / inconclusive, with and without dissent, with and without `relitigate_if`.
- [ ] Write all 16 mock-mode tests listed in §7; all pass on a fresh checkout.
- [ ] Write the 2 live-mode tests behind `@pytest.mark.live`.
- [ ] Add `import-linter` rule forbidding `sqlite3` imports outside `factory.ledger`.
- [ ] Add CI step running `python -m factory.ledger query --mock-mode` against the in-memory fixture DB.
- [ ] Write `factory/ledger/README.md` (≤ 1 page, mock-mode example + the one diagram of file-vs-row source-of-truth).
- [ ] Write `docs/runbooks/ledger-audit.md` covering: how to read a top-cited audit list, how to triage `LedgerCorruption`, how to use `export` / `restore` for backup, how to spot orphaned JSON files, what each built-in `check_fn` looks for.
- [ ] Verify `mypy --strict factory/ledger/` passes.
- [ ] Verify `python -m factory.ledger query --result passed --mock-mode` works on a fresh checkout.
- [ ] Add the `surprise_bits REAL` (nullable) column on the `entries` table per §4.1, plus the `idx_entries_surprise` index, per FIX_PLAN §26.4. Phase A schema pin: include the column and index from the first schema bootstrap — there is no migration path.
- [ ] Implement `Ledger.update_surprise(entry_hash: ArtifactHash, bits: float) -> None` per §3 / §5.9; called by `specs/016-strategy-archive.md` after attributing Bayesian surprise. Raises `EntryNotFound` if no row. Does not change `provenance_hash` (surprise is SQLite-only mutable state, like trigger state and stale flag — §4.2).
- [ ] Implement the C5 audit query `Ledger.top_high_surprise_with_dependents(k: int) -> list[AuditHighSurprise]` per §3 / §5.6.3 (FIX_PLAN §26.4). NULL `surprise_bits` sort **last** in the result. Consumed by spec 003 §5.5 C5 program-direction.
- [ ] Extend `export` / `restore` (§5.8) to round-trip `surprise_bits` in the `_ledger_state` sidecar so audit history survives restore.
- [ ] Add `AuditHighSurprise` to `factory/ledger/types.py` per §3.
- [ ] PRD-001 acceptance: after one complete cycle, the ledger contains one entry, `verify(deep=True)` succeeds, `top_cited_entries` is empty (no downstream yet), `export` round-trips byte-identical.
