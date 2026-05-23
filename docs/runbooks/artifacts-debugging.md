# Runbook: Debugging Typed Artifacts

> What this covers: triaging `ArtifactValidationError`, `ArtifactProvenanceMismatch`, `ArtifactImmutabilityViolation`, `FixtureNotFoundError`, and broken provenance chains across the eleven typed artifacts owned by spec 002 (see FIX_PLAN §1 for the full list, including `ValidationResult`, `SurrogateProbeResult`, and `FactoryControlEvent`). · When to use: a cycle aborted at an artifact boundary, a hash mismatch surfaced in `cycle.jsonl`, a `verify-chain` failure, or a stack trace pointing at `factory/artifacts/`. · Estimated time: 10 minutes for a single artifact validation; 30 minutes for a full provenance-chain walk back through a multi-stage cycle.

## 1. Prerequisites

- A failing cycle ID. Find it by `factory status` (lists active and recently terminated cycles) or by browsing `runs/`. The cycle ID is the directory name under `runs/`, e.g. `runs/20260523-abc/`.
- The artifact hash (or short 7-char prefix) from the error trace. If you only have the cycle, open `runs/<cycle-id>/MANIFEST.json` to enumerate every artifact written during that cycle along with its type.
- A clean checkout with `factory` on `$PATH` (`pip install -e .` from the repo root, then `factory --help` to confirm). Artifact-level inspection uses the per-module CLI `python -m factory.artifacts` (per FIX_PLAN §9.2); the operator-CLI surface in spec 015 does not enumerate `factory artifacts`.
- Optional: `jq` for filtering `cycle.jsonl`; `git diff --no-index` for comparing a tampered artifact against a known-good fixture.
- Mock-mode toggle: every CLI subcommand under `python -m factory.artifacts` honours `--mock-mode` / `FACTORY_MOCK=1`. Use mock mode if you cannot reach the cycle directory (e.g., a CI machine without persisted runs) and want to reproduce the bug against committed fixtures under `factory/artifacts/fixtures/`.

Mental model: **artifacts are immutable, content-addressed, and self-verifying.** Every error in this runbook is one of three failure shapes:
- *Shape A*: the artifact does not match its declared schema (`ArtifactValidationError`).
- *Shape B*: the artifact's content does not match its stored hash (`ArtifactProvenanceMismatch`).
- *Shape C*: a caller tried to mutate an artifact instead of producing a new one (`ArtifactImmutabilityViolation`).

A fourth, rarer mode is *Shape D*: the parent-hash chain is broken (`verify-chain` cannot reach a `GapCandidate` from a `RunReport`).

## 2. Steps

### 2.1 Locate the artifact file

Every artifact for a given cycle lives under `runs/<cycle-id>/artifacts/`. The filename is the SHA-256 hash of the canonical JSON (with the `provenance_hash` field excluded) plus a type-specific extension. Find the file:

```bash
# By exact hash:
ls runs/<cycle-id>/artifacts/ | grep <hash>

# By 7-char prefix (UI convention):
ls runs/<cycle-id>/artifacts/ | grep ^<prefix>

# By artifact type:
jq -r '.artifacts[] | select(.type == "HypothesisSpec") | .hash' \
   runs/<cycle-id>/artifacts/MANIFEST.json
```

If `MANIFEST.json` does not exist, the cycle terminated before any artifact was persisted; check `runs/<cycle-id>/cycle.jsonl` for the very first `factory.artifacts.persist` event — its `payload.hash` is your first lead.

### 2.2 Validate the artifact against its schema

```bash
python -m factory.artifacts validate runs/<cycle-id>/artifacts/<hash>.json
```

Expected on success:
```
ok type=HypothesisSpec hash=7a3b2c1...e91 schema_version=1
```

Expected on `ArtifactValidationError`:
```
ArtifactValidationError: 2 validation errors for HypothesisSpec
  expected_effect_size
    Input should be a valid number [type=float_parsing, input_value='inf', ...]
  pre_registered_metric
    Field required [type=missing]
```

Read each Pydantic error line as: `<field_path> ... [type=<pydantic_error_code>, input_value=<offending_value>]`. The producer of the artifact (the module that wrote it) is at fault — *not* the consumer.

### 2.3 Identify the upstream producer

```bash
# In cycle.jsonl, every artifact write emits an event with the producing module.
jq 'select(.event == "factory.artifacts.persist" and .payload.hash | startswith("<prefix>"))' \
   runs/<cycle-id>/cycle.jsonl
```

The `module` field in the matching event tells you which module produced the bad data. File the bug against that module; do not patch in `factory/artifacts/`.

### 2.4 Re-hash and diff against the stored hash

Even a schema-valid artifact can be tampered with. Re-hash:

```bash
python -m factory.artifacts hash runs/<cycle-id>/artifacts/<hash>.json
```

