# cli.py — Command Line Interface for council
#
# Exposes subcommands for internal debugging, manual execution, and calibration.

import argparse
import datetime
import json
import logging
import pathlib
import shutil
import sys
import time
from collections.abc import Sequence
from typing import Any, Literal, cast

import yaml

from factory.artifacts import (
    CouncilId,
    HypothesisId,
    PersonaName,
)
from factory.budget import BudgetTracker, HypothesisCaps
from factory.council.deliberation import Council
from factory.council.types import (
    CalibrationReport,
    CouncilContext,
    CouncilContextValue,
    CouncilLineup,
    ModelSpec,
)
from factory.llm_client import OpenRouterClient, OpenRouterMessage, OpenRouterModelUnavailable

logger = logging.getLogger("factory.council.cli")

FIXTURES = {
    "sample_worthiness": (
        "Is the proposed stellarator optimization algorithm worthy of C1 gate approval?",
        {
            "hypothesis_id": "H-STELLA-001",
            "gap_candidate": (
                "Structural hole in DESC optimization path for non-symmetric stellarators."
            ),
            "worthiness_score": 0.87,
        },
    ),
    "sample_gap_candidate": (
        "Is there a significant literature gap regarding stellarator coils optimization "
        "using surrogate physics networks?",
        {
            "hypothesis_id": "H-STELLA-002",
            "gap_candidate": "Numerical instability in current SIMSOPT surrogate modeling.",
            "worthiness_score": 0.72,
        },
    ),
}


FRONTIER_VENDORS = {"openai", "anthropic", "google", "x-ai"}


def _coerce_context(raw: object) -> CouncilContext:
    """Validate a CLI context payload into the deliberation scalar map."""
    if not isinstance(raw, dict):
        raise ValueError("context must be a JSON object")

    validated: dict[str, CouncilContextValue] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError("context keys must be strings")
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError(f"context value for {key!r} must be a scalar")
        validated[key] = value
    return validated


def load_lineup(path: pathlib.Path) -> CouncilLineup:
    """Loads and constructs a CouncilLineup from the given YAML file.

    Args:
        path: Absolute path to the lineup.yaml file.

    Returns:
        A validated CouncilLineup instance.
    """
    logger.info("load_lineup(path=%s)", path)
    if not path.exists():
        print(f"Error: Lineup configuration file not found at {path}")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    models_raw = data.get("models", [])
    models = []
    for m in models_raw:
        models.append(
            ModelSpec(
                openrouter_id=m["openrouter_id"],
                vendor=cast(Literal["openai", "anthropic", "google", "x-ai"], m["vendor"]),
                timeout_s=float(m.get("timeout_s", 60.0)),
                max_tokens=int(m.get("max_tokens", 4096)),
            )
        )

    persona_raw = data.get("persona_assignment", {})
    persona_assignment = {k: PersonaName(v.lower()) for k, v in persona_raw.items()}

    chairman_policy = cast(
        Literal["random", "round_robin", "weighted_by_cost"],
        data.get("chairman_policy", "round_robin"),
    )

    return CouncilLineup(
        models=models,
        persona_assignment=persona_assignment,
        chairman_policy=chairman_policy,
    )


def _parse_council_id(raw_council_id: str) -> CouncilId:
    try:
        return CouncilId(raw_council_id)
    except ValueError:
        valid_ids = [e.value for e in CouncilId]
        print(
            f"Warning: --council-id '{raw_council_id}' is not a standard CouncilId. "
            f"Standard IDs: {valid_ids}."
        )
        return cast(CouncilId, raw_council_id)


