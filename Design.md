# AI Co-Computational Physicist Factory — Design Document

This document outlines the architecture, data models, workflows, and core features of the autonomous co-computational physicist factory (Phase A MVP).

---

## 1. System Architecture Overview

The co-computational physicist factory is structured as a modular suite of Python packages under the `factory/` package. The orchestration and lifecycle are governed by a state machine that drives candidate hypotheses through successive evaluation, validation, simulation, and publication gates.

```
                  +-----------------------------------+
                  |        Operator CLI / Daemon      |
                  +-----------------+-----------------+
                                    |
                                    v
                  +-----------------+-----------------+
                  |       Gate State Machine          |
                  +-----------------+-----------------+
                                    |
            +-----------------------+-----------------------+
            |                       |                       |
            v                       v                       v
     +------+------+         +------+------+         +------+------+
     | Literature  |         |   Council   |         | Generator-  |
     | Discovery & |         | Deliberation|         |  Verifier   |
     | Gap Mining  |         |   Engine    |         | (GenVer)    |
     +-------------+         +-------------+         +-------------+
            |                       |                       |
            v                       v                       v
     +------+------+         +------+------+         +------+------+
     |  Simulator  |         |   Strategy  |         | Verification|
     | Catalog &   |         |   Archive   |         |     &      |
     | Selector    |         |  (Bayesian) |         | Validation  |
     +-------------+         +-------------+         +-------------+
            |                       |                       |
            +-----------------------+-----------------------+
                                    |
                                    v
                  +-----------------+-----------------+
                  |  Ledger, Budget, and Telemetry    |
                  +-----------------------------------+
```

---

## 2. Core Modules and Features

### 2.1 Artifacts (`factory/artifacts`)
- **Purpose**: Defines the typed, immutable, and self-verifying schemas representing inputs, intermediate states, and outputs of the factory.
- **Key Schemas**:
  - `GapCandidate`: Scraped/analyzed gap in literature.
  - `HypothesisSpec`: The proposed physics model (`if_then`, metrics, expected effects).
  - `CouncilVerdict`: Preserves consensus and minority opinions.
  - `ExperimentSpec`: Set of simulators, controls, and fidelity tiers.
  - `Budget`: Immutable ledger tracking resource limits.
  - `DomainScope`: Scopes allowed simulator types and physical regimes.
  - `EvidenceLedgerEntry`: Permanent record of experiment outcomes.
  - `RunReport`: The compiled LaTeX research paper.
- **Key Invariant**: Deep immutability (uses `tuple` and `frozenset` instead of `list` and `set`).
- **Deduplication Utility (`factory/artifacts/dedup.py`)**:
  - Implements global cross-cycle content-addressed storage of artifacts under a shared directory (`runs/_global_artifacts/`).
  - Automatically verifies artifact types and schemas against cryptographic hashes before registration.
  - Links cycle-specific artifact paths to the global store using relative symbolic links, falling back to hard links or direct copies where necessary.
  - Supports configurable environment variable controls and test overrides to execute scripts without altering production data.
- **Compression Utility (`factory/artifacts/compression.py`)**:
  - Implements gzip and zstd stream compression utilities for artifacts-at-rest.
  - Transparently compresses and decompresses raw bytes using `gzip`, `zstd`, or `raw` formats.
  - Automatically detects the compression method when reading artifacts from disk, using either file signature magic bytes or file extension fallbacks.
  - Provides graceful fallback to standard library `gzip` if the `zstandard` module is not installed.
  - Retains backward-compatible StrEnum-based signatures and path-based compression helpers.


### 2.2 LLM Client (`factory/llm_client`)
- **Purpose**: Unified interface to remote frontier LLMs via OpenRouter, utilizing `google/gemini-3.5-flash` for agentic turn loops and four heterogeneous models for council deliberations.
- **Key Components**:
  - `OpenRouterClient`: Manages authentication, network request retry logic, and parses prompt/completion token usage.
  - `RateLimitedDecisionClient`: Enforces strict calls per second and token rate throttling.
  - `FileClient`: Replays canned mock response fixtures for isolated offline tests.
  - Cost tracking matches prices derived from `config/pricing/openrouter.yaml`.

