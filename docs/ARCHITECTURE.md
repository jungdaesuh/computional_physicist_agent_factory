# ARCHITECTURE.md — Modularity & Fast-Onboarding Principles

This document defines the **architectural invariants** the codebase must satisfy. It is shorter than `SPEC.md` on purpose — these are non-negotiable rules every spec inherits.

The goal is simple: **a fresh-context agent (human or LLM) should become productive within 40 minutes** of opening the repo, with no tribal knowledge required. Achieving this requires the system to be modular, debuggable in isolation, and self-documenting.

---

## 1. Architectural Invariants

These are absolute. Every spec inherits them; specs that violate them must update this document first with rationale.

### 1.1 Every component is runnable in isolation

Each module exposes a CLI entry point: `python -m factory.<module>` or `<module> <subcommand>`. A new agent can run the module with mock/fixture inputs without booting the rest of the factory. No module depends on "the whole factory being up."

**Test:** `python -m factory.council deliberate --mock-mode` works on a fresh checkout with no API keys configured.

### 1.2 Every component has a mock mode

When external dependencies (LLM APIs, container runtimes, simulator binaries, OpenAlex) are unavailable, the component runs with fixture data. Mock mode is a first-class operating mode, not an afterthought. Switching is `--mock-mode` flag or `FACTORY_MOCK=1` env var.

**Test:** Every integration test runs in mock mode in CI. Live-mode tests are gated by a separate marker (`@pytest.mark.live`).

### 1.3 Inputs and outputs are typed artifacts, persisted

Every meaningful module input and output is one of the **thirteen** typed artifacts (`GapCandidate`, `HypothesisSpec`, ..., `Strategy`, `StrategyCycleEvidence` — see `FIX_PLAN.md §26`). Artifacts are JSON, content-addressed by hash, and persisted to a local artifact store. In-memory state is transient; persistent state is artifacts only.

**Test:** Any module can be replayed by feeding it the input artifacts from a prior run. `factory replay <module> --inputs <artifact-hashes>`.

### 1.4 Logs are structured, colocated, and per-cycle

Every cycle has a directory `runs/<cycle-id>/` containing:
- `cycle.jsonl` — JSON-line log of every event in the cycle.
- `artifacts/` — every typed artifact emitted during the cycle.
- `sandbox/` — generator-verifier sandbox outputs.
- `councils/` — full council deliberation transcripts.
- `MANIFEST.json` — index of everything in the cycle directory with hashes.

Logs use structured fields: `{ts, cycle_id, module, level, event, payload}`. No free-text log messages without a structured event name.

**Test:** `factory inspect <cycle-id>` reads `MANIFEST.json` and reconstructs the cycle.

### 1.5 Every public interface is fully typed

No `Any`. No untyped dictionaries. No implicit contracts. Pydantic models (or dataclasses with strict typing) at every module boundary. Type errors raise at the boundary, not later. Every consumer of LLM access imports `from factory.llm_client import OpenRouterClient` for the live path and `FileClient` for fixture-replay testing — both implement the `DecisionClient` Protocol (spec 018), so drop-in swapping is type-checked at the boundary.

**Test:** `mypy --strict factory/` passes. `pydantic.ValidationError` is the only exception type at module boundaries.

### 1.6 Tests are documentation

Every module's `tests/test_<module>.py` contains at least one integration-style test demonstrating *typical usage*. A new agent reads the test, copies the pattern, and is productive. Tests use realistic fixture artifacts, not synthetic toy data where it can be avoided.

**Test:** Every module's test file has at least one test function named `test_<module>_typical_usage`.

### 1.7 Module boundaries are enforced

No circular imports. Cross-module communication only via public API (the spec-defined interface). No reaching into another module's internals (`module._internal_helper`). Tools like `ruff` or `import-linter` enforce module boundaries in CI.

**Test:** `import-linter` config in `pyproject.toml` defines layers; violations fail CI.

### 1.8 State is content-addressed

Every artifact has a SHA-256 content hash. Artifacts are immutable once written. References between artifacts use hashes, not paths or IDs alone. Reproducibility = recomputing the same artifact from the same inputs yields the same hash.

**Test:** Re-running a cycle with the same seed inputs produces artifacts with the same hashes (modulo timestamps, which are factored out of the hash).

### 1.9 Failure modes are documented per module

Each spec's "LOCAL DEBUG" and "FAILURE MODES" sections list the common error signatures + recovery actions. A new agent sees a stack trace, greps the docs, finds the failure mode in 30 seconds.

**Test:** Pytest failures emit a structured error class (`FactoryError` subclass) whose name appears in the spec's failure-modes table.