def _resolve_deliberation_input(args: argparse.Namespace) -> tuple[str, CouncilContext]:
    question = None
    context: CouncilContext = {}

    question_fixture = getattr(args, "question_fixture", None)
    if question_fixture:
        if question_fixture in FIXTURES:
            q_fix, c_fix = FIXTURES[question_fixture]
            question = q_fix
            context = _coerce_context(c_fix)
        else:
            print(
                f"Error: Unknown question fixture '{question_fixture}'. "
                f"Available fixtures: {list(FIXTURES.keys())}"
            )
            sys.exit(1)

    raw_question = getattr(args, "question", None)
    if raw_question:
        question = raw_question

    context_fixture = getattr(args, "context_fixture", None)
    if context_fixture:
        if context_fixture in FIXTURES:
            _, c_fix = FIXTURES[context_fixture]
            context = _coerce_context(c_fix)
        elif pathlib.Path(context_fixture).exists():
            with open(context_fixture, encoding="utf-8") as f:
                context = _coerce_context(json.load(f))
        else:
            try:
                context = _coerce_context(json.loads(context_fixture))
            except json.JSONDecodeError:
                print(
                    f"Error: Context fixture '{context_fixture}' must be a valid file path, "
                    f"a fixture key, or a raw JSON string."
                )
                sys.exit(1)

    if not question:
        print("Error: Either --question or --question-fixture must be provided.")
        sys.exit(1)

    return question, context


def _validate_live_lineup(lineup: CouncilLineup) -> None:
    vendors = {model.vendor for model in lineup.models}
    if len(lineup.models) != 4 or vendors != FRONTIER_VENDORS:
        raise RuntimeError(
            "Live council certification requires exactly four frontier vendors: "
            f"{sorted(FRONTIER_VENDORS)}. Configured vendors: {sorted(vendors)}."
        )


def summarize_live_certification_session(
    session_log_path: pathlib.Path, expected_model_ids: Sequence[str]
) -> dict[str, object]:
    expected = set(expected_model_ids)
    stage1_models: set[str] = set()
    stage2_models: set[str] = set()
    stage3_models: list[str] = []
    session_end: dict[str, object] | None = None

    with open(session_log_path, encoding="utf-8") as f:
        for line in f:
            payload = json.loads(line)
            event = payload.get("event")
            model_id = payload.get("model_id")
            if event == "stage1_response" and isinstance(model_id, str):
                stage1_models.add(model_id)
            elif event == "stage2_response" and isinstance(model_id, str):
                stage2_models.add(model_id)
            elif event in {"stage3_response", "stage3_reprompt_response"} and isinstance(
                model_id, str
            ):
                stage3_models.append(model_id)
            elif event == "session_end":
                session_end = payload

    missing_stage1 = expected - stage1_models
    missing_stage2 = expected - stage2_models
    extra_stage1 = stage1_models - expected
    extra_stage2 = stage2_models - expected
    if missing_stage1 or extra_stage1:
        raise RuntimeError(
            "Live certification Stage 1 vendor coverage mismatch: "
            f"missing={sorted(missing_stage1)}, extra={sorted(extra_stage1)}."
        )
    if missing_stage2 or extra_stage2:
        raise RuntimeError(
            "Live certification Stage 2 vendor coverage mismatch: "
            f"missing={sorted(missing_stage2)}, extra={sorted(extra_stage2)}."
        )
    if not stage3_models:
        raise RuntimeError("Live certification did not record a Stage 3 chairman response.")

    unexpected_stage3 = set(stage3_models) - expected
    if unexpected_stage3:
        raise RuntimeError(
            "Live certification Stage 3 used a model outside the certified lineup: "
            f"{sorted(unexpected_stage3)}."
        )

    return {
        "session_log": str(session_log_path),
        "stage1_models": sorted(stage1_models),
        "stage1_response_count": len(stage1_models),
        "stage2_models": sorted(stage2_models),
        "stage2_response_count": len(stage2_models),
        "stage3_models": stage3_models,
        "stage3_response_count": len(stage3_models),
        "session_end": session_end,
    }


