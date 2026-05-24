# test_llm_client_typical_usage.py — Integration-style test for llm_client typical usage
#
# This test demonstrates the typical usage of DecisionClient, FileClient, and
# RateLimitedDecisionClient using a mock transcript.

import logging
from pathlib import Path

import pytest

from factory.llm_client import (
    FileClient,
    LLMClientError,
    OpenRouterResponse,
    RateLimitedDecisionClient,
)

logger = logging.getLogger("factory.llm_client.tests")


def test_llm_client_typical_usage() -> None:
    """Demonstrates typical usage of the llm_client module."""
    logger.info("Running typical usage test for llm_client")

    transcript_path = Path(__file__).resolve().parent / "sample_transcript.json"
    client = FileClient(transcript_path)

    # Wrap with rate limiter
    rate_limited_client = RateLimitedDecisionClient(client, rps=10.0)

    messages = [{"role": "user", "content": "Hello"}]

    # First invoke
    response = rate_limited_client.invoke(messages, model="google/gemini-3.5-flash")
    assert isinstance(response, OpenRouterResponse)
    assert response.text == "Hello, this is typical response 1"
    assert response.model_id_actual == "google/gemini-3.5-flash"
    assert response.input_tokens == 10
    assert response.output_tokens == 20
    assert response.cost_usd > 0.0

    # Second invoke
    response = rate_limited_client.invoke(messages, model="google/gemini-3.5-flash")
    assert response.text == "Hello, this is typical response 2"
    assert response.input_tokens == 15
    assert response.output_tokens == 25
    assert response.cost_usd > 0.0

    with pytest.raises(LLMClientError, match="Transcript exhausted"):
        rate_limited_client.invoke(messages, model="google/gemini-3.5-flash")