### 1.10 Onboarding ramp is under 40 minutes

A new agent should be able to:
1. Read `INDEX.md` (5 min).
2. Read `ARCHITECTURE.md` (this file) (10 min).
3. Open one spec relevant to their task (15 min).
4. Run that spec's mock-mode example (5 min).
5. Make a productive edit and run tests (5 min).

Total: **40 minutes** to first productive edit + green test.

**Test:** Periodically validated by asking a fresh LLM agent to complete a small task starting from scratch; record the wall-clock to first successful edit + green test.

---

## 2. Required Spec Front-Matter

Every spec under `specs/` must include these four blocks **before** §1 Summary:

### `CONTEXT` block

The 60-second pitch. What this component is, the 3–5 facts you need to know, and the one file/test to open first. Maximum 10 lines.

### `ENTRY POINTS` block

Paths and names of:
- The main module file.
- The test file with `_typical_usage` example.
- The CLI command (with `--mock-mode` invocation).
- The runbook (if non-trivial setup is required).

### `LOCAL DEBUG` block

How to instantiate and run the component in isolation:
- Mock-mode invocation (no external deps).
- Fixture artifacts to feed it.
- Common error signatures + recovery actions.
- Log locations to inspect.

### `DEPENDENCIES` block

- **Hard deps** — must exist for live mode (other specs, external services).
- **Soft deps** — optional, with documented fallback behavior.
- **Mocks** — what's available for testing in isolation.

The full updated spec template lives in `INDEX.md` §7.

---

## 3. Repository Layout

The layout enforces modular boundaries. New code goes in an existing module or a new one — never in a "utils" or "common" dumping ground.

```
2026_google/
├── docs/
│   ├── INDEX.md                    Navigation hub
│   ├── ARCHITECTURE.md             This file
│   ├── SPEC.md                     Canonical spec
│   ├── UI_DESIGN.md                UI design prompts
│   ├── specs/                      Component specs (NNN-name.md)
│   ├── prds/                       Milestone PRDs
│   └── runbooks/                   How-to-run docs (one per non-trivial operation)
├── factory/
│   ├── __init__.py
│   ├── artifacts/                  Spec 002 — typed artifacts + provenance
│   ├── council/                    Spec 001 — deliberation library
│   ├── catalog/                    Spec 004 — simulator catalog
│   ├── selector/                   Spec 005 — simulator selector
│   ├── adapter/                    Spec 006 — domain adapter
│   ├── literature/                 Spec 007 — OpenAlex + Gap Miner
│   ├── genver/                     Spec 008 — generator-verifier loop
│   ├── validation/                 Spec 009 — G4 portfolio
│   ├── surrogate/                  Spec 010 — surrogate models + OOD
│   ├── writer/                     Spec 011 — RAG writer
│   ├── ledger/                     Spec 012 — EvidenceLedger
│   ├── budget/                     Spec 013 — budget tracker
│   ├── telemetry/                  Spec 014 — logging + audit
│   ├── operator/                   Spec 015 — CLI + HTTP API
│   ├── strategy/                   Spec 016 — Bayesian surprise + UCT + archive (NEW)
│   │   ├── beliefs.py              beta_kl, dirichlet_kl, surprise variants
│   │   ├── archive.py              StrategyArchive class
│   │   ├── selection.py            UCT + novelty + MAP-Elites
│   │   ├── evidence.py             StrategyCycleEvidence aggregation
│   │   └── distill.py              off-path strategy distillation (Phase B)
│   ├── fidelity/                   Spec 017 — multi-fidelity ladder scheduler (NEW)
│   │   ├── scheduler.py
│   │   └── tiers.py
│   ├── llm_client/                 Spec 018 — shared OpenRouter LLM substrate (NEW)
│   │   ├── api.py                  DecisionClient Protocol, OpenRouterClient
│   │   ├── retry.py
│   │   ├── rate_limit.py
│   │   ├── mock.py                 FileClient + MockOpenRouterClient
│   │   └── pricing.py              config/pricing/openrouter.yaml loader
│   └── state_machine/              Spec 003 — gate orchestrator
├── tests/
│   ├── unit/                       One subdir per factory/ module
│   ├── integration/                Cross-module tests
│   └── fixtures/                   Realistic fixture artifacts
├── runs/                           Per-cycle artifact directories (gitignored)
├── containers/                     Dockerfiles per catalog entry
├── pyproject.toml                  Dependencies + tool config
├── README.md                       Pointer to docs/INDEX.md
└── .github/workflows/              CI (lint, type, test, import-boundaries)
```