### 2.3 Budget Tracker (`factory/budget`)
- **Purpose**: Enforces resource allocation limits (USD, tokens, wall-clock time, and iterations) on three levels: per-hypothesis, daily rolling UTC window, and program-wide aggregate.
- **Key Features**:
  - Proactive `check_and_deduct` before expensive steps.
  - Record-after-commit tracking of actual vendor-reported token costs.
  - Program aggregate halt sentinel created at `runs/_control/HALT_AGGREGATE_CAP` to block all concurrent actions if breached.

### 2.4 Telemetry (`factory/telemetry`)
- **Purpose**: Structured, thread-safe, and append-only logging of lifecycle events.
- **Key Features**:
  - `EventRegistry`: Dynamically discovers event taxonomies defined in each module's `events.py`.
  - `TelemetryEmitter`: Thread-safe file writer with `fcntl`-based advisory locks on the cycle log.
  - `AuditQuery`: SQLite-backed query engine for real-time validation and metrics aggregation (calculating sycophancy, dollar burn, and OOD frequency).

### 2.5 Simulator Catalog and Selector (`factory/catalog` & `factory/selector`)
- **Purpose**: Manages available open-source simulators, performs static compatibility checking, and selects simulators for experiments.
- **Key Features**:
  - Transitive SPDX license auditor scanning LICENSE texts.
  - Reproducible container recipe build integrity validations.
  - Cost/fidelity compatibility scoring matching a hypothesis's target observables.
  - **Simulator Selector (`factory/selector/api.py`)**:
    - **Compatibility Filter**: Resolves `measurable_metric` against simulator capabilities via direct matches, equivalence mappings, and capability-superset matches, filtering out license-failed or disabled simulators.
    - **Multi-Criteria Scoring**: Evaluates candidates based on weighted capability match, license compliance, cost estimation, cross-simulator availability, and commit freshness.
    - **Cost Estimation**: Calibrates expected runtime using historical telemetry if available, falling back to manifest defaults or static fallback runtimes.
    - **Maintenance Freshness**: Soft decay signal based on the commit recency within a 24-month window relative to the hypothesis creation date.
    - **Ambiguity Ties**: Detects near-ties within an `ambiguity_epsilon` threshold and forwards them for downstream council resolution.
    - **Deterministic Tie-Breaking**: Ranks candidates deterministically using score descending and `simulator_id` lexicographically ascending.

### 2.6 Deliberation Council (`factory/council`)
- **Purpose**: Multi-LLM peer review and quality gate keeping.
- **Key Features**:
  - Three-stage protocol: First opinions, anonymized cross-critique, and chairman synthesis.
  - Preserves dissenting views to prevent consensus bias.
  - Calibrates sycophancy via periodic probe queries.
  - **Chairman Management (`factory/council/chairman.py`)**:
    - **Selection Policies**: Supports `random`, deterministic `round_robin` (replayable across cycles), and `weighted_by_cost` (inversely weighted by output cost using values from `config/pricing/openrouter.yaml`).
    - **NLI Dissent Omission Verification**: Employs `cross-encoder/nli-deberta-v3-base` locally (on CPU/MPS) to identify "material dissent" (contradiction vs majority view, P >= 0.60) and ensures each is semantically represented in the preserved dissents list via semantic-entailment checks. Includes a robust fallback heuristic to mock mode if the model is missing.
    - **Auto Re-Prompting**: Re-prompts the chairman once with the verbatim text of omitted dissents to correct synthesis omission.

### 2.7 Strategy Archive (`factory/strategy`)
- **Purpose**: Evaluates candidate strategies to prioritize high-novelty directions.
- **Key Features**:
  - Computes Bayesian Surprise (KL divergence of Beta and Dirichlet distributions).
  - Novelty search space partitions via MAP-Elites descriptors.
  - Selection guided by Upper Confidence Bound for Trees (UCT).
  - **Strategy Selection (`factory/strategy/selection.py`)**:
    - **Convex UCT Scoring**: Evaluates candidates by normalising reward, surprise, and feasibility pressure (or feasibility distance as a proxy in cold-start).
    - **Behavior Novelty**: Applies a novelty bonus calculated using average cosine distance to the 4 nearest neighbors in behavior space.
    - **Child Penalty**: Prefers leaf nodes by dividing scores by `1 / (1 + child_count)`.
    - **MAP-Elites Diversity Sweep**: Filters elites per cell partition before pulling from the remaining archive.
    - **Deterministic Tie-Breaking**: Guarantees reproducibility by resolving equivalent-score candidates lexicographically by SHA ascending.
    - **Automatic Padding**: Fills under-sized selections up to `k` with `novel:<index>` tokens.

