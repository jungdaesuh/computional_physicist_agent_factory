# Runbook: Ledger Audit

> What this covers: opening and querying the `EvidenceLedger`, running the C5 audit-mode shortlist of top-cited + high-uncertainty findings, verifying provenance chains for individual entries, evaluating `relitigate_if` triggers and forcing re-litigation, exporting the ledger to JSONL for offline analysis, restoring from backup, triaging `LedgerCorruption` and orphaned artifact JSONs, and the weekly C5 audit workflow that is the front-line defense against internal hallucination compounding (SPEC.md §10.4). · When to use: weekly C5 cadence; suspected compounding of a false internal finding; before any external publication (G6 gate); after a power loss or filesystem corruption event; whenever a downstream module (surrogate, RAG writer) reports an `EntryNotFound` or `DowngradedDueToStaleness` it cannot reconcile. · Estimated time: 20–40 minutes for a routine weekly C5 audit; 1–2 hours for a corruption postmortem or a deep provenance verification on a contentious finding.

---

## 1. Prerequisites

- **Ledger DB path.** Phase A default: `runs/ledger.db` (spec 012 §3 `Ledger.__init__`). Confirm the file is present and non-zero size; the sibling `runs/ledger.db-wal` and `runs/ledger.db-shm` files are normal WAL artifacts (never check them in, never delete them while the factory is writing).
- **Artifact root** at `runs/`. The JSON files referenced by every ledger row live under `runs/<cycle-id>/artifacts/<hash>.json`. The ledger row is the *index*; the JSON file is the source of truth (spec 012 §4.2). If the artifact root has been pruned, you have rows pointing into the void — the audit will surface that, but you cannot complete a deep verify.
- **Read-only access is enough for inspection.** The ledger CLI opens read-only by default; only `mark-stale`, `evaluate-triggers`, `restore`, and (Phase B) `insert` mutate. Spec 012 §5.4: a single writer connection lives in the state machine; read CLIs open with `?mode=ro&immutable=0`.
- **Awareness of the immutability contract.** Per spec 012 §1, entries are immutable once committed. Re-litigation creates a *new* entry whose `parent_hashes` chains back. Stale-flagging and trigger-state changes live in sibling tables and do **not** alter the entry's `provenance_hash`.
- **C5 council operational** (for the weekly audit workflow). The audit-shortlist surfaces candidates; the actual re-audit decision is a C5 deliberation per spec 003 §5.5. If the council library is down, you can still surface the shortlist and quarantine entries via `mark-stale`; the deliberation step waits.
- **Backup discipline.** Before any operation that can lose data (`restore`, force-quarantine of multiple entries), take a fresh `export`. The ledger is small (≤200 MB for ≤100k entries per spec 012 §8); there is no excuse for skipping the backup.

---

## 2. Steps

### 2.1 Open the ledger and snapshot its current shape

```
python -m factory.ledger query --limit 0 --format summary
```

`--limit 0` returns no rows but the summary header reports: total entries, breakdown by result (`passed` / `falsified` / `intractable` / `inconclusive`), stale count, count with `has_dissent_flag=1`, and the time range of `created_at`. (Per FIX_PLAN §9.2, the per-module `python -m factory.ledger` CLI exposes `query`, `audit`, `export`, `verify-chain`, and `evaluate-triggers`. The operator-CLI surface in spec 015 only exposes `factory inspect` for cross-ledger projections.)

If the summary errors with `LedgerSchemaMismatch`, the DB on disk is from a different schema version than the code expects. Stop. Treat as a phase-upgrade event: see Step 2.10 (export/restore migration path).

### 2.2 Routine query patterns

```
# Recent falsifications, one cycle each
python -m factory.ledger query --result falsified --limit 20 --order created_at_desc

# All entries from a specific simulator
python -m factory.ledger query --simulator-id vmecpp --limit 50

# All entries with preserved dissent (C2 qualified or C4 split)
python -m factory.ledger query --has-dissent true --limit 50

# Stale entries only (default queries exclude them)
python -m factory.ledger query --include-stale true --only-stale --limit 100
```

