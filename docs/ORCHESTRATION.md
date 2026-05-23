# ORCHESTRATION.md — Subagent Orchestration Playbook

This document is the **canonical playbook** for orchestrating subagents (Claude / Opus 4.7 max effort) to maximize implementation speed across the AI Co-Computational Physicist Factory project. It applies to spec-writing, code implementation, testing, and review.

The playbook is read by:
1. The **main orchestrator** (the Claude conversation you have open) — deciding what to delegate and when.
2. Each **subagent** — receiving a brief, with this playbook referenced for context.

---

## 1. Core Idea

Implementation speed is bounded by either (a) the longest sequential dependency chain, or (b) operator review bandwidth. We minimize (a) by aggressive parallelism whenever the architecture supports it. The architecture is designed for this — typed artifacts and 1:1 spec-to-module mapping make most work independently parallelizable.

The orchestrator does not implement. It **decomposes**, **dispatches**, **integrates**, and **gates**.

---

## 2. The Orchestration Model

```
                        ┌─────────────────────────────────┐
                        │  Main Orchestrator (you)        │
                        │  — decomposes work into briefs  │
                        │  — dispatches subagents         │
                        │  — verifies & integrates outputs│
                        │  — gates progression to next wave│
                        └────────────────┬────────────────┘
                                         │ (12+ parallel briefs in one message)
                ┌────────────────────────┼────────────────────────┐
                ▼                        ▼                        ▼
        ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
        │  Subagent 1  │         │  Subagent 2  │   ...   │  Subagent N  │
        │  Opus 4.7    │         │  Opus 4.7    │         │  Opus 4.7    │
        │  max effort  │         │  max effort  │         │  max effort  │
        │              │         │              │         │              │
        │ Writes one   │         │ Writes one   │         │ Writes one   │
        │ file.        │         │ file.        │         │ file.        │
        │ Returns ≤50  │         │ Returns ≤50  │         │ Returns ≤50  │
        │ word report. │         │ word report. │         │ word report. │
        └──────────────┘         └──────────────┘         └──────────────┘
```

The orchestrator pattern is **fan-out then verify**. Subagents do not talk to each other. They communicate only via persisted artifacts (specs, code, tests) on disk.

---

## 3. Decomposition Rules

Work is decomposable into a subagent-sized brief iff all of the following hold:

| Rule | Why |
| :--- | :--- |
| Single file (or single tightly-scoped directory) target | No write conflicts between subagents |
| Self-contained context fits in ≤5 source files | Subagent's context window is finite; large context = slow + flaky |
| Output is structurally defined (template, schema, interface contract) | Orchestrator can verify the output mechanically, not by re-reading it |
| No subagent-to-subagent dependency within the same wave | Parallelism requires independence |
| Failure of one brief does not corrupt others' outputs | Failed briefs can be re-dispatched without rollback |

Briefs that fail one or more rules must be **split** before dispatch.

---

## 4. Wave-Based Execution

Work is organized into **waves**. Within a wave, briefs run in parallel. Between waves, the orchestrator verifies outputs and gates the next wave.

```
Wave 1 (parallel) ──→ Verify ──→ Wave 2 (parallel) ──→ Verify ──→ Wave 3 ...
```

A wave is **complete** when every brief in the wave has either succeeded or been re-dispatched after a failure. A wave **gates** the next when verification passes.

**Verification per wave:**
- Did every brief produce its expected output file?
- Does each output pass its structural check (template compliance, schema validity, lint, mypy)?
- Are inter-output references consistent (e.g., spec X references spec Y; Y exists and was produced this wave)?

If verification fails for one brief, **re-dispatch that brief only**. Do not advance the wave.

---

## 5. Current Wave Plan (Project Lifecycle)

### Wave 0 — Foundational docs (DONE)

