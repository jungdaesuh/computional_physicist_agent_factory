"""Command line utilities for the shared OpenRouter LLM client."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.request import Request, urlopen

from factory.llm_client.api import (
    DecisionClient,
    FileClient,
    OpenRouterClient,
    OpenRouterMessage,
    OpenRouterResponseFormat,
)
from factory.llm_client.pricing import (
    INPUT_RATE_KEY,
    OUTPUT_RATE_KEY,
    load_pricing_document,
    parse_openrouter_models_payload,
)

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
DEFAULT_INVOKE_MODEL = "google/gemini-3.5-flash"
FIXTURE_TRANSCRIPT_DIR = Path(__file__).resolve().parent / "fixtures" / "transcripts"


def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key is None or key == "":
        raise SystemExit("OPENROUTER_API_KEY is required")
    return key


def _get_json(path: str, api_key: str | None = None) -> object:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key is not None else {}
    request = Request(f"{OPENROUTER_API_BASE}{path}", headers=headers)
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def _as_json_object(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise SystemExit(f"{context} returned a non-object payload")
    raw_mapping: Mapping[object, object] = value
    parsed: dict[str, object] = {}
    for key, item in raw_mapping.items():
        if not isinstance(key, str):
            raise SystemExit(f"{context} returned a non-string key")
        parsed[key] = item
    return parsed


def _print_json(payload: Mapping[str, object]) -> None:
    print(json.dumps(dict(payload), sort_keys=True))


def _models_payload() -> dict[str, object]:
    return _as_json_object(_get_json("/models", _api_key()), context="OpenRouter /models")


def _verify_key() -> None:
    payload = _as_json_object(_get_json("/key", _api_key()), context="OpenRouter /key")
    _print_json(payload)


def _list_models() -> None:
    payload = _models_payload()
    data = payload.get("data")
    if not isinstance(data, list):
        raise SystemExit("OpenRouter /models response is missing data[]")
    model_ids: list[str] = []
    for item in data:
        if not isinstance(item, Mapping):
            raise SystemExit("OpenRouter /models data[] item is not an object")
        item_mapping: Mapping[object, object] = item
        model_id = item_mapping.get("id")
        if not isinstance(model_id, str):
            raise SystemExit("OpenRouter /models data[] item is missing id")
        model_ids.append(model_id)
    _print_json({"models": sorted(model_ids)})


def _fixture_path(fixture: str) -> Path:
    fixture_name = fixture if fixture.endswith(".json") else f"{fixture}.json"
    return FIXTURE_TRANSCRIPT_DIR / fixture_name


def _parse_messages_json(raw_messages: str) -> list[OpenRouterMessage]:
    parsed_messages: object = json.loads(raw_messages)
    if not isinstance(parsed_messages, list):
        raise SystemExit("--messages-json must be a JSON array")

    messages: list[OpenRouterMessage] = []
    for index, item in enumerate(parsed_messages):
        if not isinstance(item, Mapping):
            raise SystemExit(f"--messages-json item {index} must be an object")
        item_mapping: Mapping[object, object] = item
        role = item_mapping.get("role")
        content = item_mapping.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            raise SystemExit(f"--messages-json item {index} must include string role and content")
        messages.append({"role": role, "content": content})
    return messages


def _messages(
    message: str | None,
    messages_json: str | None,
    *,
    mock_mode: bool,
) -> list[OpenRouterMessage]:
    if messages_json is not None:
        return _parse_messages_json(messages_json)
    if message is not None:
        return [{"role": "user", "content": message}]
    if mock_mode:
        return []
    raise SystemExit("--message or --messages-json is required unless --mock-mode is used")


def _json_response_format() -> OpenRouterResponseFormat:
    return {"type": "json_object"}


def _invoke(args: argparse.Namespace) -> None:
    if args.fixture is not None and args.transcript_path is not None:
        raise SystemExit("--fixture and --transcript-path are mutually exclusive")

    client: DecisionClient
    if args.fixture is not None:
        client = FileClient(_fixture_path(args.fixture))
    elif args.transcript_path is not None:
        client = FileClient(Path(args.transcript_path))
    elif args.mock_mode:
        raise SystemExit("--mock-mode requires --fixture or --transcript-path")
    else:
        client = OpenRouterClient(api_key=args.api_key)

    response_format = _json_response_format() if args.json_mode else None
    response = client.invoke(
        _messages(args.message, args.messages_json, mock_mode=args.mock_mode),
        model=args.model,
        max_tokens=args.max_tokens,
        response_format=response_format,
    )
    _print_json(
        {
            "cost_usd": response.cost_usd,
            "input_tokens": response.input_tokens,
            "model_id_actual": response.model_id_actual,
            "output_tokens": response.output_tokens,
            "text": response.text,
        }
    )


def _pricing_check() -> None:
    local_document = load_pricing_document()
    live_pricing = parse_openrouter_models_payload(_models_payload(), local_document.models)
    drifts: list[str] = []
    for model_id, local_pricing in sorted(local_document.models.items()):
        live_rates = live_pricing[model_id].as_yaml_mapping()
        live_input = live_rates[INPUT_RATE_KEY]
        live_output = live_rates[OUTPUT_RATE_KEY]
        if (
            abs(local_pricing.input_per_1m_tokens_usd - live_input) > 1e-9
            or abs(local_pricing.output_per_1m_tokens_usd - live_output) > 1e-9
        ):
            drifts.append(
                f"{model_id}: local input/output "
                f"{local_pricing.input_per_1m_tokens_usd:g}/"
                f"{local_pricing.output_per_1m_tokens_usd:g}, live input/output "
                f"{live_input:g}/{live_output:g}"
            )
    payload: dict[str, object] = {
        "checked_models": sorted(local_document.models),
        "drifts": drifts,
        "status": "ok" if not drifts else "drift",
    }
    if drifts:
        _print_json(payload)
        raise SystemExit(1)
    _print_json(payload)


def main(argv: Sequence[str] | None = None) -> None:
    """Run an LLM client maintenance command."""
    parser = argparse.ArgumentParser(description="OpenRouter LLM client utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)
    invoke_parser = subparsers.add_parser(
        "invoke", help="Invoke a model or replay transcript fixture"
    )
    invoke_parser.add_argument("--model", default=DEFAULT_INVOKE_MODEL, help="OpenRouter model ID")
    invoke_parser.add_argument("--message", help="Single user message to send")
    invoke_parser.add_argument("--messages-json", help="JSON array of {role, content} messages")
    invoke_parser.add_argument("--max-tokens", type=int, default=4096, help="Completion token cap")
    invoke_parser.add_argument(
        "--json-mode", action="store_true", help="Request JSON object output"
    )
    invoke_parser.add_argument(
        "--mock-mode", action="store_true", help="Replay a transcript fixture"
    )
    invoke_parser.add_argument(
        "--fixture", help="Fixture transcript name under fixtures/transcripts"
    )
    invoke_parser.add_argument("--transcript-path", help="Explicit FileClient transcript path")
    invoke_parser.add_argument("--api-key", help="OpenRouter API key for live invocation")
    subparsers.add_parser("verify-key", help="Show current key limits and usage")
    subparsers.add_parser("list-models", help="List live OpenRouter model IDs")
    subparsers.add_parser("pricing-check", help="Verify local pricing rates match OpenRouter")

    args = parser.parse_args(argv)
    if args.command == "invoke":
        _invoke(args)
    elif args.command == "verify-key":
        _verify_key()
    elif args.command == "list-models":
        _list_models()
    elif args.command == "pricing-check":
        _pricing_check()