Expected:
```
computed=7a3b2c1...e91 stored=7a3b2c1...e91 match=true
```

If `match=false`:
```
computed=8b4c3d2...e91 stored=7a3b2c1...e91 match=false
ArtifactProvenanceMismatch: hash drift detected
```

This is a *Shape B* failure. Possible causes, in order of likelihood:
1. **Manual edit.** Someone (a human or a buggy migration script) opened the JSON and saved it. Restore from VCS or from a backup; do not re-compute the hash to "fix" it — that erases the audit trail.
2. **Schema migration drift.** A field was added to the model after the artifact was written. Migration is a Phase B concern; in Phase A this is a bug.
3. **Encoding drift.** Canonical JSON requires sorted keys, no whitespace, and UTF-8. Confirm by re-serializing:
   ```bash
   python -m factory.artifacts show --raw runs/<cycle-id>/artifacts/<hash>.json | \
     jq -c -S '. | del(.provenance_hash)' | shasum -a 256
   ```
   The output should match `stored`. If not, the file's on-disk encoding diverged from canonical.

### 2.5 Walk the provenance chain

For any `RunReport` or `EvidenceLedgerEntry`, you can walk backward through every parent artifact to a `GapCandidate`:

```bash
python -m factory.artifacts verify-chain <hypothesis-id>
```

Expected output (success):
```
RunReport       8f1d3e9...  ok
  EvidenceLedgerEntry  3a2c1b8...  ok
    ValidationResult     b4e9c2d...  ok
      ExperimentSpec     6f1a8d4...  ok
        HypothesisSpec   2c4e9b1...  ok
          GapCandidate   7d3a8f2...  ok
chain ok: 6 nodes, depth 5
```

Expected output (broken chain — *Shape D*):
```
RunReport       8f1d3e9...  ok
  EvidenceLedgerEntry  3a2c1b8...  ok
    ValidationResult     b4e9c2d...  parent_hash 6f1a8d4... not found
chain broken at depth 3
ArtifactValidationError: parent_hashes[0]=6f1a8d4... no artifact found
```

Common causes:
1. **Artifact deleted manually.** Check `runs/<cycle-id>/artifacts/` for the parent hash. If the file is genuinely missing, the cycle is poisoned for downstream consumption; the EvidenceLedger entry's `relitigate_if` should mark "provenance chain broken" so the hypothesis can be re-run.
2. **Cross-cycle parent.** A `HypothesisSpec` in cycle `X` may reference a `GapCandidate` first written in cycle `W`. `verify-chain` searches the artifact store globally; if not found, the producing cycle's directory was pruned. Restore the cycle directory from backup or accept the orphaned chain.
3. **Write race.** Rare. Two cycles writing to the artifact store concurrently can produce a partial parent reference if the persist event fired before `os.replace` landed. Spec 002 writes are atomic; if you see this in practice, file an infra bug.

### 2.6 Handle `ArtifactImmutabilityViolation` (Shape C)

Stack trace excerpt:
```
File "factory/genver/api.py", line 412, in run
    hypothesis.kill_criteria.append("max_iterations_reached")
TypeError: 'tuple' object has no attribute 'append'
...
ArtifactImmutabilityViolation: HypothesisSpec is frozen; use model_copy(update=...)
```

This is **not an artifact bug** — it is a caller bug. The fix in the calling site:

```python
# Wrong:
hypothesis.kill_criteria.append("max_iterations_reached")

# Right:
new_hypothesis = hypothesis.model_copy(
    update={"kill_criteria": [*hypothesis.kill_criteria, "max_iterations_reached"]},
)
```

`model_copy(update=...)` produces a **new** artifact with a **different** `provenance_hash`. The old artifact is unchanged on disk; the new artifact must be persisted via the normal write path (`factory.artifacts.persist`), which emits a `factory.artifacts.persist` event and updates `MANIFEST.json`.

If `mypy --strict factory/` is configured (it should be), this kind of mutation is caught at type-check time, not at runtime. If a runtime mutation slipped through, `mypy --strict` was not run on the offending module — make that the next CI failure to fix.

### 2.7 Handle `FixtureNotFoundError`

```
FixtureNotFoundError: no fixture 'sample' for artifact_type 'HypothesisSpec'
available fixtures: ['typical', 'edge', 'malformed']
```

The error message enumerates available fixtures. Use one of them. If you need a new fixture, add it to `factory/artifacts/fixtures/<artifact_type>/<name>.json`, run `python -m factory.artifacts validate` on it before committing, and reference it from your test.

### 2.8 Inspect a single artifact's content

```bash
python -m factory.artifacts show runs/<cycle-id>/artifacts/<hash>.json
```

Default output is a human-readable type-aware summary. Add `--raw` for the verbatim JSON, `--format json` for machine-readable, `--diff <other-hash>` to compare with a sibling artifact (useful when two cycles produced near-identical hypotheses but diverged downstream).