Spec 012 §3 `LedgerQuery` filters AND-combine; `include_stale=False` is the default. Stale rows are excluded by default precisely so a downstream consumer (the surrogate, the RAG writer) never accidentally re-amplifies a quarantined finding.

To pipe rows into another tool, use `--format jsonl`:

```
python -m factory.ledger query --result passed --created-after 2026-04-01 --format jsonl \
  | jq -c '{hypothesis_id, entry_hash, provenance: .provenance | {code_hash, env_hash, simulator_version}}'
```

### 2.3 Toggle audit mode for the C5 shortlist

The audit mode surfaces the two shortlists from spec 012 §5.6 that together define the C5 re-audit set:

```
python -m factory.ledger audit --top-cited 20 --min-uncertainty 0.1
python -m factory.ledger audit --high-uncertainty 0.3 --min-dependents 1
```

The first list ranks entries by **downstream citation count** — how many *other* ledger entries name this one in their `parent_hashes`. The reverse-citation index `entry_citations` makes this a fast SQL query. These are the entries whose error, if any, would compound the most.

The second list ranks entries that are **both high-uncertainty and already cited at least once**. Per spec 012 §5.6.2:

```sql
SELECT e.entry_hash, e.hypothesis_id, e.primary_uncertainty,
       COUNT(c.citing_hash) AS downstream_dependent_count, e.is_stale
  FROM entries AS e
  LEFT JOIN entry_citations AS c ON c.cited_hash = e.entry_hash
 WHERE e.is_stale = 0
   AND e.primary_uncertainty >= :uncertainty_threshold
 GROUP BY e.entry_hash
HAVING COUNT(c.citing_hash) >= :min_dependents
 ORDER BY (e.primary_uncertainty * COUNT(c.citing_hash)) DESC;
```

The product `uncertainty × dependents` is the prioritisation key: high uncertainty alone is acceptable if nothing depends on it yet; existing dependents alone are acceptable if uncertainty is low; the intersection is where compounding happens.

Combine both lists into a single audit batch:

```
python -m factory.ledger audit --combined --top-cited 20 --high-uncertainty 0.3 --min-dependents 1 \
  --format jsonl > /tmp/c5_audit_batch.jsonl
wc -l /tmp/c5_audit_batch.jsonl
```

Inspect the batch before feeding it to C5: prune obvious dupes, confirm the time window makes sense, and reject any entries that are themselves *outputs of a previous audit* (re-auditing a re-audit is a sign the cadence is too tight).

### 2.4 Verify the provenance chain for a specific entry

When a downstream module flags a suspect finding, verify the chain end-to-end:

```
python -m factory.ledger get --hash <entry-hash> --verify deep
```

Spec 012 §3 `verify(deep=True)` (also exposed as `python -m factory.ledger verify --hash <h> --deep`):
1. Recomputes the entry's `provenance_hash` from the JSON file and compares with the row's `entry_hash` and the artifact's own `provenance_hash`. Any mismatch → `LedgerCorruption`.
2. Walks `council_verdict_hashes` and confirms each referenced council-verdict JSON exists under `artifact_root` and has its expected hash.
3. Walks `run_report_hash` (if present) and confirms the report JSON exists with its expected hash.
4. Walks `parent_hashes` and confirms each parent entry is queryable in the ledger; missing parents indicate either an entry from before the ledger started (legitimate Phase A) or a deleted ancestor (Phase B audit concern).

If all four checks pass, the entry's content is exactly what was committed. Any failure is `LedgerCorruption` — proceed to Step 2.9.

For a *human-readable* chain dump suitable for a C5 deliberation packet:

```
python -m factory.ledger trace --hash <entry-hash> --depth 3 --format markdown > /tmp/trace.md
```