### 2.8 Solver Adapters (`factory/adapter`)
- **Purpose**: Decouples generator-verifier logic from simulator-specific configurations.
- **Key Features**:
  - The 6 abstract solver blocks: `Discretizer`, `ConstraintAggregator`, `UpdateStepOperator`, `AcceptanceController`, `RestartController`, `LocalPolisher`.
  - Simulators Sim A and Sim B implement concrete translations of these abstract operations.

### 2.9 Generator-Verifier (`factory/genver`)
- **Purpose**: Autonomous code-mutation loop trying to optimize computational physicist routines.
- **Key Features**:
  - ReAct agent loop limited to a maximum of 25 turns.
  - Bounded tool surface (e.g. `write_notes`, `query_db`, AST checks).
  - Context compaction summarizing prior turns when tokens near limits.

### 2.10 Physics Validation Portfolio (`factory/validation`)
- **Purpose**: Strictly verifies the physical correctness and numerical sanity of generated solvers.
- **Key Features**:
  - Physics conservation residual tests ($\nabla \cdot \mathbf{B} = 0$, energy conservation).
  - Grid/mesh refinement convergence (via Richardson Extrapolation).
  - Cross-simulator validation against alternate catalog simulators.

### 2.11 Surrogate Probes (`factory/surrogate`)
- **Purpose**: Pre-screens candidates with a cheap proxy model before running heavy simulations.
- **Key Features**:
  - kNN distances in PCA-reduced feature space detect Out-Of-Distribution (OOD) queries, escalating OOD samples to full simulation.

### 2.12 Multi-Fidelity Scheduler (`factory/fidelity`)
- **Purpose**: Runs cheap, low-fidelity tests first and escalates promising designs to high-fidelity oracle runs.
- **Key Features**:
  - Traversal engine driving candidates up the ladder.
  - Early termination if progress is slower than expectations.

### 2.13 Literature and Writing (`factory/literature` & `factory/writer`)
- **Purpose**: Interfaces with external academic databases to find gaps and compile paper reports.
- **Key Features**:
  - OpenAlex citation-graph traversal.
  - OCR document indexing and RAG prompt compilation.
  - LaTeX compiler for final PDF reports.

### 2.14 Operator and State Machine (`factory/state_machine` & `factory/operator`)
- **Purpose**: Coordinates gates and exposes human interaction boundaries.
- **Key Features**:
  - State machine routing (G0 to G6) and weekly C5 cadence schedules.
  - Operator CLI and local HTTP daemon.