Written directly by orchestrator, not delegated:
- `docs/SPEC.md`
- `docs/UI_DESIGN.md`
- `docs/ARCHITECTURE.md`
- `docs/INDEX.md`
- `docs/ORCHESTRATION.md` (this file)
- `docs/prds/PRD-001-phase-a-mvp.md`
- `docs/prds/PRD-002-council-library.md`
- `docs/prds/PRD-003-first-autonomous-cycle.md`
- `docs/prds/PRD-004-simulator-catalog-v1.md`
- `docs/specs/001-council.md`
- `docs/specs/002-artifacts.md`
- `docs/specs/003-state-machine.md`

These are the bedrock — every later wave reads them. They were written by the orchestrator to ensure consistent voice and to anchor the spec template.

### Wave 1 — Remaining specs (PARALLEL, 12 subagents)

All other component specs. Independent because each spec is a different file and structural verification is mechanical.

| Subagent | Output | Detail level |
| :--- | :--- | :--- |
| W1-A | `docs/specs/004-simulator-catalog.md` | Full |
| W1-B | `docs/specs/005-simulator-selector.md` | Medium |
| W1-C | `docs/specs/006-domain-adapter.md` | Skeleton |
| W1-D | `docs/specs/007-literature-discovery.md` | Skeleton |
| W1-E | `docs/specs/008-generator-verifier.md` | Full |
| W1-F | `docs/specs/009-validation-portfolio.md` | Full |
| W1-G | `docs/specs/010-surrogate-models.md` | Skeleton |
| W1-H | `docs/specs/011-rag-writer.md` | Skeleton |
| W1-I | `docs/specs/012-evidence-ledger.md` | Full |
| W1-J | `docs/specs/013-budget-tracker.md` | Medium |
| W1-K | `docs/specs/014-telemetry-and-audit.md` | Skeleton |
| W1-L | `docs/specs/015-operator-interface.md` | Skeleton |

**Verification step after Wave 1:** orchestrator runs `python -m factory.tooling lint-specs` **[TBD until Wave 2 W2-B lands]** — checks each spec contains the four required front-matter blocks (CONTEXT, ENTRY POINTS, LOCAL DEBUG, DEPENDENCIES) and all 10 numbered sections. Until that command exists, verification is done by hand against the same checklist. Do **not** promise the command exists. Re-dispatch any failing spec.

### Wave 2 — Project bootstrap (PARALLEL, 5 subagents)

Mechanical setup with no inter-dependencies:

| Subagent | Output |
| :--- | :--- |
| W2-A | `pyproject.toml` with deps + tool config (mypy strict, ruff, import-linter, pytest) |
| W2-B | `factory/__init__.py` + `factory/tooling/scaffold_module.py` (per ARCHITECTURE.md §3.3) |
| W2-C | `.github/workflows/ci.yml` running lint + type + tests + spec-lint + schema-drift |
| W2-D | `factory/artifacts/` skeleton + Pydantic models from spec 002 |
| W2-E | `factory/council/` skeleton (no live impl yet) from spec 001 |

**Verification step:** `mypy --strict`, `ruff check`, `pytest -m "not live"` all green. Each module's `python -m factory.<module> --help` returns clean.

### Wave 3 — Foundational modules (PARALLEL, 6 subagents)

Implement core data + infrastructure modules. Each module depends on artifacts (Wave 2 W2-D) only.

| Subagent | Module | Spec |
| :--- | :--- | :--- |
| W3-A | `factory/ledger/` full implementation | 012 |
| W3-B | `factory/budget/` full implementation | 013 |
| W3-C | `factory/telemetry/` full implementation | 014 |
| W3-D | `factory/catalog/` full implementation + schema | 004 |
| W3-E | `factory/selector/` full implementation | 005 |
| W3-F | `factory/council/` live implementation (PRD-002 acceptance) | 001 |

**Verification step:** all modules pass typical-usage test in mock mode. Council calibration runs locally and shows ≥0.40 disagreement-rate on the built-in probe set. Re-dispatch any that fail.

### Wave 4 — Execution + validation (PARALLEL, 4 subagents)

Depends on Wave 3.

