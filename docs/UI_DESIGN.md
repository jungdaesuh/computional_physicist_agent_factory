# AI Co-Computational Physicist Factory: UI Design Prompts

These prompts produce the operator-facing surfaces for the autonomous physics factory specified in `SPEC.md`. Eleven screens total. Each is self-contained — paste into your design generator independently. The Global Design System prompt should be pasted **first** in each session so style stays consistent across screens.

The factory is a researcher's tool, not a consumer product. Information density is medium-high — closer to a lab notebook crossed with a mission-control console crossed with an IDE. The aesthetic must NOT look like a generic AI product (no purple/blue gradient backgrounds, no glassmorphism, no rounded-corner-everything, no decorative emoji). It should look like an operations console for a real lab.

---

## 0. Global Design System Prompt

> Design a dark-mode operations console for an autonomous research factory called the AI Co-Computational Physicist. The product is used by a single researcher operating a 24/7 hypothesis-to-paper pipeline. The aesthetic is dense, keyboard-driven, and code-adjacent — like a developer tools dashboard or an observability console. The product must not look like a typical AI consumer app — avoid purple-to-blue gradients, glassmorphism, soft pastel backgrounds, generic line-drawing illustrations, and any decorative AI iconography (no sparkles, no orbs, no robot avatars).
>
> Palette: near-black background (#0A0A0B), surface elevation in three steps (#111114, #161619, #1C1C20), primary text off-white (#EDEDED), secondary text 60% opacity, tertiary text 40%. Accent for primary actions is a muted electric cyan (#4EC9D6). Status colors are reserved for state, never decoration: pass green (#3DDC97), fail red (#FF5C5C), pending amber (#FFB84D), in-progress steel blue (#5B9BD5), and a distinct dissent violet (#A78BFA) used wherever a council minority view appears — dissent must visually stand apart from "fail."
>
> Typography: Inter for sans-serif body and UI, JetBrains Mono for IDs / hashes / numeric values / code / equations. Equation rendering uses KaTeX. Tabular numbers everywhere. Font sizes step 12 / 13 / 14 / 16 / 20 / 28; the default body is 13.
>
> Components: dense data tables with sticky headers and per-column filtering; status pills (small, rectangular, 2px corner radius, never pill-shaped); cards with 1px borders not shadows; segmented controls instead of dropdowns where ≤ 4 options; code blocks with copyable IDs; sparklines and small multiples instead of large dashboard widgets. Iconography is line-only, 16px or 20px, no fills. Corner radius is 4px maximum throughout. No drop shadows; rely on borders and surface elevation.
>
> Interaction: keyboard-first. Every list supports j/k navigation, every detail view supports ⌘K command palette, every long-running operation streams logs inline. Loading uses skeleton rows, not spinners. Empty states are one short sentence + the action to populate it.
>
> Information principles: provenance is always visible (content hashes shown as 7-char prefixes, hover for full); uncertainty is always shown next to point estimates; council dissent is never hidden behind a "show more" — it sits next to the majority view in equal visual weight. Costs and budgets surface prominently on any screen where a run could be initiated.

---

## 1. Mission Control (Home)

> Design the home screen of a 24/7 autonomous physics research factory called Mission Control. The user is a single researcher checking in on continuous operations. The screen has four regions stacked top-to-bottom on a single scrollable page.
>
> Top region — a thin status strip showing: factory state (running / paused / human-gated), current cycle ID and elapsed time, today's dollar burn vs. daily cap, and aggregate budget remaining for the active research program. To the right of the strip, a single primary button labeled "Pause Factory" (or "Resume" if paused).
>
> Second region — Active Cycles. A horizontal row of 1–4 cards, each representing a hypothesis currently moving through the gate pipeline. Each card shows: hypothesis ID (monospace 7-char prefix), one-sentence hypothesis title, current gate (e.g., "G3 — Surrogate"), gate timer, mini gate-pipeline indicator (small horizontal row of 9 dots, one per gate G0–G6, colored by state), and the cost burned so far on this hypothesis. Clicking a card opens the Hypothesis Detail screen.
>
> Third region — Recent Verdicts. A dense table with columns: timestamp, hypothesis ID, gate that fired the verdict (G2 council, G4 validation, G5 review, etc.), outcome pill (passed / falsified / intractable / inconclusive / qualified), and a 30-character snippet of the chairman's verdict or the failing check. The row expands inline on click to show full verdict text including preserved dissent in violet.
>
> Fourth region — System Telemetry. Four small charts in a row: (1) hypotheses-per-day sparkline over the last 30 days, (2) gate-failure heatmap with G0–G6 as columns and the last 14 days as rows, (3) dollar burn over the last 7 days as a stacked bar by cycle, (4) council agreement rate sparkline (higher = more sycophancy risk; the chart has a horizontal threshold line and the value above the threshold is colored amber).
>
> Empty state when no cycles are active: a single line "Factory is idle. Start a cycle" with the action inline. Loading uses skeleton rows. No illustrations.

---

## 2. Gate Pipeline View

> Design a detail view for a single hypothesis moving through the factory's gate sequence. The user is the researcher inspecting why a hypothesis is where it is and whether to intervene. The screen has a horizontal pipeline visualization as the main element.
>
> Pipeline element: nine gates arranged left-to-right — G0 Domain, G1 Falsifiability, G1.5 Simulability, G2 Worthiness, G2.5 Tractability, G3 Surrogate, G4 Validation, G5 Interpretation, G6 Human. Each gate is rendered as a 64-pixel-wide rectangle with a 1px border, the gate label below it, and an outcome pill inside (passed green / failed red / in-progress blue with a spinning indicator / pending grey / qualified amber / parked violet). A thin horizontal line connects them. The currently-active gate has a slightly elevated background and a left-edge accent stripe in cyan.
>
> Below the pipeline, a single panel shows the *current* gate's details: which check is running, what input it received (artifact ID with provenance hash), expected output, and live log stream if the gate is currently executing. For deterministic gates this is a list of sub-checks with pass/fail markers; for council gates this is a preview of the three deliberation stages with a "view full deliberation" link.
>
> A right sidebar shows the typed artifacts for this hypothesis as a small file-tree: GapCandidate, HypothesisSpec, CouncilVerdict (one per council fired so far), ExperimentSpec, Budget, RunReport (if final). Clicking any artifact opens it as a JSON viewer in a slide-over panel.
>
> A header strip above the pipeline shows: hypothesis ID (monospace), parent gap ID, current dollar burn / cap, elapsed time, and an "Abort Hypothesis" destructive action (red border button, requires confirmation modal).
>
> When a gate has failed, the failed gate is highlighted, and a panel below the pipeline shows the failure mode, the rollback action that was taken, and a "Re-litigate" button if the EvidenceLedger entry has relitigate_if conditions that are now met.

---

## 3. Council Deliberation View

> Design the view that shows a single council deliberation in full. This is the most novel and most important screen — the heart of the product. The user is the researcher inspecting how the council reached its verdict and what dissent exists. The screen has three vertical sections, top to bottom, mirroring the three stages of the deliberation protocol.
>
> Header: which council is this (C1 Worthiness / C2 Design / C3 Interpretation / C4 Peer Review / C5 Program Direction), the question put to the council in monospace blockquote form, the model lineup as a row of small chips (each chip showing model name + assigned persona, e.g., "Claude-Opus · Pessimist" / "GPT-5 · Visionary" / "Gemini · Pragmatist" / "Qwen-235B · Pessimist"), and the chairman model identified with a small crown-shaped icon (line drawing, 12px).
>
> Stage 1 — First Opinions: a horizontal scrollable row of expert-opinion cards, one per (model × persona) cell. Each card is ~320px wide, has the model+persona chip at top, full text of that cell's opinion in body, and a rank/score they self-assigned. Cards have a max collapsed height; "expand all" toggles full text inline.
>
> Stage 2 — Anonymized Cross-Review: a matrix. Rows are reviewers, columns are reviewees (both anonymized as "Voice A" / "Voice B" / etc.). Each matrix cell contains the rank the reviewer assigned, a 1-line critique excerpt, and a small "see full critique" expander. Below the matrix, a "Reveal Identities" toggle that maps Voice A → model+persona. Default is anonymized to match the deliberation protocol.
>
> Stage 3 — Chairman Synthesis with Preserved Dissent: two parallel columns of equal width. Left column is the chairman's majority verdict — full text, clearly readable, normal body color. Right column is **Preserved Dissents** — each minority view rendered as a card with violet left-edge accent, attributed to (model + persona), with the dissent rationale in full. Dissents are NOT collapsed by default. The header of the right column reads "Dissenting Views (3)" with the count. If there is no dissent, the right column shows "No dissent recorded — flag for sycophancy review" in amber.
>
> Below the three stages, a metadata strip: deliberation cost ($X across all model calls), wall-clock time, council session ID, downstream artifact this verdict produced (linked).
>
> The screen supports a "Compare with prior verdicts" action that opens a side-by-side view of how this same council answered similar questions historically.

---

## 4. Hypothesis Detail

> Design a detail view for a single hypothesis showing its full lifecycle. The user is the researcher inspecting one specific research thread. Layout is a two-pane design: left pane is a vertical timeline, right pane shows the currently-selected artifact.
>
> Left pane — vertical timeline reading top to bottom: GapCandidate (with parent literature evidence link), C1 Worthiness Verdict, HypothesisSpec, C2 Design Verdict, ExperimentSpec, G2.5 Tractability result, G3 Surrogate result, G4 Validation result, C3 Interpretation Verdict, C4 Peer Review Verdict, RunReport, EvidenceLedger entry. Each timeline node is a small card with: artifact type icon (line-only), short label, timestamp, status pill, and content-hash prefix. Clicking selects the node and opens its content in the right pane.
>
> Right pane — context-aware view of the selected artifact:
> - For GapCandidate: shows the gap type, source papers (linked to Paper Store), confidence, and the rationale for why this is a research-worthy direction.
> - For HypothesisSpec: shows the IF-THEN statement prominently, the measurable metric, expected effect size with confidence interval, kill criteria, and parent gap link.
> - For CouncilVerdict (any of them): opens the full Council Deliberation View inline (the screen specified above).
> - For ExperimentSpec: shows simulator (with link to Catalog entry), control definition, fidelity ladder, seed set, success metric, kill criteria, estimated cost.
> - For results (G2.5/G3/G4): shows the check matrix with pass/fail per sub-check, log excerpts, plots if any.
> - For RunReport: shows a paper-style preview (title, abstract, headline figure) with a "Read full report" action that opens the RunReport Reader screen.
>
> Top strip: hypothesis ID (monospace), title in sans-serif (one sentence), overall status, total cost burned, "Abort" / "Re-litigate" actions where applicable.
>
> Far-right small panel (collapsible): Provenance Audit. Shows every content hash for every artifact in the timeline, code-hash of the generator-verifier output, container SHA, simulator version, seed values. This panel is the cryptographic proof-of-work the system can offer for the hypothesis. Researchers must be able to copy any hash with one click.

---

## 5. Experiment Detail / Runner

> Design the live view of an experiment currently executing. The user is the researcher watching a generator-verifier loop run in real time. The screen prioritizes live data over historical context.
>
> Top region — Experiment summary strip: hypothesis title (one sentence), simulator ID (linked to Catalog entry, monospace), current fidelity tier on the ladder (e.g., "tier 2 of 4 — coarse-grid surrogate"), iteration counter (e.g., "iteration 7 of 10"), elapsed wall clock, dollars burned vs. cap, and a kill button (red border).
>
> Main region — three-column layout:
>
> Left column — Fidelity Ladder. A vertical stack of tier cards, top to bottom: Tractability Dry-Run, Surrogate Probe, Mid-Fidelity Sim, Full-Fidelity Oracle, Cross-Simulator Check. Each tier shows: status (passed/running/pending/failed), the metric value achieved at that tier vs. the kill threshold, the runtime, and the cost. The currently-running tier has an active highlight; completed tiers are slightly dimmed but readable.
>
> Center column — Live log stream. Tail of stdout from the running sandbox process. Monospace, scroll-locked-to-bottom by default with a "pause stream" toggle. Errors highlighted in red, warnings in amber. A search box above the stream filters in real time.
>
> Right column — Validation Portfolio (G4 checks). A vertical list of all G4 checks for this experiment: conservation invariants, convergence below tolerance, refinement convergence, symmetry tests, limiting-case tests, statistical validity (variance, error bars), cross-simulator check (if Catalog supports). Each check is a row with status icon, check name, residual or score (monospace), threshold, and pass/fail outcome. Cross-simulator check shows two side-by-side values from the two simulators with the agreement metric.
>
> Below the three columns — Plot strip: 2–4 small inline plots showing the metric of interest over iterations, convergence curve, and residual norms. Plots are minimal: thin axes, no gridlines, no titles inside the plot (titles above).
>
> Below the plots — Generator-Verifier history. A compact table of the 10 iterations: iteration #, what the code generator tried, what the verifier returned (success / shape error / NaN / wrong physics), and the diff vs. the previous iteration as a small expandable code block. Failures are highlighted with the failure category.

---

## 6. Simulator Catalog Browser

> Design a browser for the curated catalog of open-source physics simulators. The user is either browsing for a hypothesis-relevant simulator or auditing the catalog for quality and license compliance. Layout is a master-detail pattern.
>
> Master pane (left, 360px wide) — searchable, filterable list of simulators. Each row shows: simulator name, domain badge (plasma / CFD / MD / DFT / QCD / FEA / climate / astro), license badge (OSI-approved license name in monospace), maintenance signal (green dot if commit ≤ 24mo, amber if 24–60mo, red if older or unmaintained), and a tiny stack of cross-simulator equivalence icons indicating how many other catalog entries can compute the same observables. Filters at top: domain (multi-select), license (multi-select), maintenance status, has-cross-simulator-equivalents (toggle).
>
> Detail pane (right) — selected simulator's full manifest, presented as a structured document with these sections:
> - Header: name, upstream repo link (external), version, license, maintenance status, last-commit date.
> - Capabilities: bullet list of physics/observables it computes, with explicit limits called out.
> - I/O schema: input format, configuration DSL example (monospace block), output format.
> - Container recipe: Dockerfile excerpt in a copyable code block, base image SHA, install time, container size.
> - Smoke test: the known-good problem used as build-verification probe, with last-run timestamp and pass/fail status. A "Run smoke test now" action.
> - Dependency graph: a small node-link diagram showing MPI flavor, BLAS variant, CUDA version, compiler version, OS family. Nodes that have license issues themselves are highlighted red.
> - Known pathologies: a bulleted list of domain-specific failure modes, sourced from the manifest.
> - Cross-simulator equivalence: a table of other catalog entries that compute the same observable, with the agreement metric historical mean and variance.
> - Recent runs: a table of the last 10 experiments that used this simulator, with hypothesis ID, result, and runtime.
>
> Top of the detail pane: action buttons — "Audit License" (re-runs the dependency-graph license check), "Rebuild Container", "Mark Deprecated", "View All Runs".
>
> A separate top-right primary action: "Propose New Catalog Entry" — opens an onboarding workflow form for Phase B / C entries (out of scope for this screen design but link the action).

---

## 7. Evidence Ledger Browser

> Design a searchable browser for the historical record of every hypothesis the factory has executed. The user is either reviewing past findings to inform a new direction or auditing internal findings for hallucination compounding. Layout is a search-results-style list with a detail panel.
>
> Top strip — search input (full-text), faceted filters: result type (passed / falsified / intractable / inconclusive), domain, simulator, council that issued the verdict, date range, has-relitigate-conditions (toggle), has-dissent (toggle). A second filter row: "uncertainty threshold" slider — only show entries with uncertainty below X.
>
> Results list — each row is a card with: hypothesis title (one sentence), result pill, hypothesis ID + parent gap ID (monospace prefixes), domain badge, simulator badge, date, dollar cost, council verdict snippet, dissent indicator (small violet badge if any council that signed off had preserved dissent), uncertainty interval (small inline visual: dot + horizontal range), and relitigation eligibility (small icon if relitigate_if conditions exist; second icon if those conditions are now met).
>
> Detail panel (slide-over from right when a row is clicked) — shows the full EvidenceLedger entry: result, provenance hashes (code, env, input, seed, simulator version, container SHA), uncertainty quantification, all council verdicts that signed off (each linked to the Council Deliberation View), the parent HypothesisSpec, the RunReport, and the relitigate_if conditions with current status of each condition.
>
> A special "Audit Mode" toggle in the top right re-renders the results list as an audit table for C5 (Program Direction council) review: it sorts by "how many downstream hypotheses depend on this finding," and highlights findings that are heavily cited by later cycles but have high uncertainty or unresolved dissent. This is the surface used to catch internal hallucination compounding.
>
> Empty state when no results match filters: "No matching evidence. Try widening the date range or removing the uncertainty filter."

---

## 8. RunReport Reader

> Design a reader view for the auto-generated paper a successful (or defensibly-null) hypothesis produces. The user is either reviewing a draft before approving external publication (G6), or reading historical reports. The aesthetic is "modern academic preprint" — closer to a clean web-rendered arXiv paper than to a Word document.
>
> Layout: centered column max-width 720px, ample whitespace, serif body font option toggleable from the default Inter. Strong hierarchy: title (28px), authors line ("AI Co-Computational Physicist Factory, Cycle #..."), date, then sections in order — Abstract, Introduction, Related Work, Method, Experiment, Results, Limitations, Negative-Result Discussion (if applicable), Conclusion, Provenance Appendix, BibTeX.
>
> Inline equations render with KaTeX. Code blocks for the generator-verifier output appear as expandable accordions inline. Figures appear as full-bleed centered images with caption below in 12px secondary-text color.
>
> A persistent right-edge sidebar (collapsible) shows:
> - Reading progress (small vertical bar).
> - Embedded council reviews — every claim in the body that was challenged by C3 or C4 has a small violet marker in the margin; clicking expands the preserved dissent inline next to the paragraph that triggered it.
> - Provenance summary: hypothesis ID, simulator, all hashes, total cost. A "Copy citation" button generates a BibTeX entry for the internal-published version.
> - G6 Approval status: "Approved for external release by [user]" with timestamp, or "Pending review" with an inline approve / reject action if the user has G6 permissions.
>
> Top strip: a thin header with breadcrumb (Mission Control > Cycle X > RunReport), download buttons (LaTeX source, PDF, BibTeX), and a prominent "Approve for External Release" button at the right if status is Pending and user has permission. The approve button requires a confirmation modal that re-states the report's headline claim and any preserved C4 dissent.

---

## 9. Human Approval Queue (G6)

> Design the queue of internally-published RunReports awaiting human review before external release. The user is the researcher acting as final reviewer — this is the single human-gated step in an otherwise autonomous system. Density and clarity matter; the user must be able to triage many reports quickly.
>
> Layout: a list view with bulk-selection capability. Top strip — filters by submission date, by C4 verdict strength (strong / weak), by whether dissent exists, by domain. A counter shows "N reports awaiting your review" in cyan, prominent.
>
> Each queue row is taller than a normal table row (about 96px) and contains:
> - Left: hypothesis title (one sentence, 14px), one-paragraph abstract excerpt (~3 lines, 12px secondary), domain + simulator badges.
> - Center: a 240px-wide "Evidence Strength" panel showing five small indicators in a vertical stack — Validation portfolio pass rate, cross-simulator agreement (if applicable), C3 chairman confidence, C4 chairman confidence, and a "dissent severity" indicator (violet). Each indicator is a thin horizontal bar with a value and a threshold mark.
> - Right: a vertical stack of action buttons: "Read Full Report" (opens RunReport Reader), "Approve for Release", "Reject" (with required reason in a modal), "Send Back for Re-litigation" (sends back to C5).
>
> Above the list, a "Triage Mode" toggle that switches to a more compact one-line-per-row view for quick scanning — same actions accessible via keyboard shortcuts (a/r/s for approve/reject/send-back).
>
> A right-side persistent panel — "Approval History": a chronological log of every G6 decision the user has made in the past 90 days, with stats: approval rate, average time-to-decision, percentage of approvals that triggered a downstream C5 re-audit (this is a self-calibration signal — if approvals frequently get re-audited, the user is approving too liberally).
>
> Empty state when no reports await review: "Queue clear. All current cycles are pre-G6." Small.

---

## 10. Literature Discovery / OpenAlex Graph View

> Design the view of the literature discovery layer. The user is either inspecting why the Gap Miner produced a particular GapCandidate, or actively browsing the OpenAlex citation graph to understand the research neighborhood. Layout has three regions: graph canvas (center, takes most of the screen), traversal-control panel (left, 280px), and selected-paper detail (right, slide-over).
>
> Graph canvas — a force-directed graph visualization. Nodes are papers from the Paper Store; node size is proportional to the citation count, node fill color encodes role (seed = cyan, bridge paper = violet, seminal ancestor = white outline, recent extension = green, contradiction-cluster member = amber). Edges are citation directions (backward citations as solid lines, forward citations as dashed, related_works as dotted). Hovering a node shows a tooltip with title + authors + year + venue; clicking opens the detail panel.
>
> Above the graph canvas, a thin breadcrumb showing the current traversal run ID + the seed query in monospace blockquote form.
>
> Traversal-control panel (left) — the YAML policy currently in effect, editable in place: max_depth, max_nodes, branch_factor (backward, forward), filters (publication_year_min, is_oa), scoring weights (relevance, citation, recency, oa_pdf, bridge). A "Re-traverse" button at the bottom kicks off a new graph build. Below the YAML, a small list of "Promoted Papers" — papers the operator has promoted to the Paper Store for full PDF/OCR + evidence extraction. The list is reorderable by drag-and-drop with relevance score.
>
> Selected-paper detail panel (right, opens on click) — shows the full Paper Store entry for the selected node: title, authors, abstract, full citation, open-access PDF link if available, extracted-evidence schema entries (key claims, hyperparameters, methods, simulators used), and a "Used by these GapCandidates" backlink list. Two actions: "Promote to Paper Store" (if not already promoted) and "Add as Seed for New Traversal".
>
> Below the graph canvas, a thin strip showing graph statistics: nodes count, edges count, identified bridge papers, contradiction clusters detected, gaps surfaced. Each statistic is a small chip; clicking a chip filters the canvas to highlight only those nodes.

---

## 11. Settings — Council, DomainScope, Budgets

> Design a settings page for the factory's configuration. The user is the researcher tuning the system's behavior. Layout is a left-side category nav + main configuration panel.
>
> Left nav categories: Council Configuration, DomainScope, Budgets, Surrogate Models, Catalog Onboarding, API Keys & Models, Audit & Logging.
>
> **Council Configuration panel:** the model lineup as a vertical list — each row is a model entry with: provider/model identifier (monospace dropdown), persona assignment (segmented control: Visionary / Pessimist / Pragmatist / Random), enabled toggle, last-used timestamp, average response time, average cost-per-deliberation. "Add Model" button at bottom. Below the lineup, a Chairman Rotation section — list of which models are eligible to chair, with the rotation policy (random / round-robin / weighted-by-cost). Below that, a Sycophancy Calibration section showing the current agreement-rate metric, the threshold above which the system flags sycophancy risk, and a sample-rerun action that asks all current councils a known-divisive test question and reports their disagreement score.
>
> **DomainScope panel:** the current allowed domains as a tag cloud — each tag is a domain (e.g., stellarator-MHD, CFD, MD, DFT) and clicking removes it from scope. An "Add Domain" workflow shows simulator availability prereqs and proposes a probationary onboarding plan. Below, the expansion_criteria as an editable rule list (e.g., "expand to adjacent domain when ≥3 successful runs in current scope produce findings that cite cross-domain methods").
>
> **Budgets panel:** four columns — per-hypothesis cap, per-cycle cap, daily cap, aggregate program cap. Each shows current burn vs. cap as a horizontal bar, with the input field beside it to adjust. A kill switch toggle at the top of the panel: "Hard stop on aggregate cap" (default on); a relaxation requires a confirmation modal. Cost-per-component breakdown: a small horizontal stacked bar showing where dollars went in the last 30 days — LLM council calls, generator-verifier code-gen, simulator compute, surrogate training, container builds.
>
> **Surrogate Models panel:** list of trained surrogates (random forest / MLP / GP for each target observable) with last-trained timestamp, training-set size, validation R² or accuracy, OOD-detection method (e.g., distance-to-training-distribution percentile threshold), and "Retrain" / "Replace" actions. A section at the bottom shows how many G3 decisions in the last 30 days were OOD-escalated to oracle.
>
> **API Keys & Models panel:** API keys for the LLM router and direct-vendor fallbacks, plus self-hosted-model endpoint URLs. Each key shows its last-used timestamp, monthly spend, and rate-limit status. Keys are stored as redacted prefixes with reveal-on-hover.
>
> **Audit & Logging panel:** retention policy for raw council deliberations, raw generator-verifier logs, container build artifacts. Export controls (download as tar.gz). C5 re-audit cadence configuration. A "Trigger Internal Audit" action that runs C5 immediately over the top-K most-cited internal EvidenceLedger entries and reports back.

---

## Appendix A — Component Library Notes

For coherent designs across all eleven screens, the following components are reused. When generating any screen, assume these exist:

- **Status pill:** rectangular, 2px corner, 12px font, padding 4×8. Variants: pass green, fail red, pending amber, in-progress blue, parked violet, dissent violet, qualified amber-with-border.
- **Provenance hash chip:** 7-char monospace prefix on grey-tinted background, copy-on-click, hover reveals full hash.
- **Council verdict card:** majority view + preserved dissents in two equal-width columns, never collapsed by default.
- **Fidelity ladder tier card:** vertical stack of 5 tiers, current tier accent-bordered, completed tiers dimmed but readable.
- **Gate dot:** 12px square, colored by gate state, used in mini gate-pipeline indicators.
- **Sparkline:** thin axes, no gridlines, no titles inside chart, height ≤ 40px when used inline.
- **Uncertainty bar:** point estimate dot + horizontal range, 80px wide standard.
- **Live log pane:** monospace, scroll-lock-to-bottom toggle, inline search, error/warning highlighting.
- **Empty state:** one short sentence + the action to populate, never an illustration.
- **Skeleton loader:** for any list, table, or card while loading.

---

## Appendix B — What the Design Generator Must NOT Produce

To keep the product from drifting into generic AI-product aesthetic, repeat these constraints in each prompt iteration as needed:

- Purple-to-blue gradient backgrounds.
- Glassmorphism / frosted-glass surfaces.
- Decorative emoji or AI-iconography (sparkles, orbs, brain icons, robot faces).
- Soft pastel palettes (the only soft tones are status colors, used sparingly).
- "Chat bubble" patterns for any council or LLM interaction display — councils are deliberations, not chats.
- Auto-generated stock illustrations.
- Drop shadows on cards (use 1px borders and surface elevation).
- Pill-shaped buttons or chips (max 4px corner radius throughout).
- Centered hero sections (this is an operations console, not a landing page).
- "Try X with AI" generic AI-feature CTAs anywhere.

---

## Appendix C — Suggested Generation Workflow

1. Paste the Global Design System Prompt (§0) as the first message in a new design-generation session.
2. Paste one screen prompt at a time (§1 through §11), starting with Mission Control (§1) since it sets the overall density and palette tone.
3. After each screen generates, refine with short follow-ups: "Make the council dissent column more prominent" / "Use monospace for all IDs and hashes" / "Reduce visual weight of the chairman crown icon" / etc.
4. The Council Deliberation View (§3) is the most novel and most worth iterating on — budget extra rounds for it.
5. Once individual screens look right, ask the design generator to produce a "navigation map" showing how the eleven screens link together — this surfaces inconsistencies in headers, breadcrumbs, and shared component reuse.