### 2.15 Reusable UI Component Library (`ui/src/components/`)
- **Purpose**: Implements visual building blocks for the co-computational physicist operations console. Ensures typographic and styling alignment with the design system (Linear/Datadog-adjacent dark mode).
- **Key Components**:
  - [theme.ts](file:///Users/suhjungdae/code/2026_google/ui/src/components/theme.ts): Configures core color tokens, typography settings (Inter and JetBrains Mono), custom padding margins, and defines `logUIAction` for tracing UI events.
  - [StatusPill.tsx](file:///Users/suhjungdae/code/2026_google/ui/src/components/StatusPill.tsx): Renders small, rectangular 2px corner pills for status outputs (`passed`, `failed`, `pending`, `running`, `dissent`, `qualified`, `parked`) with interaction logs.
  - [PipelineVisual.tsx](file:///Users/suhjungdae/code/2026_google/ui/src/components/PipelineVisual.tsx): Renders the horizontal 9-gate tracker (G0 to G6) with status-aware connecting lines, active gate cyan vertical accent highlight, and compact status tags.
  - [LiveLogStream.tsx](file:///Users/suhjungdae/code/2026_google/ui/src/components/LiveLogStream.tsx): Displays terminal-style stdout logs with level filter tabs (All, Info, Warn, Error), scroll-lock toggle, matching search filters, and log file downloading.
  - [Sparkline.tsx](file:///Users/suhjungdae/code/2026_google/ui/src/components/Sparkline.tsx): High-performance responsive SVG sparkline charts containing zero gridlines, threshold-exceeding highlight dots, linear background gradients, and interactive hover tooltips.
  - [ComponentShowcase.tsx](file:///Users/suhjungdae/code/2026_google/ui/src/components/ComponentShowcase.tsx): A Storybook-like visual test page rendering all UI blocks across their distinct states and interactions without altering production data.
2.16 Dashboard Views (`ui/src/views/`)
- **Purpose**: Implements the main dashboard view panels for monitoring and managing the research factory runs.
- **Views**:
  - [MissionControl.tsx](file:///Users/suhjungdae/code/2026_google/ui/src/views/MissionControl.tsx): Home dashboard showing active state-machine cycles (timer, mini gate-pipeline indicators), recent verdicts list with inline expandable preserved dissent blocks, and custom CSS-based sparklines/heatmaps monitoring sycophancy risk and budgets.
  - [DeliberationView.tsx](file:///Users/suhjungdae/code/2026_google/ui/src/views/DeliberationView.tsx): High-fidelity council deliberation viewer showing Stage 1 (opinions drafting), Stage 2 (anonymized cross-critique matrix with Identity Reveal toggle), and Stage 3 (consensus synthesis and violet-left-bordered preserved dissents).
  - [RunReportReader.tsx](file:///Users/suhjungdae/code/2026_google/ui/src/views/RunReportReader.tsx): Preprint manuscript journal-style viewer featuring physics stats metadata, line-numbered expandable LaTeX code reader, and human sign-off G6 Approve/Reject controls.
  - [Settings.tsx](file:///Users/suhjungdae/code/2026_google/ui/src/views/Settings.tsx): Configuration dashboard displaying budget caps (daily/aggregate), token limits, and multi-model lineup assignments. Includes warnings if active models fall below 3 (weak consensus threat).

---

## 3. Configurable Items

All configuration is externalized under standard yaml files:
- `config/budget.yaml`: Holds default cap definitions and halt toggles.
- `config/pricing/openrouter.yaml`: Defines prices for the five supported OpenRouter model endpoints.

---

## 4. Dark-Mode User Interface & Design System

The operator-facing interface is styled using a custom, high-density CSS design system defined in `ui/src/index.css`.

### 4.1 Design System Tokens & Properties
- **Base Colors**: Near-black background (`#0A0A0B`), primary off-white text (`#EDEDED`), with secondary and tertiary text at 60% and 40% opacity respectively.
- **Surface Elevation Levels**:
  - `surface-1` (`#111114`): Lowest elevation surfaces.
  - `surface-2` (`#161619`): Mid-level elevation surfaces.
  - `surface-3` (`#1C1C20`): Highest elevation surfaces.
- **Accent**: Muted electric cyan accent (`#4EC9D6`).
- **Status Colors**: Reserved strictly for state:
  - Pass/status green (`#3DDC97`)
  - Fail red (`#FF5C5C`)
  - Pending amber (`#FFB84D`)
  - In-progress steel blue (`#5B9BD5`)
  - Dissent violet (`#A78BFA`) (also used for parked states).

### 4.2 Typography & Elements
- **Inter Font**: Default for sans-serif body and UI elements (13px default body size).
- **JetBrains Mono Font**: Monospace font for IDs, hashes, numeric tabular values, code blocks, and equations.
- **Strict Constraints**: Max 4px border radius for containers/buttons (no rounded/pill buttons); strict 2px border radius for status pills. No soft gradients or drop shadows are allowed; depth is indicated strictly via borders and elevations.

### 4.3 Core Components
- **Status Pills (`.status-pill`)**: small, rectangular status blocks with strict 2px corner radius and appropriate state colors.
- **Copyable Code Blocks (`.code-block`)**: monospace content wrappers featuring headers with copyable IDs and action buttons.
- **Dense Tables (`.dense-table`)**: space-efficient tabular layout with sticky headers, per-column text-overflow cropping, and row-hover highlighting.
- **Custom Scrollbars (`.custom-scrollbar`)**: custom thin, dark-themed scroll handles that match the elevation colors.
- **Council Deliberation & Dissent Layouts**: split columns and specialized dissent cards with violet left borders to highlight minority opinions.