| Subagent | Module | Spec |
| :--- | :--- | :--- |
| W4-A | `factory/adapter/` + first 2 simulator adapters | 006 |
| W4-B | `factory/genver/` full implementation | 008 |
| W4-C | `factory/validation/` full G4 portfolio | 009 |
| W4-D | `factory/surrogate/` skeleton + 1 working surrogate | 010 |

### Wave 5 — Literature + writing (PARALLEL, 2 subagents)

| Subagent | Module | Spec |
| :--- | :--- | :--- |
| W5-A | `factory/literature/` OpenAlex client + Gap Miner | 007 |
| W5-B | `factory/writer/` RAG writer skeleton | 011 |

### Wave 6 — Orchestrator + operator (PARALLEL, 2 subagents)

| Subagent | Module | Spec |
| :--- | :--- | :--- |
| W6-A | `factory/state_machine/` full orchestrator | 003 |
| W6-B | `factory/operator/` CLI + HTTP API | 015 |

### Wave 7 — Integration test + first live cycle (SEQUENTIAL, orchestrator-led)

Not parallel — this is the milestone gate. The orchestrator drives:
1. Integration test in mock mode end-to-end. Fix any drift.
2. Live cycle attempt against real Council, real Catalog, real generator-verifier.
3. Postmortem.

PRD-003 closes here.

---

## 6. Subagent Brief Template

Every brief must include all of the following. Briefs without the full template produce drift.

```
ROLE
You are an Opus 4.7 max-effort subagent contributing to the AI Co-Computational Physicist Factory project at /Users/suhjungdae/code/2026_google/.

CONTEXT (read these files first; in this order)
1. /Users/suhjungdae/code/2026_google/docs/SPEC.md
2. /Users/suhjungdae/code/2026_google/docs/ARCHITECTURE.md
3. /Users/suhjungdae/code/2026_google/docs/INDEX.md
4. /Users/suhjungdae/code/2026_google/docs/specs/001-council.md (style reference)
5. /Users/suhjungdae/code/2026_google/docs/specs/002-artifacts.md (data contracts you consume)

ASSIGNMENT
- Output file: <absolute path>
- Spec ID / module name: <NNN-name>
- Detail level: <full | medium | skeleton>
- Hard dependencies (other specs you read from): <list>
- Spec consumers (who reads what you produce): <list>

SPEC-SPECIFIC GUIDANCE
- Key concepts your spec MUST address: <bullets>
- Common pitfalls to avoid: <bullets>
- Reference content in SPEC.md: §<numbers>

CONSTRAINTS (non-negotiable)
- Follow the spec template in INDEX.md §7 EXACTLY: 4 front-matter blocks (CONTEXT, ENTRY POINTS, LOCAL DEBUG, DEPENDENCIES) + 10 numbered sections.
- Inherit all invariants from ARCHITECTURE.md §1.
- No references to external repos (karpathy, AI-Scientist, Theorizer, etc.) — they were stripped earlier.
- Status header: `> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23`.
- Use same code-block / table / section style as 001-council.md.
- Write the file directly. Do not return content to me.

REPORTING
After completion, report in ≤50 words: file path, approximate line count, any issues encountered.
```

---

## 7. Conflict Avoidance

Subagents in the same wave must satisfy:

1. **Disjoint file targets.** No two subagents write the same file. (Easy: 1:1 brief-to-file.)
2. **No shared in-memory state.** Subagents are independent Claude conversations — they cannot share state. Communication is via files only.
3. **No reliance on another subagent's output within the same wave.** If brief A needs brief B's output, B must be in an earlier wave.
4. **No editing files that earlier waves produced.** Once a wave's output is verified, it is frozen until a deliberate re-dispatch. Subagents do not silently amend prior outputs.

If two briefs *must* touch the same file, restructure: either merge them into one brief, or split the file into two so each brief owns one.

---

## 8. When to Use Worktree Isolation

The `Agent` tool supports `isolation: "worktree"` to run a subagent in a git worktree (isolated copy of the repo). Use this when:

