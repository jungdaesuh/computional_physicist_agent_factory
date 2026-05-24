from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from factory.artifacts import CouncilId
from factory.council.api import Council, CouncilError
from factory.council.mock import MockOpenRouterClient
from factory.llm_client import OpenRouterMessage, OpenRouterResponse, OpenRouterResponseFormat


def _prompt_text(messages: Sequence[OpenRouterMessage]) -> str:
    return "\n".join(message["content"] for message in messages)


def _run_deliberation(tmp_path: Path) -> None:
    council = Council(
        lineup=Council.mock_lineup(),
        session_dir=tmp_path,
        mock_mode=True,
    )
    council.deliberate(
        council_id=CouncilId.C1_WORTHINESS,
        question="Should the council approve this gate?",
        context={"hypothesis_id": "hypothesis-1"},
    )


class _Stage1VendorFailureClient(MockOpenRouterClient):
    def invoke(
        self,
        messages: Sequence[OpenRouterMessage],
        *,
        model: str,
        max_tokens: int = 4096,
        response_format: OpenRouterResponseFormat | None = None,
    ) -> OpenRouterResponse:
        prompt_text = _prompt_text(messages)
        is_stage2_or_stage3 = (
            "reviewer for a decision council" in prompt_text
            or "Chairman for this deliberation cycle" in prompt_text
        )
        if model == "x-ai/grok-4.3" and not is_stage2_or_stage3:
            raise RuntimeError("vendor unavailable")
        return super().invoke(
            messages,
            model=model,
            max_tokens=max_tokens,
            response_format=response_format,
        )


class _Stage2VendorFailureClient(MockOpenRouterClient):
    def invoke(
        self,
        messages: Sequence[OpenRouterMessage],
        *,
        model: str,
        max_tokens: int = 4096,
        response_format: OpenRouterResponseFormat | None = None,
    ) -> OpenRouterResponse:
        prompt_text = _prompt_text(messages)
        if model == "x-ai/grok-4.3" and "reviewer for a decision council" in prompt_text:
            raise RuntimeError("vendor unavailable")
        return super().invoke(
            messages,
            model=model,
            max_tokens=max_tokens,
            response_format=response_format,
        )


def test_stage1_vendor_failure_aborts_deliberation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("factory.council.mock.MockOpenRouterClient", _Stage1VendorFailureClient)

    with pytest.raises(CouncilError, match="Stage 1 failed for model x-ai/grok-4.3"):
        _run_deliberation(tmp_path)


def test_stage2_vendor_failure_aborts_deliberation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("factory.council.mock.MockOpenRouterClient", _Stage2VendorFailureClient)

    with pytest.raises(CouncilError, match="Stage 2 failed for model x-ai/grok-4.3"):
        _run_deliberation(tmp_path)
