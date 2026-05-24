"""Factory operator command line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections.abc import Sequence

from factory.operator.api import NonLoopbackBindRejected


from factory.state_machine import (
    CycleTaskInput,
    GateTaskInput,
    GateTaskResult,
    run_cycles_concurrently,
)
from factory.state_machine.concurrency import GateName

logger = logging.getLogger("factory.operator.cli")
DEFAULT_MOCK_GATES: tuple[GateName, ...] = ("G1", "G2", "G3", "G4", "G5", "G6")


async def _mock_gate_executor(task_input: GateTaskInput) -> GateTaskResult:
    return GateTaskResult(
        gate=task_input.gate,
        status="passed",
        detail=f"mock {task_input.gate} passed for {task_input.hypothesis_id}",
    )


def _bounded_cycle_count(cycles: int, multi_cycle: bool) -> int:
    if cycles < 1:
        raise SystemExit("--cycles must be at least 1")
    if multi_cycle and cycles == 1:
        return 2
    return cycles


def _start_mock(cycles: int, *, multi_cycle: bool, output_format: str) -> None:
    cycle_count = _bounded_cycle_count(cycles, multi_cycle)
    cycle_inputs = tuple(
        CycleTaskInput(
            cycle_id=f"mock-cycle-{index + 1}",
            hypothesis_id=f"mock-hypothesis-{index + 1}",
            gates=DEFAULT_MOCK_GATES,
            state_payload={"mode": "mock"},
        )
        for index in range(cycle_count)
    )
    results = asyncio.run(run_cycles_concurrently(cycle_inputs, _mock_gate_executor))
    if output_format == "json":
        print(json.dumps({"event": "factory_start", "mode": "mock", "cycles": cycle_count}))
        for result in results:
            print(
                json.dumps(
                    {
                        "event": "cycle_complete",
                        "cycle_id": result.cycle_id,
                        "hypothesis_id": result.hypothesis_id,
                        "completed_gates": list(result.completed_gates),
                    }
                )
            )
        print(json.dumps({"event": "factory_stop", "reason": "cycle_bound_reached"}))
    else:
        print(f"factory start: mock mode, cycles={cycle_count}")
        for result in results:
            gates = ",".join(result.completed_gates)
            print(f"{result.cycle_id}: completed gates {gates}")
        print("factory stop: cycle_bound_reached")


def _run_start(args: argparse.Namespace) -> None:
    if not args.mock_mode:
        raise SystemExit("factory start currently requires --mock-mode")
    _start_mock(
        cycles=args.cycles,
        multi_cycle=args.multi_cycle,
        output_format=args.output_format,
    )


def _run_serve(args: argparse.Namespace) -> None:
    host = args.host
    port = args.port
    mock_mode = args.mock_mode or os.environ.get("FACTORY_MOCK") == "1"

    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise NonLoopbackBindRejected(
            f"Non-loopback bind address {host!r} rejected in Phase A/B."
        )

    if not mock_mode:
        if "OPENROUTER_API_KEY" not in os.environ:
            logger.warning(
                "OPENROUTER_API_KEY not set; live council deliberation and "
                "agentic LLM calls will fail"
            )
            print(
                "WARN: OPENROUTER_API_KEY not set; live council deliberation and "
                "agentic LLM calls will fail",
                file=sys.stderr,
            )

    if mock_mode:
        os.environ["FACTORY_MOCK"] = "1"

    import uvicorn
    print(f"Starting operator HTTP server on {host}:{port} (mock_mode={mock_mode})...")
    uvicorn.run("factory.operator.http:app", host=host, port=port, log_level="info")



def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point for the operator module."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
    logger.info("main() called with args=%s", raw_args)
    parser = argparse.ArgumentParser(description="Operator CLI")
    parser.add_argument("--mock-mode", action="store_true", help="Run in mock mode")
    subparsers = parser.add_subparsers(dest="command")

    start_parser = subparsers.add_parser("start", help="Start the factory control loop")
    start_parser.add_argument("--mock-mode", action="store_true", help="Run in mock mode")
    start_parser.add_argument("--multi-cycle", action="store_true", help="Run at least two cycles")
    start_parser.add_argument("--cycles", type=int, default=1, help="Bounded cycle count")
    start_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        dest="output_format",
        help="Output format",
    )
    start_parser.set_defaults(handler=_run_start)

    serve_parser = subparsers.add_parser("serve", help="Start the FastAPI HTTP server")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host address to bind to")
    serve_parser.add_argument("--port", type=int, default=8765, help="Port to run the HTTP daemon on")
    serve_parser.set_defaults(handler=_run_serve)


    args = parser.parse_args(raw_args)

    handler = getattr(args, "handler", None)
    if handler is not None:
        handler(args)
        return

    if args.mock_mode:
        print("Running operator in mock mode.")
    else:
        print("Running operator in live mode.")


if __name__ == "__main__":
    main()