## 3. Verification

After applying any fix, confirm:

1. **The offending artifact is gone or repaired.** `python -m factory.artifacts validate <file>` returns ok. `python -m factory.artifacts hash <file>` matches the stored hash.
2. **The provenance chain is whole.** `python -m factory.artifacts verify-chain <hypothesis-id>` prints `chain ok` with the expected depth.
3. **The producer no longer emits bad data.** Re-run the producing module against the same input fixture in mock mode; confirm the new artifact passes validation.
   ```bash
   python -m factory.<producing_module> --mock-mode run --input <fixture>
   python -m factory.artifacts validate runs/<new-cycle-id>/artifacts/<new-hash>.json
   ```
4. **The CI step that emits JSON schemas still passes.** Spec 002 §7 requires `python -m factory.artifacts emit-schemas docs/schemas/` to be diff-free. Run it locally before committing.
   ```bash
   python -m factory.artifacts emit-schemas docs/schemas/
   git diff --exit-code docs/schemas/
   ```
5. **No silent fixture drift.** If you touched a fixture, run the full artifact test suite:
   ```bash
   pytest factory/artifacts/tests/ -q
   ```

## 4. Troubleshooting

| Symptom | Likely cause | First action |
| :--- | :--- | :--- |
| `ArtifactValidationError` immediately on cycle start | A producing module wrote a malformed artifact and `from_json` rejected on the next read | Step 2.3: find the producer in `cycle.jsonl`; fix at the source |
| `ArtifactValidationError` with `Field required [type=missing]` on a field added recently | Schema bumped without migrating old artifacts | Phase A bug — schema migration is deferred to Phase B. Either restore old artifact format or regenerate the artifact under the new schema |
| `ArtifactProvenanceMismatch` after a `git pull` | File mode / line-ending normalization rewrote the JSON | Check `.gitattributes`; ensure artifact `.json` files are `binary` or `eol=lf` |
| `ArtifactProvenanceMismatch` with no obvious tamper | Encoding drift (step 2.4 #3) — non-canonical JSON written by a third-party serializer | Replace the writer with `artifact.model_dump_json(sort_keys=True)` or the canonical helper |
| `chain broken at depth N` and the missing parent is in a different cycle | Cross-cycle parent referenced after cycle pruning | Restore the parent cycle from backup, or mark the dependent hypothesis as `relitigate_if=provenance_chain_broken` |
| `ArtifactImmutabilityViolation` with `'list' object` instead of `'tuple' object` | Pydantic config not actually frozen — caller used a non-frozen subclass | Audit `model_config = ConfigDict(frozen=True)` on every artifact subclass; ensure no subclass overrides it |
| `FixtureNotFoundError` in tests after a rebase | Fixture renamed in main but the test still references the old name | Update the test to reference the new fixture name; do not re-add the old fixture |
| `verify-chain` slow on deep chains | Disk-bound on artifact reads | Acceptable in Phase A (target <100 ms for depth ~10). If significantly slower, check that `runs/` is on local disk, not a network mount |
| Two artifacts with same content but different hashes | Different JSON encodings (whitespace, key order, escape style) | Step 2.4 — re-canonicalize via `to_canonical_json()`; replace the writer that produced the off-canonical version |
| `ArtifactValidationError` mentions an enum value not in the enum class | Stale fixture references a removed enum variant | Update fixture; check spec 002 for current enum values |
| Cycle directory missing `MANIFEST.json` but `artifacts/` has files | Cycle aborted before manifest sync | Rebuild manifest by re-running `python -m factory.artifacts manifest --cycle <cycle-id>` (regenerates from existing files) |

## 5. Related

- Spec 002 (Typed Artifacts) — the source of truth for every artifact's schema, hashing algorithm, and immutability contract.
- Spec 012 (Evidence Ledger) — owns the durability boundary for `EvidenceLedgerEntry` and is the consumer of `ValidationResult` from G4.
- `docs/specs/002-artifacts.md` §5.1 — canonical hashing algorithm; required reading if you need to debug Shape B failures from first principles.
- `docs/specs/002-artifacts.md` §6 — full failure-modes table; this runbook expands on the entries there.
- `factory/artifacts/tests/test_artifacts_typical_usage.py` — copy this pattern when writing a new artifact consumer.
- `runbooks/genver-debugging.md` — sibling runbook; if the bad artifact came out of the Generator-Verifier loop, that runbook covers the producer side.
- `runbooks/validation-debugging.md` — when a `ValidationResult` artifact has an inconsistent `verdict` vs. its `check_outcomes` (rejected at construction by the artifact validator).
- `ARCHITECTURE.md` §1.5 (Every public interface is fully typed) and §1.8 (State is content-addressed) — the architectural invariants this runbook protects.