- Subagent modifies multiple files that another wave might also touch.
- Subagent runs experimental refactors that should not block other work.
- You want to compare two different implementation approaches in parallel without committing to either.

Do **not** use worktree isolation when:
- Brief writes a single file (no conflict risk).
- Brief is part of a wave where all outputs go into one merge step.
- Subagent needs to read the latest state of the main branch.

For Phase A, most briefs are single-file writes — worktree isolation is rarely needed.

---

## 9. Quality Gates Between Waves

Before advancing to the next wave, the orchestrator verifies:

| Check | Tool | Availability |
| :--- | :--- | :--- |
| All expected files exist | `ls` + glob | available |
| Specs pass structural lint | `python -m factory.tooling lint-specs` | **TBD — lands in Wave 2 W2-B**; meanwhile do the four-block + ten-section check by hand |
| Python modules pass mypy strict | `mypy --strict factory/` | available once any `factory/` module exists (Wave 2+) |
| Linting clean | `ruff check .` | available once `pyproject.toml` lands (Wave 2 W2-A) |
| Mock-mode tests green | `pytest -m "not live"` | available once Wave 2 modules expose tests |
| Import boundaries respected | `import-linter` config | available once `pyproject.toml` declares the layered config (Wave 2 W2-A) |
| Schema drift caught | CI step regenerating JSON Schemas | available once `.github/workflows/ci.yml` lands (Wave 2 W2-C) |

Any check fails → identify the responsible brief → re-dispatch that brief only. **Do not silently promise a command exists** — if a row is marked TBD, the orchestrator either runs the hand-check fallback or defers verification to the wave that delivers the command.

---

## 10. Concrete Orchestrator Commands (Quick Reference)

Commands marked **[TBD]** do not yet exist; the wave that produces them is named in parentheses. Until that wave lands, use the documented fallback (or skip the check).

```bash
# Inspect current wave status (available now)
find docs/specs -name "*.md" | sort
find factory -name "README.md" | sort

# Verify Wave 1 spec structure
# [TBD until Wave 2 W2-B] — fallback: hand-check four front-matter blocks + ten numbered sections
python -m factory.tooling lint-specs docs/specs/

# Verify Wave 2 module skeletons (available after each module's W2-* lands)
for m in artifacts council ledger budget; do
    python -m factory.$m --help && echo "$m OK"
done

# Run all mock-mode tests (available once Wave 2 modules expose tests)
pytest -m "not live"

# Lint + type (available once Wave 2 W2-A pyproject.toml lands)
ruff check .
mypy --strict factory/

# Confirm import boundaries (available once Wave 2 W2-A declares the import-linter layered config)
import-linter --config pyproject.toml
```

---

## 11. Anti-Patterns in Orchestration

| Anti-pattern | Why it slows you down | Fix |
| :--- | :--- | :--- |
| One mega-brief covering many files | Subagent loses focus; output quality drops | Split into single-file briefs |
| Re-briefing because of vague initial brief | Wasted compute, doubled wall clock | Use the §6 template every time |
| Sequential briefs when parallel is possible | Wall clock = N × per-brief time | Identify the independent subset; parallel-dispatch it |
| Reading the subagent's full output to verify | Defeats the parallelism benefit | Verify structurally (template / schema / lint), not by re-reading |
| Letting a wave's failures cascade | One slow brief blocks the wave | Time-box; re-dispatch failures while others continue |
| Skipping verification between waves | Drift compounds; later waves break | Always verify. Verification is cheap; re-work is expensive |
| Running a wave with shared file targets | Last writer wins; silent corruption | Enforce disjoint targets at brief-design time |

---

## 12. Outcome Metric

This playbook works if:
- A wave of N parallel briefs completes in approximately the time of the *slowest* brief, not the sum.
- Re-dispatches are rare (< 10% of briefs).
- Verification takes < 5% of wave wall-clock.
- The orchestrator's context window stays available for the next decomposition, not consumed by reading every subagent's output.

Optimizing for these metrics is the orchestrator's job. The playbook gives the recipe; tuning is empirical.
