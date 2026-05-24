# test_pricing.py — Strict OpenRouter pricing helper tests

from __future__ import annotations

from pathlib import Path

import pytest

from factory.budget import BudgetTokenUsageMissing
from factory.llm_client.pricing import (
    ModelPricing,
    PricingConfigError,
    fetch_openrouter_pricing,
    load_pricing_document,
    parse_openrouter_models_payload,
    update_pricing_config,
)


def test_load_pricing_document_fails_loudly_on_missing_file(tmp_path: Path) -> None:
    """Missing pricing config cannot fall back to hard-coded defaults."""
    with pytest.raises(PricingConfigError, match="missing"):
        load_pricing_document(tmp_path / "missing.yaml")


def test_load_pricing_document_fails_loudly_on_malformed_model(tmp_path: Path) -> None:
    """A requested pricing table with missing rates is invalid."""
    pricing_path = tmp_path / "openrouter.yaml"
    pricing_path.write_text(
        """
models:
  google/gemini-3.5-flash:
    input_per_1m_tokens_usd: 0.075
""",
        encoding="utf-8",
    )

    with pytest.raises(PricingConfigError, match="output_per_1m_tokens_usd"):
        load_pricing_document(pricing_path)


def test_parse_openrouter_payload_requires_requested_models() -> None:
    """Payload parsing fails loudly when a requested model is absent."""
    payload = {"data": [{"id": "present/model", "pricing": {"prompt": "0.1", "completion": "0.2"}}]}

    with pytest.raises(BudgetTokenUsageMissing) as exc_info:
        parse_openrouter_models_payload(payload, ("missing/model",))

    assert exc_info.value.model_id == "missing/model"


def test_fetch_openrouter_pricing_success() -> None:
    """Verifies successful pricing parsing from an OpenRouter models payload."""
    payload = {
        "data": [
            {
                "id": "openai/gpt-5.5",
                "pricing": {"prompt": "0.000020", "completion": "0.000080"},
            }
        ]
    }

    result = fetch_openrouter_pricing(payload, ("openai/gpt-5.5",))

    assert result["openai/gpt-5.5"]["input_per_1m_tokens_usd"] == 20.0
    assert result["openai/gpt-5.5"]["output_per_1m_tokens_usd"] == 80.0


def test_fetch_openrouter_pricing_uses_supplied_opener() -> None:
    """The helper fetches through the caller-owned opener without hidden fallback."""
    payload = """
{
  "data": [
    {
      "id": "openai/gpt-5.5",
      "pricing": {"prompt": "0.000015", "completion": "0.000075"}
    }
  ]
}
"""
    opened_urls: list[str] = []

    def opener(url: str) -> str:
        opened_urls.append(url)
        return payload

    result = fetch_openrouter_pricing(
        "https://openrouter.ai/api/v1/models",
        ("openai/gpt-5.5",),
        opener=opener,
    )

    assert opened_urls == ["https://openrouter.ai/api/v1/models"]
    assert result["openai/gpt-5.5"]["input_per_1m_tokens_usd"] == 15.0
    assert result["openai/gpt-5.5"]["output_per_1m_tokens_usd"] == 75.0


def test_fetch_openrouter_pricing_requires_opener_for_url() -> None:
    """URL fetching must be explicit so CLI/network behavior cannot hide stale prices."""
    with pytest.raises(PricingConfigError, match="opener is required"):
        fetch_openrouter_pricing(
            "https://openrouter.ai/api/v1/models",
            ("openai/gpt-5.5",),
        )


def test_fetch_openrouter_pricing_fails_loudly_without_requested_model() -> None:
    """Missing requested models remain a budget-accounting error."""
    payload = {
        "data": [
            {
                "id": "openai/gpt-5.5",
                "pricing": {"prompt": "0.000020", "completion": "0.000080"},
            }
        ]
    }

    with pytest.raises(BudgetTokenUsageMissing) as exc_info:
        fetch_openrouter_pricing(payload, ("missing/model",))

    assert exc_info.value.model_id == "missing/model"


def test_update_pricing_config_replaces_with_validated_table(tmp_path: Path) -> None:
    """The update helper writes a complete typed pricing document."""
    pricing_path = tmp_path / "openrouter.yaml"

    update_pricing_config(
        {
            "openai/gpt-5.5": {
                "input_per_1m_tokens_usd": 20.0,
                "output_per_1m_tokens_usd": 80.0,
            }
        },
        config_path=pricing_path,
    )

    document = load_pricing_document(pricing_path)
    assert document.models == {
        "openai/gpt-5.5": ModelPricing(
            input_per_1m_tokens_usd=20.0,
            output_per_1m_tokens_usd=80.0,
        )
    }
    assert document.last_updated_iso is not None
