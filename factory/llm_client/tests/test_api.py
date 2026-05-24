# test_api.py — Unit tests for the llm_client API
#
# Verifies configuration handling, error raising, and client constructors.

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from factory.budget import BudgetTokenUsageMissing
from factory.llm_client import (
    OpenRouterAuthError,
    OpenRouterClient,
    OpenRouterMessage,
    OpenRouterModelUnavailable,
    OpenRouterResponse,
    OpenRouterResponseFormat,
    RateLimitedDecisionClient,
    get_process_token_bucket,
)
from factory.llm_client import api as llm_api


def test_missing_api_key_raises_auth_error() -> None:
    """Verifies that invoking OpenRouterClient without an API key raises OpenRouterAuthError."""
    import os

    orig_key = os.environ.get("OPENROUTER_API_KEY")
    if "OPENROUTER_API_KEY" in os.environ:
        del os.environ["OPENROUTER_API_KEY"]

    try:
        # Instantiating now with no key in env
        client = OpenRouterClient(api_key=None)
        with pytest.raises(OpenRouterAuthError):
            client.invoke([{"role": "user", "content": "Hi"}], model="google/gemini-3.5-flash")
    finally:
        if orig_key is not None:
            os.environ["OPENROUTER_API_KEY"] = orig_key


def test_missing_pricing_entry_raises_budget_usage_error() -> None:
    """Unknown model IDs cannot silently inherit another model's price."""
    client = OpenRouterClient(api_key="test")

    with pytest.raises(BudgetTokenUsageMissing) as exc_info:
        client.calculate_cost("missing/model", input_tokens=1, output_tokens=1)

    assert exc_info.value.module == "llm_client"
    assert exc_info.value.model_id == "missing/model"
    assert exc_info.value.description == "pricing entry missing"


def test_missing_response_usage_raises_budget_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenRouter 200 responses without token usage cannot be costed."""

    class _Message:
        content = "ok"

    class _Choice:
        message = _Message()

    class _Response:
        usage = None
        choices = [_Choice()]
        model = "google/gemini-3.5-flash"

    class _Completions:
        def create(self, **kwargs: object) -> _Response:
            assert kwargs["model"] == "google/gemini-3.5-flash"
            assert kwargs["max_completion_tokens"] == 4096
            assert "max_tokens" not in kwargs
            assert "temperature" not in kwargs
            return _Response()

    class _Chat:
        completions = _Completions()

    class _SDK:
        chat = _Chat()

    client = OpenRouterClient(api_key="test")
    monkeypatch.setattr(client, "_get_client", lambda: _SDK())

    with pytest.raises(BudgetTokenUsageMissing) as exc_info:
        client.invoke(
            [{"role": "user", "content": "hello"}],
            model="google/gemini-3.5-flash",
        )

    assert exc_info.value.module == "llm_client"
    assert exc_info.value.model_id == "google/gemini-3.5-flash"
    assert exc_info.value.description == "usage block absent"


def test_bad_request_model_error_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenRouter invalid-model 400s are model configuration failures, not transient API errors."""

    class _BadRequestError(Exception):
        pass

    class _Completions:
        calls = 0

        def create(self, **kwargs: object) -> object:
            del kwargs
            self.calls += 1
            raise _BadRequestError("openai/missing-model is not a valid model ID")

    class _Chat:
        completions = _Completions()

    class _SDK:
        chat = _Chat()

    client = OpenRouterClient(api_key="test")
    monkeypatch.setattr(llm_api, "BadRequestError", _BadRequestError)
    monkeypatch.setattr(client, "_get_client", lambda: _SDK())

    with pytest.raises(OpenRouterModelUnavailable):
        client.invoke(
            [{"role": "user", "content": "hello"}],
            model="openai/missing-model",
        )

    assert _SDK.chat.completions.calls == 1


def test_rate_limited_clients_share_process_token_bucket() -> None:
    """Separate wrappers with the same rate/capacity consume the same process bucket."""

    class _Inner:
        def invoke(
            self,
            messages: Sequence[OpenRouterMessage],
            *,
            model: str,
            max_tokens: int = 4096,
            response_format: OpenRouterResponseFormat | None = None,
        ) -> OpenRouterResponse:
            del messages, model, max_tokens, response_format
            return OpenRouterResponse(
                text="ok",
                model_id_actual="test/model",
                input_tokens=1,
                output_tokens=1,
                cost_usd=0.0,
            )

    rps = 0.01
    capacity = 2.0
    first = RateLimitedDecisionClient(_Inner(), rps=rps, capacity=capacity)
    second = RateLimitedDecisionClient(_Inner(), rps=rps, capacity=capacity)

    first.invoke([], model="test/model")
    second.invoke([], model="test/model")

    shared_bucket = get_process_token_bucket(rps=rps, capacity=capacity)
    assert not shared_bucket.try_acquire()


def test_invoke_cli_replays_mock_fixture() -> None:
    """The documented invoke CLI works in fixture-backed mock mode."""
    project_root = Path(__file__).resolve().parents[3]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "factory.llm_client",
            "invoke",
            "--mock-mode",
            "--fixture",
            "sample_round_trip",
            "--model",
            "google/gemini-3.5-flash",
            "--message",
            "Hello",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["text"] == "fixture response"
    assert payload["model_id_actual"] == "google/gemini-3.5-flash"
    assert payload["input_tokens"] == 11
    assert payload["output_tokens"] == 7
    assert payload["cost_usd"] > 0.0