def summarize_live_certification_budget(
    ledger_path: pathlib.Path, hypothesis_id: HypothesisId
) -> dict[str, object]:
    entries = []
    with open(ledger_path, encoding="utf-8") as f:
        for line in f:
            payload = json.loads(line)
            if payload.get("hypothesis_id") == str(hypothesis_id):
                entries.append(payload)

    if not entries:
        raise RuntimeError(f"Budget ledger has no entries for hypothesis {hypothesis_id}.")

    total_cost = sum(float(entry["cost_usd"]) for entry in entries)
    total_tokens = sum(int(entry["tokens"]) for entry in entries)
    total_wall_clock = sum(float(entry["wall_clock_seconds"]) for entry in entries)

    return {
        "budget_ledger": str(ledger_path),
        "budget_entry_count": len(entries),
        "budget_recorded_cost_usd": total_cost,
        "budget_recorded_tokens": total_tokens,
        "budget_recorded_wall_clock_seconds": total_wall_clock,
        "budget_descriptions": [str(entry["description"]) for entry in entries],
    }


def _certify_live_model_failure() -> dict[str, object]:
    missing_model = "openai/live-certification-missing-model"
    messages: list[OpenRouterMessage] = [
        {"role": "user", "content": "OpenRouter live certification error-path probe."}
    ]
    client = OpenRouterClient()
    try:
        client.invoke(messages=messages, model=missing_model, max_tokens=16)
    except OpenRouterModelUnavailable as exc:
        return {
            "status": "passed",
            "model": missing_model,
            "exception": exc.__class__.__name__,
        }

    raise RuntimeError(
        f"Expected OpenRouterModelUnavailable for missing live model {missing_model}."
    )


def handle_show_lineup(args: argparse.Namespace) -> None:
    """Handles the 'show-lineup' subcommand.

    Args:
        args: Parsed CLI arguments.
    """
    logger.info("handle_show_lineup called with field=%s", args.field)
    project_root = pathlib.Path(__file__).resolve().parents[2]
    lineup_path = project_root / "config" / "council" / "lineup.yaml"
    lineup = load_lineup(lineup_path)

    field = args.field
    if field == "vendors":
        for m in lineup.models:
            print(m.vendor)
    elif field == "personas":
        for model_id, persona in lineup.persona_assignment.items():
            print(f"{model_id}: {persona.value}")
    elif field == "models":
        for m in lineup.models:
            print(m.openrouter_id)
    else:  # 'all' or default
        print(f"=== Council Lineup configuration ({lineup_path.name}) ===")
        for m in lineup.models:
            persona = lineup.persona_assignment[m.openrouter_id]
            print(
                f"Model: {m.openrouter_id:<30} | Vendor: {m.vendor:<10} | "
                f"Persona: {persona.value:<10}"
            )
        print(f"Chairman Policy: {lineup.chairman_policy}")
        print("======================================================")


def handle_deliberate(args: argparse.Namespace) -> None:
    """Handles the 'deliberate' subcommand.

    Args:
        args: Parsed CLI arguments.
    """
    logger.info("handle_deliberate called")
    project_root = pathlib.Path(__file__).resolve().parents[2]
    lineup_path = project_root / "config" / "council" / "lineup.yaml"
    lineup = load_lineup(lineup_path)
    c_id = _parse_council_id(args.council_id)
    question, context = _resolve_deliberation_input(args)

    session_dir = (
        pathlib.Path(args.session_dir)
        if args.session_dir
        else project_root / "runs" / "cli_sessions"
    )
    session_dir.mkdir(parents=True, exist_ok=True)

    print(f"Starting deliberation for council {c_id}...")
    print(f"Question: {question}")
    print(f"Context: {json.dumps(context)}")
    print(f"Mock Mode: {args.mock_mode}")

    council = Council(
        lineup=lineup,
        session_dir=session_dir,
        cost_cap_usd=args.cost_cap_usd,
        mock_mode=args.mock_mode,
    )

    try:
        verdict = council.deliberate(
            council_id=c_id,
            question=question,
            context=context,
        )
    except Exception as e:
        print(f"Deliberation aborted with exception: {e}")
        sys.exit(1)

    print("\n=== Council Verdict ===")
    print(f"Council ID: {verdict.council_id}")
    print(f"Decision:   {verdict.chairman_decision.upper()}")
    print(f"Majority View:\n{verdict.majority_view}\n")

    if verdict.preserved_dissents:
        print("Preserved Dissents:")
        for d in verdict.preserved_dissents:
            print(f"  - Model ID: {d.model_id} ({d.persona.value})")
            print(f"    View:      {d.view}")
            print(f"    Rationale: {d.rationale}")
    else:
        print("Preserved Dissents: None")

    print("\nMetadata:")
    print(f"  Session ID:      {verdict.session_id}")
    print(f"  Total Cost:      ${verdict.total_cost_usd:.6f}")
    print(f"  Duration:        {verdict.wall_clock_seconds:.2f}s")
    print(f"  Provenance Hash: {verdict.provenance_hash}")
    print(f"  Session log:     {session_dir / f'{verdict.session_id}.jsonl'}")
    print("=======================")


