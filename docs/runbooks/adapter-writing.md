# Runbook: Writing a Domain Adapter

> What this covers: adding a new simulator from `SimulatorCatalog` to the factory by writing the matching domain adapter — implementing the six-component abstract solver interface, registering, mocking, and smoke-testing. · When to use: a new simulator has been onboarded into the Catalog (Spec 004) and needs an adapter before the Generator-Verifier loop (Spec 008) can target it. Also use when an existing adapter is broken and needs a full rewrite. · Estimated time: 1–3 days for a fresh adapter, including mock fixtures and the live smoke test. The translation logic itself is the dominant cost; the registry boilerplate is minutes.

## 1. Prerequisites

Before you start writing adapter code, confirm the following exist: (a) a `SimulatorCatalog` entry for `<simulator_id>` with license, container recipe, smoke-test target, and dependency graph already approved (Spec 004); (b) the container builds from scratch and the smoke-test problem produces known-good output when run by hand inside the container — if the container is unhealthy, fix that **first**, do not paper over it inside the adapter; (c) the abstract solver interface (`factory/adapter/abstract.py`) is locked — if Spec 008 is still iterating the six-component blueprint, prefer to wait for it to stabilize; (d) at least one existing adapter is already in tree as a reference (`factory/adapter/<sim_other>.py`) — read it before drafting a new one; (e) you have CLI access to `python -m factory.adapter list` to confirm the registry boots without your new entry, and to `python -m factory.catalog inspect <simulator_id>` to read the catalog manifest.

## 2. Steps

1. **Study the abstract interface.** Open `factory/adapter/abstract.py` and identify the six pluggable ABCs: `Discretization`, `BoundaryHandler`, `UpdateOperator`, `Acceptance`, `RestartPolicy`, `LocalPolish`. `[TBD-impl]` exact class names may shift when Spec 008 freezes. Understand what *operation* each ABC promises before deciding how your simulator implements it.
2. **Identify the six per-simulator implementations.** For your target simulator, map each ABC onto a concrete piece of the simulator's API or config. Some simulators bundle several of these into one binary; the adapter still presents six components. Document the mapping in a top-of-file docstring before writing any code.
3. **Scaffold the adapter file.** Copy `factory/adapter/<sim_other>.py` to `factory/adapter/<simulator_id>.py`. Replace the `simulator_id` class attribute, rewrite the six component classes, and stub `Adapter.run(experiment_spec, sandbox_dir) -> RunArtifacts`. The `@register` decorator on the class auto-adds it to the registry at import time — no manifest edit required.
4. **Implement `Adapter.run(...)` in four discrete passes:** (i) validate `experiment_spec.simulator_id == self.simulator_id` and raise `AdapterContractViolation` on mismatch; (ii) translate `control_definition` and the chosen fidelity tier into the simulator's input DSL — `SimulatorConfigInvalid` must fire **before** the container launches; (iii) invoke the simulator inside `sandbox_dir` (subprocess, container exec, or in-process call — adapter's choice); (iv) parse outputs into a `RunArtifacts` payload, persist `run_artifacts.json` alongside raw outputs, return.
5. **Write the mock subclass.** In the same module file, define `MockAdapter` that reads fixture `RunArtifacts` from `factory/adapter/fixtures/<simulator_id>/<fixture_name>.json` and returns them verbatim. `factory.adapter.load(simulator_id, mock_mode=True)` must wire to this subclass.
6. **Author ≥3 fixtures:** one passing run, one invariant-violating run (so spec 009's validation tests have something to catch), and one runtime-failure case. Place under `factory/adapter/fixtures/<simulator_id>/`. Each fixture is a JSON file satisfying the `RunArtifacts` protocol.
7. **Write the typical-usage test.** Add `factory/adapter/tests/test_<simulator_id>_typical_usage.py`. The test instantiates the adapter in mock mode, runs a fixture `ExperimentSpec`, and asserts the returned `RunArtifacts` shape — observables present, residuals populated, provenance fields filled. Confirm the test passes via `pytest factory/adapter/tests/test_<simulator_id>_typical_usage.py`.
8. **Run the live smoke test.** Boot the catalog-entry container, run `python -m factory.adapter run --simulator-id <id> --experiment-fixture smoke` (no `--mock-mode`), and confirm the returned `RunArtifacts` matches the catalog's documented known-good output. This is gated `@pytest.mark.live` so it is the human acceptance gate before activating the adapter for cycles.

## 3. Verification

After completing all steps you should observe: (a) `python -m factory.adapter list` includes `<simulator_id>` and the startup adapter↔catalog consistency check passes — i.e., no `AdapterContractViolation` fires at import time; (b) `python -m factory.adapter inspect <simulator_id>` displays the adapter's metadata and the six bound components; (c) `pytest factory/adapter/tests/test_<simulator_id>_typical_usage.py` is green; (d) `python -m factory.adapter run --simulator-id <id> --experiment-fixture sample --mock-mode` exits 0 with a non-empty `RunArtifacts` payload printed; (e) the live smoke test (manual, `@pytest.mark.live`) reproduces the catalog's known-good output within tolerance.

## 4. Troubleshooting

- **`AdapterNotRegistered` at runtime even though the file exists.** The `@register` decorator did not fire because the module was not imported by `factory.adapter.__init__`. Verify the package's `__init__.py` imports `<simulator_id>` (or relies on auto-discovery scanning the directory). Restart any running orchestrator after editing.
- **`AdapterContractViolation` at startup, "simulator_id not in catalog".** Either the catalog entry is missing (run Spec 004 onboarding first), or `Adapter.simulator_id` is misspelled. The state machine refuses to boot until adapter and catalog match exactly.
- **`SimulatorConfigInvalid` for an `ExperimentSpec` that "should" work.** Translation logic rejected the spec — usually because a numeric field is out of the simulator's native bounds or a required field was unmapped. Add the missing translation; do **not** loosen the validator to make the test pass.
- **`AdapterRuntimeFailure` on the live smoke test, simulator OOMs.** The smoke-test problem is too aggressive for the available container memory. Either bump the container resource request in the catalog manifest, or shrink the smoke problem. Do not catch the OOM inside the adapter and pretend it succeeded — `AdapterRuntimeFailure` is the correct signal.
- **`RunArtifacts` shape mismatch.** The parsed simulator outputs missed a required field (typical: `simulator_version` or `container_sha` empty). Fix the parser; the protocol is enforced. `[TBD-impl]` exact required-field list will move once `RunArtifacts` is promoted from `Protocol` to a Pydantic concrete class.

## 5. Related

- Spec 006 (`docs/specs/006-domain-adapter.md`) — adapter contract, registry behavior, `RunArtifacts` protocol.
- Spec 004 (`docs/specs/004-simulator-catalog.md`) — catalog entry requirements; the prerequisite for any new adapter.
- Spec 008 (Generator-Verifier loop) — the only intended caller of `adapter.run(...)`; defines the abstract solver blueprint the six ABCs implement.
- Spec 009 (Validation Portfolio) — consumer of `RunArtifacts`; fixture set must include adversarial cases.
- SPEC.md §5.3 — strategic role of the adapter layer ("adding a simulator is writing an adapter, not retraining a prompt").
