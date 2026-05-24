# Spec 015: Operator Interface (CLI + HTTP API)

> Status: ☐ not started · Owner: TBD · Last updated: 2026-05-23

## CONTEXT (60-second summary — read first)
- The **Operator Interface** is the single human-facing surface for driving and inspecting the factory: a `factory` CLI for all state-changing commands (start / stop / approve / reject / catalog onboarding / budget mutation) plus a localhost-only read-only FastAPI HTTP server (launched via `factory serve`) that the deferred UI (`UI_DESIGN.md`) consumes.
- The 5 facts: (1) Phase A is **CLI-only for mutations** — HTTP exposes only GETs for the 11 UI screens; (2) read endpoints stream from artifact store + EvidenceLedger + telemetry — they do *not* compute new state; (3) `factory start` streams cycle events to stdout from telemetry (spec 014) and supports an explicit `--cycles N` bound for finite runs; (4) every CLI subcommand respects a `--mock-mode` global flag (and the `FACTORY_MOCK=1` env var) against committed fixtures so onboarding works without a live factory; (5) mutations are append-only events — `factory pause`, `factory approve`, `factory budget set`, etc. all write a `FactoryControlEvent` artifact (spec 002, FIX_PLAN §1) that the state machine (spec 003) is the only consumer of.
- Open first: `factory/operator/api.py` (CLI dispatcher) and `factory/operator/tests/test_operator_typical_usage.py`.

## ENTRY POINTS
- Main module: `factory/operator/api.py`
- HTTP server entry: `factory/operator/http.py` (FastAPI app, bound to `127.0.0.1`; reachable only by running `factory serve`).
- Typical-usage test: `factory/operator/tests/test_operator_typical_usage.py`
- CLI: `python -m factory.operator --help` *and* the installed console script `factory <subcommand>`.
- Mock-mode examples: `factory --mock-mode status` and `factory --mock-mode serve --port 8765`.
- Runbook: `docs/runbooks/operator-cli.md`

## LOCAL DEBUG
- Mock-mode invocation: `FACTORY_MOCK=1 factory status` (or `factory --mock-mode status`) returns a deterministic snapshot built from `factory/operator/fixtures/`.
- HTTP server in isolation: `factory --mock-mode serve --port 8765`; then `curl http://127.0.0.1:8765/mission_control` returns fixture JSON.
- Bounded live start: `factory start --cycles 3 --daily-cap-usd 5` runs at most 3 cycles before clean shutdown — useful for smoke tests against a real council.
- Verbosity controls: `factory --quiet status` suppresses informational lines; `factory --verbose start` adds DEBUG-level structured events to stderr in addition to the normal stdout stream.
- Config-dir override: `factory --config-dir ./alt_config status` looks up `operator.yaml`, `pricing/openrouter.yaml`, `council/`, etc. under the supplied directory instead of the default `config/`. Equivalent to `FACTORY_CONFIG_DIR=./alt_config factory status`.

### Required environment variables (Phase A)

Per FIX_PLAN §25.6, all LLM access (council + agentic) flows through OpenRouter. The **only** required LLM env var is `OPENROUTER_API_KEY`:

| Variable | Purpose | Required for live mode? |
| :--- | :--- | :--- |
| `OPENROUTER_API_KEY` | Single API key for all LLM access via OpenRouter — council (4 vendors via `openai/gpt-5.5`, `anthropic/claude-opus-4.7`, `google/gemini-3.1-pro-preview`, `x-ai/grok-4.3`) and agentic default (`google/gemini-3.5-flash`). Used by the shared `openai` SDK client (FIX_PLAN §25.2). | yes |
| `OPENALEX_API_KEY` | OpenAlex live literature-discovery API key | yes for live literature discovery |
| `FACTORY_MOCK` | Force mock mode | no |
| `FACTORY_CONFIG_DIR` | Override config dir | no |