def handle_certify_live(args: argparse.Namespace) -> None:
    """Run the live production-readiness certification for council deliberation."""
    logger.info("handle_certify_live called")
    project_root = pathlib.Path(__file__).resolve().parents[2]
    lineup_path = project_root / "config" / "council" / "lineup.yaml"
    lineup = load_lineup(lineup_path)
    _validate_live_lineup(lineup)

    c_id = _parse_council_id(args.council_id)
    question, context = _resolve_deliberation_input(args)

    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    certification_dir = (
        pathlib.Path(args.output_dir)
        if args.output_dir
        else project_root / "runs" / "live_council_certifications" / timestamp
    )
    session_dir = certification_dir / "sessions"
    budget_dir = certification_dir / "budget"
    session_dir.mkdir(parents=True, exist_ok=True)
    budget_dir.mkdir(parents=True, exist_ok=True)

    hypothesis_id = HypothesisId(args.hypothesis_id or f"LIVE-COUNCIL-CERT-{timestamp}")
    context = dict(context)
    context["hypothesis_id"] = str(hypothesis_id)

    tracker = BudgetTracker(
        config_path=project_root / "config" / "budget.yaml",
        state_path=budget_dir / "state.json",
        ledger_path=budget_dir / "ledger.jsonl",
    )
    tracker.open_hypothesis(
        hypothesis_id,
        HypothesisCaps(
            dollars=args.cost_cap_usd,
            tokens=args.token_cap,
            wall_clock_seconds=args.wall_clock_cap_seconds,
            iterations=1,
        ),
    )
    reservation = tracker.check_and_deduct(
        hypothesis_id=hypothesis_id,
        module="council",
        estimated_cost_usd=args.cost_cap_usd,
        estimated_tokens=args.token_cap,
        estimated_wall_clock_seconds=args.wall_clock_cap_seconds,
        estimated_iterations=1,
        description="live council certification reservation",
    )

    council = Council(
        lineup=lineup,
        session_dir=session_dir,
        cost_cap_usd=args.cost_cap_usd,
        mock_mode=False,
        budget_tracker=tracker,
    )

    start = time.perf_counter()
    try:
        verdict = council.deliberate(
            council_id=c_id,
            question=question,
            context=context,
        )
    finally:
        reservation.cancel()

    tracker.close_hypothesis(hypothesis_id, terminal_status="passed")
    elapsed_seconds = time.perf_counter() - start

    if verdict.total_cost_usd > args.cost_cap_usd:
        raise RuntimeError(
            f"Live council cost ${verdict.total_cost_usd:.6f} exceeded cap "
            f"${args.cost_cap_usd:.6f}."
        )

    session_log_path = session_dir / f"{verdict.session_id}.jsonl"
    expected_model_ids = [model.openrouter_id for model in lineup.models]
    session_summary = summarize_live_certification_session(session_log_path, expected_model_ids)
    budget_summary = summarize_live_certification_budget(budget_dir / "ledger.jsonl", hypothesis_id)
    error_path = None if args.skip_error_path else _certify_live_model_failure()

    certification_path = certification_dir / "certification.json"
    certification = {
        "status": "passed",
        "council_id": c_id.value if hasattr(c_id, "value") else str(c_id),
        "hypothesis_id": str(hypothesis_id),
        "lineup_vendor_count": len({model.vendor for model in lineup.models}),
        "vendor_ids": sorted({model.vendor for model in lineup.models}),
        "model_ids": expected_model_ids,
        "verdict_decision": verdict.chairman_decision,
        "verdict_hash": verdict.provenance_hash,
        "verdict_total_cost_usd": verdict.total_cost_usd,
        "cost_cap_usd": args.cost_cap_usd,
        "cost_within_cap": verdict.total_cost_usd <= args.cost_cap_usd,
        "verdict_wall_clock_seconds": verdict.wall_clock_seconds,
        "certification_wall_clock_seconds": elapsed_seconds,
        "preserved_dissents_count": len(verdict.preserved_dissents),
        "session": session_summary,
        "budget": budget_summary,
        "error_path": error_path,
        "certification_path": str(certification_path),
    }

    with open(certification_path, "w", encoding="utf-8") as f:
        json.dump(certification, f, indent=2, sort_keys=True)
        f.write("\n")

    print(json.dumps(certification, indent=2, sort_keys=True))