`trace` ([TBD-impl] — `trace` is not enumerated in spec 012 §3 or FIX_PLAN §9.2's `python -m factory.ledger` subcommand list; the underlying graph is available via the `entry_citations` table) walks the parent chain up to `depth` ancestors and the dependent chain forward by the same depth, producing a markdown document with each entry's `provenance_hash`, `result`, `primary_uncertainty`, key council verdicts, and a single-line summary.

### 2.5 Evaluate `relitigate_if` triggers

`RelitigationTrigger` rows live in `relitigate_triggers` (spec 012 §4.1) outside the immutable artifact (mutable trigger state would otherwise change the entry's hash). To re-evaluate every trigger across the ledger:

```
python -m factory.ledger evaluate-triggers --format jsonl > /tmp/trigger_reports.jsonl
jq -c 'select(.new_state == true and .previous_state == false)' /tmp/trigger_reports.jsonl
```

The second command surfaces newly-satisfied triggers — these are the entries the state machine should consider re-running. Per spec 012 §5.5, the four Phase A built-in check functions are:

- `simulator_version_changed` — entry's `ProvenanceBlock.simulator_version` differs from the catalog's current version. Triggered when a catalog entry is updated.
- `container_sha_changed` — entry's `container_sha` differs from current. Triggered when a container is rebuilt.
- `surrogate_retrained_after` — surrogate has a newer training timestamp than entry's `created_at`. Triggered when surrogate is retrained on a larger dataset.
- `domain_scope_expanded` — `DomainScope` now allows a simulator capable of cross-validating this entry. Triggered when C5 expands the scope.

A trigger that fails to evaluate (raised an exception in its `check_fn`) is captured in `relitigate_triggers.last_error`; spec 012 §6 explicitly says the state machine MUST treat trigger-evaluation errors as "not currently satisfied" — failures do not auto-flag entries.

To force re-litigation for a *specific* entry whose trigger is newly satisfied:

```
python -m factory.state_machine run-cycle --hypothesis-id <id> --relitigate-from <entry-hash>
```

(Per FIX_PLAN §9.2, the per-module state-machine CLI exposes `run-cycle`, `replay`, `inspect`, `step`, `submit-gaps`, `run-gate`, `validate-routes`, and `force-terminate`. There is no separate `relitigate` subcommand; the path runs through `run-cycle --relitigate-from`.) The state machine then re-runs the cycle from G0, and the new EvidenceLedgerEntry will list the prior entry in its `parent_hashes`.

### 2.6 Export the ledger for offline analysis

```
python -m factory.ledger export --dst /tmp/ledger-$(date -u +%FT%TZ).jsonl --format jsonl
gzip /tmp/ledger-*.jsonl
```

Spec 012 §5.8 guarantees the JSONL dump is *deterministic* given the same DB state — entries are sorted by `created_at`, the mutable trigger state and stale flag are written in a `_ledger_state` sidecar object, and a re-export from a freshly restored DB is byte-identical to the original. Use this property to validate restores.

Common offline-analysis patterns:

```
# Distribution of results
jq -r '.result' ledger.jsonl | sort | uniq -c

# Spend by simulator version
jq -r '"\(.provenance.simulator_id) \(.provenance.simulator_version)"' ledger.jsonl | sort | uniq -c

# Citation count distribution
jq -c '{entry_hash, parent_count: (.parent_hashes | length)}' ledger.jsonl \
  | jq -s 'group_by(.parent_count) | map({pc: .[0].parent_count, n: length})'
```

The export does **not** include the underlying artifact JSON contents (council verdicts, run reports) — only the EvidenceLedgerEntry artifact for each row. For a complete offline bundle, also archive the relevant `runs/<cycle-id>/artifacts/` directories.

### 2.7 Restore from backup

`restore` (spec 012 §3, §5.8) refuses to run against a non-empty DB:

```
# Move the suspect DB aside
mv runs/ledger.db runs/ledger.db.suspect.$(date -u +%FT%TZ)
mv runs/ledger.db-wal runs/ledger.db-wal.suspect.$(date -u +%FT%TZ) 2>/dev/null
mv runs/ledger.db-shm runs/ledger.db-shm.suspect.$(date -u +%FT%TZ) 2>/dev/null

# Restore a fresh DB from the JSONL dump
python -m factory.ledger restore --src /tmp/ledger-<timestamp>.jsonl --format jsonl
```

The restore:
1. Opens a fresh empty DB.
2. For each line in the JSONL: revalidates the artifact, re-verifies the hash, recreates the artifact JSON under `runs/<cycle-id>/artifacts/` if it is missing, inserts the row group across all five tables, and re-establishes trigger state plus the stale flag from the `_ledger_state` sidecar.
3. After all inserts, runs `verify(deep=False)` on every entry and `verify(deep=True)` on a configurable sample (default 5%). A failure halts the restore and leaves the partial DB in place for inspection.

After restore, take a fresh export and confirm byte-identical to the source dump:

```
python -m factory.ledger export --dst /tmp/post_restore.jsonl --format jsonl
diff /tmp/ledger-<original>.jsonl /tmp/post_restore.jsonl
```

`diff` should be empty.

### 2.8 Detect orphaned artifact JSONs

Per spec 012 §5.1, the insert flow writes the JSON file *first*, then commits the SQLite row group. If the process dies between the two writes, the JSON is on disk but no row references it. `verify` surfaces this:

```
python -m factory.ledger verify --orphans --format text
```

Each orphan is a JSON under `runs/<cycle-id>/artifacts/` whose hash does not appear as `entry_hash` in `entries`. Responses:

- **Recoverable orphan**: the JSON validates as an `EvidenceLedgerEntry` and the prior insert attempt was definitely intended to commit. Re-insert via `python -m factory.ledger insert --from <orphan-path>`. Idempotent on hash (spec 012 §5.1 step 2).
- **Stale orphan**: a developer hand-wrote a JSON for testing, or a partial cycle was force-killed before the entry was meant to be persistent. Delete after operator confirmation; never delete in bulk without listing.

### 2.9 Quarantine a poisoned entry

When a deep verify failure surfaces an entry whose stored hash does not match its content (or its referenced JSON has changed under it), treat the entry as poisoned. Per spec 012 §6:

```
python -m factory.ledger mark-stale --hash <entry-hash> \
  --reason "<short reason linked to investigation>" \
  --marked-by "<actor>"
```

([TBD-impl] — `mark-stale` is not enumerated in FIX_PLAN §9.2's per-module `factory.ledger` subcommand list (`query`, `audit`, `export`, `verify-chain`, `evaluate-triggers`). The underlying API is `Ledger.mark_stale(...)` per spec 012 §3.)

`mark_stale` (spec 012 §3) flips `is_stale=1` and records `stale_reason`, `stale_marked_by`, `stale_marked_at`. Default-mode queries thereafter raise `DowngradedDueToStaleness` for direct gets and silently exclude the row from `query()`. The surrogate (spec 010) and RAG writer (spec 011) MUST honour the stale flag and skip these entries during retrieval.

A stale-flag is **not** a delete. The row remains; the artifact JSON remains. The entire history is preserved for audit. Reversing a stale-flag is permitted only with a documented rationale:

```
python -m factory.ledger mark-stale --hash <entry-hash> --clear \
  --reason "Re-verified after <fix>; provenance now matches"
```

### 2.10 Schema migration via export/restore

Phase A pins the schema (spec 012 §4.1 `schema_meta.schema_version = "1"`). When Phase B upgrades the schema, the migration path is:

1. Export the current DB to JSONL.
2. Upgrade the code to the new schema version.
3. Restore from the JSONL into a fresh DB. The new code populates new columns from the artifact JSON (which is the source of truth, unchanged across the migration).
4. Take a fresh export and archive both the old and new dumps. The old dump is the rollback.

The migration deliberately routes through the *artifact JSON* (not the SQLite row) because the JSON is the canonical content; the SQLite row is a projection. Adding a column to the projection is a code change plus a re-restore, not a schema migration in the database-management sense.

### 2.11 Weekly C5 audit workflow

This is the codified flow the C5 program-direction council runs every cadence (default weekly per spec 003 §5.5). It is the front-line defense per SPEC.md §10.4. Run the steps in order.

#### Sub-step A — Take a fresh export (5 min)

```
python -m factory.ledger export --dst runs/_audit/$(date -u +%F)/ledger.jsonl --format jsonl
```

Always export first. The audit may produce stale-flags; if the rationale for any flag turns out to be wrong, you want the pre-audit state archived.

#### Sub-step B — Generate the combined shortlist (5 min)

```
python -m factory.ledger audit --combined \
  --top-cited 20 \
  --high-uncertainty 0.3 \
  --min-dependents 1 \
  --format jsonl > runs/_audit/$(date -u +%F)/shortlist.jsonl
```

Inspect the shortlist length. Phase A target: 10–30 entries per audit. Below 10 means the ledger is too small to have meaningful compounding risk yet (continue, but expect few flags). Above 50 means either the thresholds are too loose (raise `--high-uncertainty`) or the factory's recent output is unusually dissent-heavy (note this in the audit packet and surface to C5 chairman as a separate signal).

#### Sub-step C — Verify provenance for every shortlisted entry (10 min)

```
jq -r '.entry_hash' runs/_audit/$(date -u +%F)/shortlist.jsonl \
  | while read h; do
      python -m factory.ledger verify --hash "$h" --deep --format json
    done > runs/_audit/$(date -u +%F)/verify.jsonl
```

Any `LedgerCorruption` from this batch is a P1 finding and short-circuits the rest of the audit: quarantine via Step 2.9, escalate to the operator on call. Do not feed corrupted entries into the C5 deliberation packet.

#### Sub-step D — Re-evaluate triggers (5 min)

```
python -m factory.ledger evaluate-triggers \
  --entry-hashes-from runs/_audit/$(date -u +%F)/shortlist.jsonl \
  --format jsonl > runs/_audit/$(date -u +%F)/triggers.jsonl
```

Newly-satisfied triggers (`previous_state=false`, `new_state=true`) are signals that the *external* environment has changed enough to warrant re-litigation. Per spec 012 §5.5, the four built-ins cover the canonical cases. Flag these for C5; the council may choose to re-litigate or to mark stale based on dissent.

#### Sub-step E — Assemble the C5 deliberation packet (5 min)

For each shortlisted entry, build a markdown trace (Step 2.4) and concatenate:

```
mkdir -p runs/_audit/$(date -u +%F)/packets/
jq -r '.entry_hash' runs/_audit/$(date -u +%F)/shortlist.jsonl \
  | while read h; do
      python -m factory.ledger trace --hash "$h" --depth 2 --format markdown \
        > "runs/_audit/$(date -u +%F)/packets/${h:0:12}.md"
    done
```

The packet is a self-contained read for the C5 council: each entry's content, its parents (what it cites), its dependents (what cites it), recent trigger evaluations, and the existing council verdicts attached. Spec 003 §5.5 step 2 names the document fields: top-cited findings, dissent-heavy verdicts, OOD-escalation rate, sycophancy report — produce those summaries separately.

#### Sub-step F — Run C5 deliberation (driven by spec 003's `C5Scheduler`)

```
python -m factory.council deliberate --council-id C5 \
  --context runs/_audit/$(date -u +%F)/ \
  --persona-set program_direction
```

The deliberation outputs a `CouncilVerdict` with preserved dissent. The chairman's decision can be:
- `approve` — apply scope changes (add/remove allowed_domains, etc.).
- `reject` — keep current scope; close the audit.
- `qualified` — flag specific entries for operator attention.

Spec 003 §5.5: C5 outcomes are written as `CouncilVerdict` to the Ledger but do not bind any per-cycle state. The audit is advisory at the per-entry level — *quarantines themselves* are applied via `mark-stale`, which the audit packet recommends and the operator (or chairman) confirms.

#### Sub-step G — Apply the audit decisions (5 min)

For each entry C5 recommends quarantining:

```
python -m factory.ledger mark-stale --hash <entry-hash> \
  --reason "C5 audit $(date -u +%F): <one-line rationale>" \
  --marked-by "C5:<chairman_model>"
```

For each entry C5 recommends re-litigating:

```
python -m factory.state_machine run-cycle --hypothesis-id <id> \
  --relitigate-from <entry-hash> \
  --reason "C5 audit $(date -u +%F): trigger=<which>"
```

#### Sub-step H — Archive the audit (2 min)

```
python -m factory.ledger export --dst runs/_audit/$(date -u +%F)/post_audit.jsonl --format jsonl
git -C runs/_audit add $(date -u +%F)
git -C runs/_audit commit -m "C5 audit $(date -u +%F)"
```

The pre-audit and post-audit exports together with the deliberation transcript form the full audit record. Spec 015's `runs/_control/events/` also captures the `mark-stale` and `relitigate` mutations as `FactoryControlEvent`s.

#### Sub-step I — Surface findings to the operator UI

The C5 deliberation verdict appears on screen 11 (Settings → C5 history) per UI_DESIGN.md. The operator reviews the audit at the next opportunity; nothing further is required unless C5 returns `qualified`, in which case the operator must explicitly acknowledge before the next cadence.

### 2.12 Pre-publication audit (G6 precursor)

Before any `factory approve <run-report-id>` for an external release, run a focused audit on the entries the RunReport cites:

```
python -m factory.ledger get --by-run-report <run-report-id> --format jsonl \
  | jq -r '.entry_hash' \
  | while read h; do
      python -m factory.ledger verify --hash "$h" --deep
    done
```

Any failure blocks G6: external publication of a finding whose provenance does not verify is exactly the failure mode SPEC.md §10.4 names. If verification passes, also run the audit-shortlist queries restricted to those entries — any of them appearing on either list is a signal the report depends on a high-leverage internal finding that has not been C5-audited recently.

---

## 3. Verification

After any audit pass, restore, or mass quarantine, verify the ledger is internally consistent.

1. **No orphans.**
   ```
   python -m factory.ledger verify --orphans
   ```
   Should report zero. Any orphan is either a recovery-by-re-insert candidate (Step 2.8) or a stale dev artifact to clean up.

2. **All shortlist entries deep-verify.**
   ```
   jq -r '.entry_hash' runs/_audit/$(date -u +%F)/shortlist.jsonl \
     | while read h; do
         python -m factory.ledger verify --hash "$h" --deep >/dev/null && echo "OK $h" || echo "FAIL $h"
       done
   ```
   Every line `OK`. Any `FAIL` after the audit means a quarantine missed or a corruption appeared during the audit window.

3. **Stale-flag counts match expectations.**
   ```
   python -m factory.ledger query --include-stale true --only-stale --limit 0 --format summary
   ```
   The summary's stale count equals `(pre-audit stale count) + (entries C5 quarantined this audit)`. A larger number means an out-of-band quarantine happened during the audit; investigate.

4. **Export round-trip is deterministic.**
   ```
   python -m factory.ledger export --dst /tmp/check1.jsonl
   sleep 1
   python -m factory.ledger export --dst /tmp/check2.jsonl
   diff /tmp/check1.jsonl /tmp/check2.jsonl
   ```
   Empty diff. Per spec 012 §5.8 the dump is deterministic for the same DB state; any difference is a bug.

5. **Trigger evaluation persisted.**
   ```
   python -m factory.ledger query --limit 0 --format summary --include-trigger-stats
   ```
   ([TBD-impl] — `--include-trigger-stats` not yet enumerated in spec 012 §3; query the `relitigate_triggers` table directly via the read-only SQLite connection if needed.) Sanity-check that the `currently_satisfied` counts reflect the recent `evaluate-triggers` run.

6. **Read connections functional after writes.**
   ```
   python -m factory.ledger query --limit 5
   ```
   Should return immediately. If it blocks, a writer connection from a stale process is still holding a lock — confirm with `lsof runs/ledger.db` and kill the orphan.

7. **Audit directory archived.**
   ```
   ls -la runs/_audit/$(date -u +%F)/
   ```
   Contains at minimum: `ledger.jsonl` (pre-audit export), `shortlist.jsonl`, `verify.jsonl`, `triggers.jsonl`, `packets/`, the C5 deliberation transcript path, and `post_audit.jsonl`.

---

## 4. Troubleshooting

| Symptom | Likely cause | Action |
| :--- | :--- | :--- |
| `LedgerCorruption` on a routine `get_by_hash` | The artifact JSON on disk has been edited after persistence (developer mistake) or a partial write corrupted the bytes. | Quarantine via `mark-stale` immediately (Step 2.9). Compare the on-disk JSON against the most recent `export` to identify the divergence. Restore that single entry by overwriting the JSON from the export's content (the entry's full body lives on each export line). Re-verify deep. |
| `EntryNotFound` for a hash the operator copy-pasted from the UI | UI shows 7-char hash prefixes; the prefix collided with no row (typo) or with zero rows after a recent quarantine. | Use the full 64-char hash. If the UI truncated and the prefix is genuinely ambiguous, the audit-mode CLI accepts longer prefixes — pass at least 12 chars. |
| `RelitigateCheckFailed` for one of the built-in triggers | The trigger's `check_fn` raised (catalog unreachable, surrogate file missing). Per spec 012 §5.5, the state machine MUST treat error as "not currently satisfied". | Investigate the underlying dependency. The trigger's `last_error` field captures the exception type and message; the trigger stays in its previous `currently_satisfied` value until the check succeeds again. Failure is *not* an entry-staleness signal. |
| `DowngradedDueToStaleness` raised by a downstream module the operator did not expect | The entry was quarantined by a prior audit and the downstream module is correctly refusing to use it. | This is the system working. If the downstream module needs the data, the right path is **re-litigation** (Step 2.5), not un-staling. Only un-stale via `--clear` with a documented re-verification. |
| `LedgerSchemaMismatch` at startup after a code update | Phase A pins schema version; the code expected a different version. | Export from the old code, upgrade the code, restore into a fresh DB (Step 2.10). Never edit `schema_meta.schema_version` directly to bypass the check — it exists exactly to force this migration. |
| `LedgerWriteFailed` during an `insert_entry` from a live cycle | SQLite `OperationalError`: locked, disk full, read-only mount. | Pause the factory. Inspect `runs/<cycle-id>/cycle.jsonl` for the underlying SQLite message. Fix the cause (free disk, remount r/w, kill the holder of the lock). The JSON file from step 4 of the insert flow is on disk; the next `insert_entry` retry is idempotent on the entry's hash (spec 012 §5.1). |
| `top_cited_entries` returns zero rows on a multi-week-old factory | The reverse-citation index `entry_citations` is empty, meaning no downstream artifact has cited a prior entry. This is *not* a bug in a young factory — the dependency graph forms slowly. | Lower the audit's `--top-cited` threshold or wait for more cycles. Spec 012 §5.6: `top_cited_entries` is the C5 shortlist by design; an empty list means no compounding risk yet. |
| `high_uncertainty_with_dependents` returns the same entries audit after audit | These entries have high `primary_uncertainty` and multiple dependents, but C5 chose `qualified` (not stale) on each pass. | Re-evaluate whether the entries are mis-classified as high-uncertainty (the `primary_uncertainty` summary rule per spec 012 §5.7 is max 1σ half-width on the pre-registered metric; some entries may have inflated half-widths from cherry-picked metrics). Surface the recurrence to the operator as a separate signal; persistent re-appearance without resolution is a calibration issue, not a per-entry problem. |
| `verify --orphans` lists hundreds of files | The factory was force-killed during a high-throughput period, or someone restored an export into a directory that already had artifact JSONs. | Move all the listed orphans to a quarantine directory; replay them through `python -m factory.ledger insert --from <path>` one at a time. If they fail validation, archive as stale dev artifacts. |
| `evaluate-triggers` is slow (>1 min for the full ledger) | One of the built-in `check_fn`s is doing per-entry network calls (e.g., querying the catalog for every entry). | Spec 012 §8: ledger overhead is < 1 ms per trigger; user-provided `check_fn` cost dominates. Confirm with profiling; cache the catalog lookups across triggers. |
| `restore` refuses to run | DB is non-empty (spec 012 §3 explicitly refuses to mix histories). | Move the existing DB aside (Step 2.7). Restore into a fresh path. |
| Export shows fewer entries than `query --limit 0 --format summary` total | `query` excludes stale by default; `export` includes everything (spec 012 §5.8). The summary header counts all entries; default `query` rows omit stale. | This is correct behaviour. Cross-check by passing `--include-stale true` to the summary. |
| Repeated `LedgerWriteFailed` even after freeing disk | The writer connection is still held by a process that has since crashed; SQLite's `busy_timeout=5000` (spec 012 §4.1) hits before the OS releases the lock. | `lsof runs/ledger.db` to find the holder; kill it. The WAL files (`*.db-wal`, `*.db-shm`) may need to be checkpointed via `PRAGMA wal_checkpoint(TRUNCATE)` after the holder is gone. |

---

## 5. Related

- **Spec 012 — Evidence Ledger** (`docs/specs/012-evidence-ledger.md`): canonical interface, SQLite schema, the file-before-row atomicity contract (§5.3), the C5 audit query semantics (§5.6), trigger evaluation rules (§5.5), and the failure-mode taxonomy this runbook depends on.
- **Spec 002 — Typed Artifacts** (`docs/specs/002-artifacts.md`): defines `EvidenceLedgerEntry`, `ProvenanceBlock`, `RelitigationTrigger`, `EvidenceResult`, and the hash computation that `verify(deep=True)` re-runs. The ledger indexes these artifacts; it does not invent new ones.
- **Spec 003 — Gate State Machine** (`docs/specs/003-state-machine.md`): owns the `C5Scheduler` (§5.5) that drives the weekly audit cadence; consumes ledger queries at G0 for hypothesis freshness; owns the `relitigate` path. See `runbooks/state-machine-debugging.md` when an `insert_entry` failure at cycle terminal blocks the state machine.
- **Spec 001 — Council Library** (`docs/specs/001-council.md`): runs the C5 deliberation that consumes the audit packet from Sub-step E of the weekly workflow.
- **Spec 010 — Surrogate Models** (`docs/specs/010-surrogate.md`): MUST honour stale flags during training-set queries; a regression here re-introduces the compounding failure mode.
- **Spec 011 — RAG Writer** (`docs/specs/011-rag-writer.md`): MUST honour stale flags during internal-citation retrieval; a regression here surfaces in published RunReports.
- **Spec 014 — Telemetry & Audit** (`docs/specs/014-telemetry-audit.md`): the structured-event stream `ledger.insert`, `ledger.trigger_check_failed`, `ledger.mark_stale` that the audit workflow expects.
- **SPEC.md §10.4** (internal hallucination compounding): the failure mode this entire runbook defends against. The weekly C5 audit workflow (§2.11) is the codified countermeasure; the top-cited + high-uncertainty queries are its shortlist.
- **SPEC.md §10.1, §10.2, §10.3** (sycophancy, numerical gullibility, invariant hacking): adjacent failure modes that the audit may surface (a sycophantic C2 verdict leading to a falsely-passed entry now eligible for C5 re-audit, etc.) but does not primarily defend.