The §24-era `GEMINI_FLASH` env var is **removed** (superseded by §25). The legacy per-vendor keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY`) are also not used — there is exactly one LLM key and it is `OPENROUTER_API_KEY`.

`factory serve --port 8765` performs a startup precondition check in live mode: if `OPENROUTER_API_KEY` is unset (and `--mock-mode` / `FACTORY_MOCK=1` is not active), the server logs a `WARN` line `"OPENROUTER_API_KEY not set; live council deliberation and agentic LLM calls will fail"` and continues to boot the read-only HTTP surface. Mock mode never reads `OPENROUTER_API_KEY`.
- Fixture artifacts: `factory/operator/fixtures/` contains one canned response per HTTP endpoint plus an example `FactoryControlEvent`.
- Common error signatures → recovery:
  - `FactoryNotRunning` → start the factory or pass `--mock-mode`; surfaced by every read endpoint that needs live state.
  - `CycleNotFound` → the cycle ID is malformed or the artifact directory has been pruned; check `runs/<cycle-id>/MANIFEST.json`.
  - `AmbiguousHypothesisId` → the short 7-char prefix matched ≥2 ledger entries; pass the full hash.
  - `ApprovalDenied` → G6 rejected; the reason text is required for `reject`; reconsider scope or escalate via C5.
  - `TelemetryUnavailable` → spec 014's event bus is not reachable; HTTP read endpoints degrade to "last-known snapshot" with a stale-flag header.
  - `ConfigurationInvalid` → bad `factory budget set` argument or unknown subcommand option; exits non-zero with usage.
  - `NonLoopbackBindRejected` → `factory serve --host 0.0.0.0` (or any non-loopback address) refused at startup; rerun with `--host 127.0.0.1` (the default) or use SSH port-forwarding for remote access.
- Logs to inspect: every CLI invocation appends to `runs/_operator/operator.jsonl` (structured event per command). HTTP requests log to the same file under `event=http_request`. Control-event artifacts land under `runs/_control/events/<ts>.json` (FIX_PLAN §10).

## DEPENDENCIES
- **Hard:**
  - Spec 001 (Council) — `factory inspect` and `GET /verdicts/<id>` surface `CouncilVerdict`s and `factory council calibrate` runs the calibration probe set.
  - Spec 002 (Artifacts) — every read endpoint returns artifacts (or projections of them); CLI never invents data shapes. `FactoryControlEvent` (artifact #11, FIX_PLAN §1) is the canonical mutation payload.
  - Spec 003 (State Machine) — the only consumer of mutation events (`start`, `stop`, `pause`, `resume`, `approve`, `reject`, `budget set`). The operator interface does **not** transition gates itself; it appends `FactoryControlEvent` artifacts the state machine reads.
  - Spec 012 (EvidenceLedger) — `factory inspect`, `GET /ledger/*`, `GET /reports/*`, `GET /approval_queue` read from the ledger.
  - Spec 013 (Budget) — `factory budget show` and `factory budget set` read/write `Budget` via `BudgetTracker.set_cap(...)` (FIX_PLAN §6.3); never bypass the tracker.
- **Soft:**
  - Spec 014 (Telemetry) — used to stream events for `factory start` / `factory replay` and to feed the live regions of `GET /mission_control`. If unavailable, the CLI falls back to artifact-store polling and HTTP returns a stale-flag header.
  - Spec 004 (Catalog) — `factory catalog onboard <manifest>` calls the catalog onboarding workflow; falls back to mock fixtures until that spec lands.
  - Spec 007 (Literature) — `factory discover --seed <topic>` enqueues a discovery run; falls back to mock when the literature subsystem is offline.
- **Mocks available:** `factory/operator/fixtures/` covers one healthy snapshot per HTTP endpoint plus mock `factory start | status | inspect | approve | reject` outputs. The mock layer is a thin adapter that reads JSON files instead of calling the live subsystems.

---

## 1. Summary

This is the **operator boundary** of the factory: the single tool a human uses to drive a 24/7 autonomous loop. The interface is split deliberately — a CLI for every state-changing command (so the audit log is the shell history plus an `operator.jsonl` event stream plus a stream of `FactoryControlEvent` artifacts) and a localhost-only read-only HTTP server (launched on demand by `factory serve`) that the deferred UI consumes. The split keeps mutations auditable on the command line while letting the UI render rich dashboards without ever owning a write path in Phase A. Phase B will add token-authenticated POST endpoints once the read surface is stable.

## 2. Scope

**In scope (Phase A):**
- A `factory` CLI binary with the following subcommands (canonical surface per FIX_PLAN §9.1):

  ```
  factory start [--seed TOPIC] [--cycles N] [--daily-cap-usd USD] [--mock-mode]
  factory stop
  factory pause
  factory resume
  factory status
  factory inspect <hypothesis-id> [--format text|json]
  factory discover --seed "<topic>"
  factory replay <cycle-id> [--dry-run] [--format text|json] [--mock-mode]
  factory approve <run-report-hash>
  factory reject <run-report-hash> --reason "<text>"
  factory catalog onboard <manifest.yaml>
  factory council calibrate
  factory budget show
  factory budget set --aggregate-usd USD [--per-hypothesis-usd USD] [--daily-usd USD]
  factory serve [--host HOST] [--port PORT]
  ```

  Global flags (apply to every subcommand): `--mock-mode`, `--quiet`, `--verbose`, `--config-dir PATH`.
- A FastAPI HTTP server, started by `factory serve`, bound to `127.0.0.1` only, exposing **read-only** GET endpoints aligned 1-to-1 with the 11 UI screens.
- Streaming of cycle events to stdout for long-running commands (`factory start`, `factory replay`).
- Mock mode for every CLI subcommand and every HTTP endpoint, backed by fixtures.
- Structured per-command event logging (`runs/_operator/operator.jsonl`) plus per-mutation `FactoryControlEvent` artifacts under `runs/_control/events/`.
- Configuration loader (CLI flags > env vars > `config/operator.yaml` > defaults) with `--config-dir` / `FACTORY_CONFIG_DIR` honoring the same precedence.
- Failure-mode taxonomy with `FactoryError` subclasses and clean non-zero exit codes.
- Startup check that refuses any non-loopback bind in Phase A (raises `NonLoopbackBindRejected`).

**Out of scope:**
- Web UI rendering. The UI is *frontend* work driven by `UI_DESIGN.md` and consumes this spec's HTTP surface; it lives in a separate repo or directory and is **not** implemented here.
- HTTP write endpoints. Mutations are CLI-only in Phase A; Phase B adds authenticated POSTs.
- Multi-user auth / RBAC. Phase A is single-operator localhost only.
- Network exposure beyond `127.0.0.1`. Phase B adds token auth before any non-loopback bind is permitted.
- WebSocket / SSE streaming over HTTP (CLI streams via stdout in Phase A; HTTP returns snapshots).
- A `per_cycle` budget tier — Phase A has only `aggregate`, `per_hypothesis`, and `per_day` (FIX_PLAN §6.2).

## 3. Public Interface

```python
# factory/operator/api.py — CLI dispatch surface
# Every command accepts the four global flags: --mock-mode, --quiet, --verbose,
# --config-dir <path>. The handler bodies are TODO; signatures below are canonical.

from pathlib import Path
from typing import Literal
from factory.artifacts import (
    HypothesisId, CycleId, ArtifactHash, Budget, RunReport, FactoryControlEvent,
)

class OperatorError(FactoryError): ...
class FactoryNotRunning(OperatorError): ...
class CycleNotFound(OperatorError): ...
class AmbiguousHypothesisId(OperatorError): ...
class ApprovalDenied(OperatorError): ...
class TelemetryUnavailable(OperatorError): ...
class ConfigurationInvalid(OperatorError): ...
class NonLoopbackBindRejected(OperatorError): ...

# CLI entry points (Typer/Click app) — TODO: implement bodies.
def cmd_start(
    seed: str | None,
    cycles: int | None,
    daily_cap_usd: float | None,
    mock_mode: bool,
) -> int: ...
def cmd_stop() -> int: ...
def cmd_pause() -> int: ...
def cmd_resume() -> int: ...
def cmd_status(format: Literal["text", "json"] = "text") -> int: ...
def cmd_inspect(
    hypothesis_id: HypothesisId,
    format: Literal["text", "json"] = "text",
) -> int: ...
def cmd_discover(seed: str) -> int: ...
def cmd_replay(
    cycle_id: CycleId,
    dry_run: bool,
    format: Literal["text", "json"],
    mock_mode: bool,
) -> int: ...
def cmd_approve(run_report_hash: ArtifactHash) -> int: ...
def cmd_reject(run_report_hash: ArtifactHash, reason: str) -> int: ...
def cmd_catalog_onboard(manifest_path: Path) -> int: ...
def cmd_council_calibrate() -> int: ...
def cmd_budget_show(format: Literal["text", "json"] = "text") -> int: ...
def cmd_budget_set(
    aggregate_usd: float | None,
    per_hypothesis_usd: float | None,
    daily_usd: float | None,
) -> int: ...
def cmd_serve(host: str = "127.0.0.1", port: int = 8765) -> int: ...
```

Notes on signatures:
- `cmd_approve` / `cmd_reject` parameter is named `run_report_hash` and typed as `ArtifactHash` — it is the content hash of the `RunReport` artifact, not a free-form id. The CLI surface still spells the argument `<run-report-hash>` for the operator (FIX_PLAN §9.1).
- `cmd_budget_set` does **not** accept a `per_cycle_usd` argument. The three valid tiers are `aggregate`, `per_hypothesis`, and `per_day` (FIX_PLAN §6.2). Each non-`None` argument writes one `FactoryControlEvent` and one `BudgetTracker.set_cap(...)` call.
- `cmd_serve` is the only handler whose primary effect is to keep the process alive: it starts the FastAPI app under uvicorn bound to `host:port` and blocks until SIGINT/SIGTERM. The host defaults to `127.0.0.1`; any non-loopback value triggers `NonLoopbackBindRejected` before the socket is opened.
- `cmd_start` accepts `cycles: int | None` — when `None` (the default), the factory runs until externally stopped; when an integer N≥1, the state machine halts cleanly after the N-th cycle terminates.

```python
# factory/operator/http.py — FastAPI read-only API (Phase A)
# TODO: implement endpoints; each returns a Pydantic projection of one or more artifacts.

from fastapi import FastAPI
app = FastAPI(title="Factory Operator API (read-only, Phase A)")

# Endpoints (1-to-1 with the 11 UI screens in UI_DESIGN.md):
# GET /mission_control                -> screen 1
# GET /cycles/<cycle_id>              -> screen 4 (hypothesis detail) + screen 5 (runner)
# GET /cycles/<cycle_id>/gates        -> screen 2 (gate pipeline view)
# GET /verdicts/<session_id>          -> screen 3 (council deliberation)
# GET /catalog                        -> screen 6 (master pane)
# GET /catalog/<simulator_id>         -> screen 6 (detail pane)
# GET /ledger/search?q=...&filters... -> screen 7 (browser)
# GET /ledger/<entry_id>              -> screen 7 (detail slide-over)
# GET /reports/<report_id>            -> screen 8 (RunReport reader)
# GET /approval_queue                 -> screen 9 (G6 queue)
# GET /literature/<run_id>            -> screen 10 (graph view)
# GET /settings                       -> screen 11 (read-only snapshot of current config)
```

The HTTP surface returns Pydantic response models that are *projections* of typed artifacts (spec 002) — never raw dicts. Every response includes a `stale: bool` flag and a `served_at` ISO timestamp so the UI can label data freshness. The server itself is launched only via `factory serve`; importing `factory.operator.http` does not bind a socket.

## 4. Data Structures / Schemas

- `FactoryControlEvent` (artifact #11 in the canonical registry, FIX_PLAN §1) — captures every state-changing CLI invocation: `{ts, command, args, actor, reason?, artifact_refs[]}`. Persisted to `runs/_control/events/<ts>.json` (FIX_PLAN §10). The state machine (spec 003) consumes these and produces `EvidenceLedgerEntry` audit links.
- HTTP response projections live in `factory/operator/responses.py` (Pydantic models, frozen). Each projection has a stable schema that the UI can bind to without leaking artifact-internal fields.
- Configuration schema (`config/operator.yaml`): default daily cap, HTTP host/port defaults consumed by `factory serve`, log retention, mock-mode default-off, telemetry endpoint, verbosity defaults.
- TODO: enumerate the projection model for every endpoint with exact fields, including pagination envelopes for `/ledger/search` and `/approval_queue`.

## 5. Algorithms / Logic

### 5.1 CLI dispatch
- A single Typer/Click app routes subcommands to handler functions. Each handler:
  1. Loads config (file → env → flags merge). `--config-dir` / `FACTORY_CONFIG_DIR` selects the root directory; missing files trigger `ConfigurationInvalid`.
  2. Applies the verbosity globals: `--quiet` suppresses non-error stdout lines; `--verbose` raises the log level to DEBUG. The two flags are mutually exclusive; specifying both is `ConfigurationInvalid`.
  3. Resolves mock vs. live mode (`--mock-mode` flag, `FACTORY_MOCK` env, or config default — in that precedence).
  4. Validates inputs against artifact schemas where applicable (e.g., `run_report_hash` must satisfy `ArtifactHash._PATTERN`, FIX_PLAN §13).
  5. For mutations, writes a `FactoryControlEvent` then notifies the state machine via the telemetry bus.
  6. For reads, calls the right module's public API (ledger / budget / catalog / council).
  7. Emits a structured event to `operator.jsonl` regardless of success.
- Exit codes: `0` success, `2` configuration error, `3` factory-state error (not running, etc.), `4` validation error, `5` approval denied, `6` non-loopback bind rejected, `1` for any other `FactoryError`.

### 5.2 HTTP read endpoints
- FastAPI app bound to `127.0.0.1` only. `factory serve` performs a startup check that the parsed host is in `{"127.0.0.1", "localhost", "::1"}`; anything else raises `NonLoopbackBindRejected` before `uvicorn.run(...)` is invoked. The CLI returns exit code 6 and writes a `FactoryControlEvent` recording the rejected bind attempt for audit.
- Each endpoint is a thin adapter: read artifacts, project to response model, return.
- The endpoint never writes; if a downstream module requires write side effects to answer a read, the endpoint returns `503 TelemetryUnavailable` rather than silently mutating state.

### 5.3 Streaming for long-running CLI
- `factory start` and `factory replay` subscribe to the telemetry event bus (spec 014) and tee structured events to stdout (JSONL by default; `--format pretty` for human-readable). On SIGINT the CLI emits a `pause` event and exits cleanly.
- `factory start --cycles N` registers an upper bound on cycle count; after the N-th cycle's terminal event, the CLI emits a `stop` `FactoryControlEvent` and exits 0. If no `--cycles` value is given the run is unbounded.

### 5.4 Hypothesis ID resolution
- All ID arguments accept the 7-char prefix used in the UI. The CLI first looks up the ledger; if exactly one match, proceeds; if ≥2, raises `AmbiguousHypothesisId` with the candidate list.

### 5.5 Approval / rejection workflow
- `factory approve <run-report-hash>` requires interactive confirmation (`--yes` opt-out for scripted use) and records the approver username. `factory reject` requires `--reason` non-empty; reasons under 20 chars trigger a prompt before exit. Both paths route the validated `ArtifactHash` through the typed `cmd_approve` / `cmd_reject` handlers.

### 5.6 Budget mutation
- `factory budget set` accepts any combination of `--aggregate-usd`, `--per-hypothesis-usd`, `--daily-usd`. The handler resolves the `BudgetTracker` from spec 013 and invokes `tracker.set_cap(tier=..., dollars=...)` once per provided flag, then appends a single `FactoryControlEvent` enumerating the applied caps. There is intentionally no `--per-cycle-usd` flag (FIX_PLAN §6.2).

### 5.7 Council calibration (`factory council calibrate`)
- Runs the calibration probe set against the **4-vendor OpenRouter lineup** defined in `config/council/lineup.yaml` (FIX_PLAN §25.3 / §25.4) — one call per vendor: `openai/gpt-5.5`, `anthropic/claude-opus-4.7`, `google/gemini-3.1-pro-preview`, `x-ai/grok-4.3`. Each call carries a persona assignment (Visionary / Pessimist / Pragmatist) per the lineup config.
- The acceptance threshold is the restored target: overall disagreement-rate ≥ **0.40** (FIX_PLAN §25.4 — restored from §24's lowered 0.25). The empirical floor for the redesign-trigger is the pre-§24 value as documented in PRD-002.
- The handler reads `OPENROUTER_API_KEY` from the environment (unless `--mock-mode` is active) and writes a `FactoryControlEvent` plus a calibration report to `runs/_calibration/<ts>/report.json` (FIX_PLAN §10). A report below the empirical floor exits non-zero and prints the redesign-trigger banner. A single-vendor failure inside the lineup (any of the 4 OpenRouter vendors unreachable) is a fail — vendor heterogeneity IS the sycophancy defense (§25.3 invariant).

### 5.8 `factory serve` startup preconditions
- Before binding the loopback socket, `cmd_serve` enforces:
  1. Loopback host check (raises `NonLoopbackBindRejected` for non-loopback hosts — §5.2).
  2. **Live-mode env-var check**: if not in mock mode and `OPENROUTER_API_KEY` is absent from the environment, emit a `WARN` event to `operator.jsonl` (`event=openrouter_api_key_missing`) and a stderr banner (FIX_PLAN §25.6). The server continues to boot the read-only HTTP surface; any downstream call that requires an LLM (council deliberation, code-gen, RAG drafting) will fail loudly at request time rather than at startup.

TODO: detail concurrency model (single CLI process + single `factory serve` process; multi-CLI safety is doc-only), detail the SIGTERM grace period for `factory stop`, detail rate limiting on `discover` / `catalog onboard`.

## 6. Failure Modes

| Error class | When it fires | Recovery action |
| :--- | :--- | :--- |
| `FactoryNotRunning(OperatorError)` | Read endpoint or `stop/pause/resume` invoked while state machine reports idle | Exit 3 with hint; pass `--mock-mode` for offline inspection |
| `CycleNotFound(OperatorError)` | Cycle ID unknown or `runs/<cycle-id>/` pruned | Exit 4; suggest `factory status` to list active cycles |
| `AmbiguousHypothesisId(OperatorError)` | Prefix matches >1 ledger entry | Exit 4; print candidates with their first divergent byte |
| `ApprovalDenied(OperatorError)` | G6 reject committed; subsequent approve attempts on same RunReport | Exit 5; require explicit `--re-litigate` flag and a C5 verdict reference |
| `TelemetryUnavailable(OperatorError)` | Event bus down; HTTP returns 503; CLI streams stale snapshot with banner | Restart telemetry or pass `--mock-mode`; reads degrade, mutations refuse |
| `ConfigurationInvalid(OperatorError)` | Bad flag combination, missing file, schema violation, `--quiet` + `--verbose` together | Exit 2 with full usage; never partial-apply config |
| `NonLoopbackBindRejected(OperatorError)` | `factory serve` invoked with `--host` outside `{127.0.0.1, localhost, ::1}` | Exit 6; rerun with the default loopback host or tunnel via SSH; the rejected attempt is recorded as a `FactoryControlEvent` |

## 7. Testing

**Mock-mode unit tests** (`factory/operator/tests/`):
- `test_operator_typical_usage.py` — REQUIRED. Runs `factory status`, `factory inspect <fixture-id>`, `factory budget show`, and one HTTP `GET /mission_control` (against `factory --mock-mode serve` started in-process) against the fixture set.
- `test_cli_dispatch.py` — every subcommand parses correctly and returns the right exit code under fixture conditions; covers all four global flags.
- `test_http_readonly.py` — every endpoint returns 200 with mock data; verifies no endpoint accepts POST/PUT/DELETE in Phase A.
- `test_failure_modes.py` — each error class is raised under its triggering condition and produces the right exit code, including `NonLoopbackBindRejected` for `factory serve --host 0.0.0.0`.
- `test_mutation_event_emission.py` — `pause`, `resume`, `approve`, `reject`, `budget set`, `catalog onboard`, and a rejected `serve` bind each append a `FactoryControlEvent` to `runs/_control/events/`.

**Live-mode tests** (`@pytest.mark.live`):
- `test_live_start_stop.py` — starts the factory with `--cycles 1`, asserts a cycle event reaches stdout, stops cleanly.
- `test_live_approval_round_trip.py` — approves a fixture RunReport (by content hash) and verifies the ledger reflects the G6 status change.

**Acceptance:**
- `factory --help` enumerates every subcommand listed in §2 including `serve`.
- The HTTP server (launched by `factory --mock-mode serve`) boots in <2 s and responds to all 11 endpoints in mock mode.
- A fresh-context agent can run the mock-mode example from a clean checkout in <5 minutes.

## 8. Performance & Budget

- CLI startup target: <300 ms cold start in mock mode (no live deps).
- HTTP read latency target: p95 <100 ms for cached projections, <500 ms when touching the ledger.
- HTTP server memory ceiling: <200 MB resident; if the UI demands richer queries, add caching not threads.
- Streaming throughput: must keep up with telemetry firehose at 100 events/sec without back-pressuring the bus.
- Mutation cost: each mutation writes one `FactoryControlEvent` file (<1 KB) and one ledger row; no LLM calls in the operator layer ever.

## 9. Open Questions

- Should `factory replay <cycle-id>` re-execute the full cycle deterministically (requires sandbox + simulator) or only re-render artifacts? Phase A leans toward re-render only (the default `--dry-run` posture); re-execute is a Phase B feature.
- HTTP auth in Phase B: bearer token issued by `factory token issue`, with rotation and scope-per-endpoint (read vs. approve) — needs an RFC before implementation.
- WebSocket vs. SSE for UI live updates in Phase B — defer until the UI has measured latency needs.
- Multi-operator safety: today the CLI assumes one human at a time. Adding a file lock on `runs/_control/` is cheap insurance but not yet specified.
- How to surface `council calibrate` results: structured JSON vs. a rendered report? Probably both, behind `--format`.

## 10. TODO Checklist

- [ ] Scaffold `factory/operator/` from the canonical module template (api.py, http.py, mock.py, errors.py, cli.py, types.py).
- [ ] Define Typer/Click app with all 15 subcommands listed in §2 (including `factory serve`) and the four global flags (`--mock-mode`, `--quiet`, `--verbose`, `--config-dir`).
- [ ] Wire `--cycles N` into `cmd_start` and into the state machine's stop-after-N hook.
- [ ] Implement `cmd_serve` with the loopback startup check that raises `NonLoopbackBindRejected` for non-loopback hosts.
- [ ] Implement `cmd_serve` live-mode precondition that warns (does not fail) when `OPENROUTER_API_KEY` is absent (FIX_PLAN §25.6); cover with a unit test.
- [ ] Implement `cmd_council_calibrate` against the 4-vendor OpenRouter lineup (FIX_PLAN §25.3) with disagreement-rate threshold ≥ 0.40 (restored from §24's lowered 0.25) and empirical-floor exit code per FIX_PLAN §25.4.
- [ ] Implement Pydantic projection models for every HTTP endpoint in `factory/operator/responses.py`.
- [ ] Implement read endpoints against fixture data first; wire to live modules behind a `mode="live"` flag.
- [ ] Implement `FactoryControlEvent` writer + telemetry-bus notify path for every mutation, including the rejected-bind audit case.
- [ ] Implement structured `operator.jsonl` logger covering every CLI invocation and every HTTP request, honoring `--quiet` / `--verbose`.
- [ ] Implement streaming subscriber for `factory start | replay` (subscribe to spec 014 event bus; tee to stdout).
- [ ] Build the fixture set in `factory/operator/fixtures/` — one canned response per endpoint plus a fixture `RunReport` for the approval flow.
- [ ] Write `factory/operator/cli.py` console-script entry registered in `pyproject.toml` as `factory = factory.operator.cli:main`.
- [ ] Write 5 mock-mode tests listed in §7 plus the 2 live-mode tests under the `@pytest.mark.live` marker.
- [ ] Write `docs/runbooks/operator-cli.md` covering: start in mock mode, inspect the fixture cycle, approve the fixture RunReport, stop.
- [ ] Verify `mypy --strict factory/operator/` passes.
- [ ] Verify `factory --mock-mode status` works on a fresh checkout (architectural invariant §1.1).
- [ ] Verify `factory --mock-mode serve` refuses non-loopback binds in Phase A (startup check + dedicated test).