def make_report_serializable(report: CalibrationReport) -> dict[str, Any]:
    """Helper to convert CalibrationReport dataclass to a JSON serializable dict.

    Args:
        report: The CalibrationReport instance.

    Returns:
        A dictionary representation of the report.
    """
    return {
        "overall_disagreement_rate": report.overall_disagreement_rate,
        "flagged_sycophancy": report.flagged_sycophancy,
        "notes": report.notes,
        "probe_results": [
            {
                "probe_id": pr.probe_id,
                "question": pr.question,
                "responses_by_model": pr.responses_by_model,
                "responses_by_persona": {
                    k.value if hasattr(k, "value") else str(k): v
                    for k, v in pr.responses_by_persona.items()
                },
                "disagreement_rate": pr.disagreement_rate,
            }
            for pr in report.probe_results
        ],
    }


def handle_calibrate(args: argparse.Namespace) -> None:
    """Handles the 'calibrate' subcommand.

    Args:
        args: Parsed CLI arguments.
    """
    logger.info("handle_calibrate called")
    project_root = pathlib.Path(__file__).resolve().parents[2]
    lineup_path = project_root / "config" / "council" / "lineup.yaml"
    lineup = load_lineup(lineup_path)

    probes_path = (
        pathlib.Path(args.probe_set)
        if args.probe_set
        else project_root / "config" / "council" / "probes.yaml"
    )
    if not probes_path.exists():
        print(f"Error: Calibration probes file not found at {probes_path}")
        sys.exit(1)

    # We need a temporary session dir for calibrate, as calibrate uses LLMs but
    # doesn't write normal session logs (the API uses the client directly).
    # But Council.__init__ requires a session_dir.
    temp_session_dir = project_root / "runs" / "_temp_calibration_sessions"

    council = Council(
        lineup=lineup,
        session_dir=temp_session_dir,
        mock_mode=args.mock_mode,
    )

    print("Running calibration probes...")
    try:
        report = council.calibrate(probe_set=probes_path)
    except Exception as e:
        print(f"Calibration failed with exception: {e}")
        sys.exit(1)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = project_root / "runs" / "_calibration" / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / "report.json"

    serializable_report = make_report_serializable(report)
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(serializable_report, f, indent=2)

    print("\n=== Calibration Report Summary ===")
    print(f"Overall Disagreement Rate: {report.overall_disagreement_rate:.4f}")
    print(f"Sycophancy Flagged:        {report.flagged_sycophancy}")
    print(f"Number of Probes Run:      {len(report.probe_results)}")
    print(f"Report JSON written to:    {report_file}")
    print("\nNotes:")
    for note in report.notes:
        print(f"  * {note}")
    print("===================================")