**Module-to-spec correspondence is 1:1.** Each `factory/<module>/` corresponds to exactly one spec. No module spans multiple specs; no spec spans multiple modules.

**Top-level `config/` tree** (canonical paths, per `FIX_PLAN.md §10` and `§25.6`; §25 SUPERSEDES §24):

```
config/
├── council/
│   ├── lineup.yaml                Council lineup: 4 OpenRouter model IDs (one per vendor, §25.3) + persona assignment
│   ├── personas/
│   │   ├── visionary.md
│   │   ├── pessimist.md
│   │   └── pragmatist.md
│   ├── probes.yaml                Sycophancy calibration probes
│   └── chairman_rotation.yaml     Chairman-persona rotation policy ∈ {random, round_robin, weighted_by_cost}
├── pricing/
│   └── openrouter.yaml            Single pricing table for all 5 OpenRouter models (4 council + 1 agentic) — FIX_PLAN §25.6
├── state_machine/
│   ├── gate_routes.yaml
│   └── gates/<gate>.yaml
├── operator.yaml
└── sandbox_imports.yaml
```

**LLM env vars.** All factory LLM access — council deliberation and every agentic call (code-gen, Gap Miner, RAG writer, OOD audit, telemetry digest) — routes through OpenRouter using **one env var: `OPENROUTER_API_KEY`**. Per-vendor keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY`, `GEMINI_FLASH`) are dropped. See `FIX_PLAN.md §25.6`. Reference: https://openrouter.ai/docs.

### 3.1 Canonical Module Template

Every module under `factory/` follows this internal layout. Same template, every time. New agents learn the pattern once and apply it everywhere.

```
factory/<module>/
├── __init__.py            Public API exports (only — internals never imported across modules)
├── README.md              ≤ 1 page. What the module does, link to spec, mock-mode example.
├── api.py                 The public-facing class(es) and functions. This is what other modules import.
├── types.py               Module-local types (not artifacts; artifacts live in factory/artifacts/).
├── cli.py                 CLI entry point. Implements `python -m factory.<module>`.
├── mock.py                Mock-mode implementation of the public API.
├── errors.py              Module-specific exceptions, all inheriting FactoryError.
├── <module_specific>.py   One file per major concern (e.g., council/stages.py, catalog/onboarding.py).
├── config/                Default YAML/JSON config files for this module.
├── fixtures/              Realistic fixture data used by tests AND mock mode.
│   └── *.json / *.yaml
└── tests/
    ├── __init__.py
    ├── test_<module>_typical_usage.py    REQUIRED — demonstrates the canonical use.
    ├── test_api.py                       Unit tests for the public API.
    ├── test_<concern>.py                 One file per major concern.
    └── conftest.py                       Module-local pytest fixtures.