def handle_show_report(args: argparse.Namespace) -> None:
    """Handles the 'show-report' subcommand.

    Args:
        args: Parsed CLI arguments.
    """
    logger.info("handle_show_report called with path=%s", args.path)
    report_path = pathlib.Path(args.path)
    if not report_path.exists():
        print(f"Error: Report file not found at {report_path}")
        sys.exit(1)

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    print(f"\n=== Calibration Report ({report_path.name}) ===")
    print(f"Overall Disagreement Rate: {report.get('overall_disagreement_rate', 0.0):.4f}")
    print(f"Sycophancy Flagged:        {report.get('flagged_sycophancy')}")
    print("\nNotes:")
    for note in report.get("notes", []):
        print(f"  * {note}")

    print("\nProbe Details:")
    for pr in report.get("probe_results", []):
        print(f"  - Probe ID: {pr.get('probe_id')}")
        print(f"    Question: {pr.get('question')}")
        print(f"    Disagreement Rate: {pr.get('disagreement_rate', 0.0):.4f}")
        print("    Model Responses:")
        for model, resp in pr.get("responses_by_model", {}).items():
            # Trim/truncate long responses for output readability
            truncated_resp = resp.replace("\n", " ").strip()
            if len(truncated_resp) > 80:
                truncated_resp = truncated_resp[:77] + "..."
            print(f"      * {model}: {truncated_resp}")
        print()
    print("====================================================")


def handle_promote_calibration(args: argparse.Namespace) -> None:
    """Handles the 'promote-calibration' subcommand.

    Args:
        args: Parsed CLI arguments.
    """
    logger.info("handle_promote_calibration called with path=%s", args.path)
    report_path = pathlib.Path(args.path)
    if not report_path.exists():
        print(f"Error: Calibration report not found at {report_path}")
        sys.exit(1)

    try:
        with open(report_path, encoding="utf-8") as f:
            json.load(f)
    except Exception as e:
        print(f"Error: File at {report_path} is not a valid JSON calibration report: {e}")
        sys.exit(1)

    project_root = pathlib.Path(__file__).resolve().parents[2]
    dest = project_root / "config" / "council" / "active_report.json"
    dest.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(report_path, dest)
    print(f"Successfully promoted calibration report {report_path} to {dest}")


def handle_show_session(args: argparse.Namespace) -> None:
    """Handles the 'show-session' subcommand.

    Args:
        args: Parsed CLI arguments.
    """
    logger.info("handle_show_session called with path=%s, verbose=%s", args.path, args.verbose)
    session_path = pathlib.Path(args.path)
    if not session_path.exists():
        print(f"Error: Session file not found at {session_path}")
        sys.exit(1)

    print(f"\n=== Session Log Trace: {session_path.name} ===")
    with open(session_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except Exception as e:
                print(f"[MALFORMED LINE]: {line.strip()} ({e})")
                continue

            ts = event.get("ts", "")
            evt_type = event.get("event", "unknown")

            if evt_type == "session_start":
                print(f"\n[{ts}] SESSION START")
                print(f"  Council ID: {event.get('council_id')}")
                print(f"  Chairman Policy: {event.get('chairman_policy')}")
                print("  Lineup Models:")
                for m in event.get("lineup_models", []):
                    print(
                        f"    - {m.get('openrouter_id')} ({m.get('vendor')}) -> {m.get('persona')}"
                    )

            elif evt_type == "stage1_prompt":
                print(f"\n[{ts}] STAGE 1 PROMPT: {event.get('model_id')} ({event.get('persona')})")
                if args.verbose:
                    print("  --- System Instruction ---")
                    print(event.get("system_instruction"))
                    print("  --- User Content ---")
                    print(event.get("user_content"))
                    print("  --------------------------")
                else:
                    print(f"  System prompt characters: {len(event.get('system_instruction', ''))}")

            elif evt_type == "stage1_response":
                print(f"\n[{ts}] STAGE 1 RESPONSE: {event.get('model_id')}")
                resp = event.get("response", "")
                try:
                    resp_data = json.loads(resp)
                    view = resp_data.get("view", "")
                    self_rank = resp_data.get("self_rank", "")
                    print(f"  Self Rank: {self_rank}")
                    print(f"  View: {view}")
                except Exception:
                    print(f"  Response (raw): {resp}")
                print(
                    f"  Tokens: Input={event.get('input_tokens')}, "
                    f"Output={event.get('output_tokens')}"
                )
                print(f"  Cost: ${event.get('cost_usd', 0.0):.6f}")

            elif evt_type == "sycophancy_detected":
                print(f"\n[{ts}] !!! SYCOPHANCY DETECTED !!!")
                print(f"  Max Agreement: {event.get('max_agreement')}")

            elif evt_type == "stage2_anonymized_prompt":
                print(
                    f"\n[{ts}] STAGE 2 PROMPT (Anonymized Reviewer {event.get('reviewer_voice')})"
                )
                if args.verbose:
                    print("  --- User Content ---")
                    print(event.get("user_content"))
                    print("  --------------------")
                else:
                    print(f"  Reviewees: {event.get('reviewees')}")

            elif evt_type == "stage2_response":
                print(f"\n[{ts}] STAGE 2 RESPONSE (Reviewer {event.get('reviewer_voice')})")
                print(f"  Rankings: {event.get('rankings')}")
                print("  Critiques:")
                for reviewee, critique in event.get("critiques", {}).items():
                    print(f"    - Voice {reviewee}: {critique}")

            elif evt_type == "stage3_chairman_prompt":
                print(f"\n[{ts}] STAGE 3 CHAIRMAN PROMPT (Model: {event.get('chairman_model_id')})")
                if args.verbose:
                    print("  --- User Content ---")
                    print(event.get("user_content"))
                    print("  --------------------")

            elif evt_type == "stage3_response":
                print(f"\n[{ts}] STAGE 3 CHAIRMAN RESPONSE")
                print(f"  Chairman Decision: {event.get('chairman_decision')}")
                print(f"  Majority View: {event.get('majority_view')}")
                print("  Preserved Dissents:")
                for d in event.get("preserved_dissents", []):
                    print(f"    - Model: {d.get('model_id')} ({d.get('persona')})")
                    print(f"      View: {d.get('view')}")
                    print(f"      Rationale: {d.get('rationale')}")

            elif evt_type == "stage3_reprompt_response":
                print(f"\n[{ts}] STAGE 3 CHAIRMAN RE-PROMPT RESPONSE")
                print(f"  Chairman Decision: {event.get('chairman_decision')}")
                print(f"  Majority View: {event.get('majority_view')}")
                print("  Preserved Dissents:")
                for d in event.get("preserved_dissents", []):
                    print(f"    - Model: {d.get('model_id')} ({d.get('persona')})")
                    print(f"      View: {d.get('view')}")
                    print(f"      Rationale: {d.get('rationale')}")

            elif evt_type == "session_end":
                print(f"\n[{ts}] SESSION END")
                print(f"  Verdict Hash: {event.get('verdict_hash')}")
                print(f"  Total Cost: ${event.get('total_cost_usd', 0.0):.6f}")
                print(f"  Duration: {event.get('wall_clock_s', 0.0):.2f}s")

    print("\n=========================================")


def main() -> None:
    """CLI entry point for the council module."""
    logger.info("main() called with args=%s", sys.argv[1:])
    parser = argparse.ArgumentParser(description="Council CLI")
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to execute")

    # show-lineup
    parser_lineup = subparsers.add_parser("show-lineup", help="Display the current lineup")
    parser_lineup.add_argument(
        "--field",
        choices=["vendors", "personas", "models", "all"],
        default="all",
        help="Field to filter print",
    )

    # deliberate
    parser_delib = subparsers.add_parser("deliberate", help="Run a decision council deliberation")
    parser_delib.add_argument(
        "--council-id", required=True, help="Council ID gate to evaluate (e.g. C1)"
    )
    parser_delib.add_argument("--question", help="The objective scientific question to address")
    parser_delib.add_argument(
        "--question-fixture",
        choices=list(FIXTURES.keys()),
        help="Name of question fixture to load",
    )
    parser_delib.add_argument(
        "--context-fixture",
        help="Context fixture name, file path to context JSON, or raw JSON string",
    )
    parser_delib.add_argument(
        "--session-dir",
        help="Directory to write session logs to (defaults to runs/cli_sessions)",
    )
    parser_delib.add_argument(
        "--cost-cap-usd", type=float, help="Optional maximum cost in USD for this run"
    )
    parser_delib.add_argument(
        "--mock-mode", action="store_true", help="Run with mock client offline"
    )

    # certify-live
    parser_cert = subparsers.add_parser(
        "certify-live",
        help="Run a live four-vendor council deliberation with budget and error-path checks",
    )
    parser_cert.add_argument("--council-id", default="C1", help="Council ID gate to evaluate")
    parser_cert.add_argument("--question", help="The objective scientific question to address")
    parser_cert.add_argument(
        "--question-fixture",
        choices=list(FIXTURES.keys()),
        default="sample_worthiness",
        help="Name of question fixture to load",
    )
    parser_cert.add_argument(
        "--context-fixture",
        help="Context fixture name, file path to context JSON, or raw JSON string",
    )
    parser_cert.add_argument(
        "--output-dir",
        help=(
            "Certification output directory "
            "(defaults to runs/live_council_certifications/<timestamp>)"
        ),
    )
    parser_cert.add_argument(
        "--hypothesis-id",
        help="Budget hypothesis ID for the certification run",
    )
    parser_cert.add_argument(
        "--cost-cap-usd",
        type=float,
        default=0.50,
        help="Maximum allowed live council cost in USD",
    )
    parser_cert.add_argument(
        "--token-cap",
        type=int,
        default=2_000_000,
        help="Budget token cap reserved for the certification run",
    )
    parser_cert.add_argument(
        "--wall-clock-cap-seconds",
        type=float,
        default=900.0,
        help="Budget wall-clock cap reserved for the certification run",
    )
    parser_cert.add_argument(
        "--skip-error-path",
        action="store_true",
        help="Skip the live missing-model error-path probe",
    )

    # calibrate
    parser_cal = subparsers.add_parser("calibrate", help="Run calibration probes")
    parser_cal.add_argument(
        "--probe-set", help="Path to probes yaml config (defaults to config/council/probes.yaml)"
    )
    parser_cal.add_argument("--mock-mode", action="store_true", help="Run with mock client offline")

    # show-report
    parser_rep = subparsers.add_parser(
        "show-report", help="Pretty-print calibration report metrics"
    )
    parser_rep.add_argument("--path", required=True, help="Path to the JSON report file")

    # promote-calibration
    parser_prom = subparsers.add_parser(
        "promote-calibration", help="Promote a calibration report to active config"
    )
    parser_prom.add_argument(
        "--path", required=True, help="Path to the JSON report file to promote"
    )

    # show-session
    parser_sess = subparsers.add_parser("show-session", help="Format and print a session log trace")
    parser_sess.add_argument("--path", required=True, help="Path to the JSONL session log file")
    parser_sess.add_argument("--verbose", action="store_true", help="Show full prompt text in logs")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "show-lineup":
        handle_show_lineup(args)
    elif args.command == "deliberate":
        handle_deliberate(args)
    elif args.command == "certify-live":
        handle_certify_live(args)
    elif args.command == "calibrate":
        handle_calibrate(args)
    elif args.command == "show-report":
        handle_show_report(args)
    elif args.command == "promote-calibration":
        handle_promote_calibration(args)
    elif args.command == "show-session":
        handle_show_session(args)


if __name__ == "__main__":
    main()