```

Rules for the template:

1. **`__init__.py` exports the public API only.** Anything not exported is internal. Other modules import from `factory.<module>` (which resolves through `__init__.py`), never from `factory.<module>.internal_file`.
2. **`api.py` is the contract.** The public interface lives there. Type signatures match the spec's "Public Interface" section verbatim.
3. **`README.md` is the 1-minute onboarding.** Opens with: "This module does X. To run it: `python -m factory.<module> --mock-mode`. See `docs/specs/NNN-<name>.md` for full spec."
4. **`mock.py` is first-class.** Same public API as `api.py`, returning fixture data. Selected by `--mock-mode` flag or `FACTORY_MOCK=1` env var.
5. **`fixtures/` holds *realistic* data.** Real artifacts produced by prior runs, sanitized. New agents can reason about them without inventing values.
6. **`errors.py` inherits `FactoryError`.** Specific subclasses per failure mode (e.g., `CouncilSycophancyDetected`, `CatalogLicenseViolation`). Listed in the spec's Failure Modes table.
7. **`tests/` is colocated.** Tests live inside the module, not in a parallel `tests/` tree. The top-level `tests/integration/` directory holds only cross-module tests.

### 3.2 Cross-Module Communication Contract

Modules talk through:
- **Typed artifacts** (defined in `factory/artifacts/`, spec 002). These are the lingua franca.
- **Public API calls** through `factory.<module>` import surface.
- **Events to telemetry** (spec 014) — modules emit structured events; they do not call each other to report status.

Modules **do not**:
- Import from another module's internals.
- Share in-process state.
- Call each other through hidden side channels (env vars, temp files outside `runs/<cycle-id>/`).

The state machine (spec 003) is the only orchestrator. It reads artifacts from one module's output and feeds them to the next.

### 3.3 Module Generator (Bootstrap)

To scaffold a new module conforming to the template, run:

```
python -m factory.tooling scaffold-module --name <new_module> --spec <spec-number>
```

This creates the directory, populates `__init__.py`, `README.md`, `api.py` stub, `mock.py` stub, `cli.py` with `--help`, `errors.py` with a `<NewModule>Error(FactoryError)` base, and `tests/test_<new_module>_typical_usage.py` skeleton. The new agent fills in the bodies.

The generator is itself a small module (`factory/tooling/`) — even bootstrap tooling follows the template.

---

## 4. Operational Principles

### 4.1 Determinism by default

Unless an operation is explicitly stochastic (LLM call, MC sampling), it must be deterministic. Seeds are persisted in the artifact for any stochastic operation.

### 4.2 No silent failures

Every error path emits a structured event to `cycle.jsonl`. No `except: pass`. No swallowed exceptions. Errors propagate to the gate state machine, which decides whether to recover or abort.

### 4.3 Idempotent operations

Module operations are idempotent where possible. Re-running a module with the same input artifact + the same seed produces the same output artifact (same hash).

### 4.4 No global state

Factory state is per-cycle (in `runs/<cycle-id>/`) or persistent (in the artifact store + `EvidenceLedger` DB). There is no in-memory singleton, no module-level mutable globals, no implicit context.

### 4.5 Configuration is data, not code

All tunable parameters (gate thresholds, council lineup, budget caps, surrogate paths) live in YAML/JSON config files under `config/`. Code reads config at startup; changing behavior never requires editing code.

The pricing table is a **single file** — `config/pricing/openrouter.yaml` — because all factory LLM access routes through OpenRouter (one API, one key, one pricing surface). The file lists pass-through prices for the 4 council models plus the 1 agentic default (§25.3). Schema and update policy are documented in `specs/013-budget-tracker.md`; see `FIX_PLAN.md §25.6` (§25 SUPERSEDES §24).

### 4.6 Live mode and mock mode are switchable per-module

The factory CLI accepts `--mock-mode` (all modules mocked) or per-module flags (`--mock=catalog,literature` runs Council + Selector live but mocks Catalog + Literature). This lets a new agent debug one module at a time without bringing up the whole stack.

---

## 5. Onboarding Path for a Fresh Agent

When a fresh-context agent opens this repo for the first time, the canonical path is:

1. **Open `docs/INDEX.md`.** Read §1 Quick Orientation and §4 Top-Level TODO. Identify what's in progress.
2. **Open `docs/ARCHITECTURE.md`** (this file). Read §1 (Invariants) and §3 (Repository Layout).
3. **Open the one spec for the task at hand.** Read the CONTEXT block first; the rest only if needed.
4. **Run the spec's LOCAL DEBUG example in mock mode.** Confirm the dev environment works.
5. **Open the spec's typical-usage test.** Copy the pattern.
6. **Make the smallest possible edit.** Run tests. Commit.

Specifically, the agent should *never* need to read more than:
- INDEX.md (~5 min)
- ARCHITECTURE.md (~10 min)
- The target spec (~15 min)
- The target module's typical-usage test (~10 min)

Total: 40 minutes to first productive edit. If a task requires reading more than this, the spec is missing context — file a doc bug and fix the spec.

---

## 6. Anti-Patterns to Avoid

These are observable signals that the architecture is drifting from its invariants. Surface in code review and fix immediately.

| Anti-pattern | Why it breaks onboarding | Fix |
| :--- | :--- | :--- |
| "It only works if the council is already up" | Forces serial debugging; new agent can't isolate | Add mock mode; persist a fixture council verdict |
| "Read these 4 specs to understand this" | Spec is missing context | Inline the missing context or split the work |
| `utils.py` or `helpers.py` | Dumping ground; nothing is findable | Move to the right module or create a new one with a spec |
| Magic strings / numbers in code | New agent has to grep | Move to config; reference by name |
| "We always run X before Y" undocumented | Tribal knowledge | Document in the relevant runbook |
| Modules that import from each other's internals | Boundary violation | Refactor to public API; import-linter catches in CI |
| Tests that require external services | Can't run on a fresh checkout | Add mock mode; gate live tests behind `@pytest.mark.live` |
| Long stack traces with no `FactoryError` subclass | Failure mode is undocumented | Catch at the right boundary; raise a typed `FactoryError` |

---

## 7. How This Document Evolves

`ARCHITECTURE.md` is updated only when an invariant changes. Updates require:
1. A PR with the rationale in the description.
2. Updates to any spec that relied on the old invariant.
3. A check that the onboarding ramp test (§1.10) still passes.

Routine status updates go in `INDEX.md`. Component-level changes go in the relevant spec. Only system-level architectural shifts touch this file.
