"""Strict OpenRouter pricing configuration helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

import yaml

from factory.artifacts import FactoryError
from factory.budget import BudgetTokenUsageMissing

DEFAULT_OPENROUTER_PRICING_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "pricing" / "openrouter.yaml"
)
INPUT_RATE_KEY = "input_per_1m_tokens_usd"
OUTPUT_RATE_KEY = "output_per_1m_tokens_usd"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


class PricingConfigError(FactoryError):
    """Raised when the OpenRouter pricing config is missing or malformed."""


@dataclass(frozen=True)
class ModelPricing:
    """Per-model OpenRouter rates in USD per 1,000,000 tokens."""

    input_per_1m_tokens_usd: float
    output_per_1m_tokens_usd: float

    def as_yaml_mapping(self) -> dict[str, float]:
        """Return the persisted YAML representation."""
        return {
            INPUT_RATE_KEY: self.input_per_1m_tokens_usd,
            OUTPUT_RATE_KEY: self.output_per_1m_tokens_usd,
        }


@dataclass(frozen=True)
class PricingDocument:
    """Typed representation of config/pricing/openrouter.yaml."""

    models: dict[str, ModelPricing]
    last_updated_iso: str | None

    def as_yaml_mapping(self) -> dict[str, object]:
        """Return the complete YAML document representation."""
        document: dict[str, object] = {
            "models": {
                model_id: pricing.as_yaml_mapping()
                for model_id, pricing in sorted(self.models.items())
            }
        }
        if self.last_updated_iso is not None:
            document["last_updated_iso"] = self.last_updated_iso
        return document


class UrlOpener(Protocol):
    """Small URL opener contract for offline tests and CLI callers."""

    def __call__(self, url: str) -> str:
        """Return the response body for the URL."""
        ...


def _as_object_mapping(value: object, *, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PricingConfigError(f"{context} must be a mapping.")
    return value


def _as_model_id(value: object, *, context: str) -> str:
    if not isinstance(value, str) or value == "":
        raise PricingConfigError(f"{context} must be a non-empty string.")
    return value


def _as_nonnegative_float(value: object, *, context: str) -> float:
    if not isinstance(value, int | float | str) or isinstance(value, bool):
        raise PricingConfigError(f"{context} must be numeric.")
    try:
        numeric = float(value)
    except ValueError as exc:
        raise PricingConfigError(f"{context} must be numeric.") from exc
    if numeric < 0.0:
        raise PricingConfigError(f"{context} must be non-negative.")
    return numeric


def _parse_model_pricing(value: object, *, model_id: str) -> ModelPricing:
    model_data = _as_object_mapping(value, context=f"pricing for {model_id}")
    if INPUT_RATE_KEY not in model_data:
        raise PricingConfigError(f"pricing for {model_id} is missing {INPUT_RATE_KEY}.")
    if OUTPUT_RATE_KEY not in model_data:
        raise PricingConfigError(f"pricing for {model_id} is missing {OUTPUT_RATE_KEY}.")
    return ModelPricing(
        input_per_1m_tokens_usd=_as_nonnegative_float(
            model_data[INPUT_RATE_KEY],
            context=f"pricing for {model_id}.{INPUT_RATE_KEY}",
        ),
        output_per_1m_tokens_usd=_as_nonnegative_float(
            model_data[OUTPUT_RATE_KEY],
            context=f"pricing for {model_id}.{OUTPUT_RATE_KEY}",
        ),
    )


def _parse_last_updated(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value != "":
        return value
    raise PricingConfigError("last_updated_iso must be a non-empty ISO date string.")


def load_pricing_document(
    path: Path = DEFAULT_OPENROUTER_PRICING_PATH,
) -> PricingDocument:
    """Load and validate the complete OpenRouter pricing YAML document."""
    if not path.exists():
        raise PricingConfigError(f"OpenRouter pricing config is missing: {path}")

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PricingConfigError(f"OpenRouter pricing config is malformed YAML: {path}") from exc

    root = _as_object_mapping(loaded, context="OpenRouter pricing config")
    models_raw = _as_object_mapping(root.get("models"), context="OpenRouter pricing models")
    models: dict[str, ModelPricing] = {}
    for raw_model_id, raw_pricing in models_raw.items():
        model_id = _as_model_id(raw_model_id, context="OpenRouter pricing model ID")
        models[model_id] = _parse_model_pricing(raw_pricing, model_id=model_id)
    if not models:
        raise PricingConfigError("OpenRouter pricing config must define at least one model.")

    return PricingDocument(
        models=models,
        last_updated_iso=_parse_last_updated(root.get("last_updated_iso")),
    )


def load_pricing_table(
    path: Path = DEFAULT_OPENROUTER_PRICING_PATH,
) -> dict[str, dict[str, float]]:
    """Load pricing as the legacy model-id-to-rate mapping without defaults."""
    document = load_pricing_document(path)
    return {model_id: pricing.as_yaml_mapping() for model_id, pricing in document.models.items()}


def require_model_pricing(
    model_id: str,
    pricing: Mapping[str, ModelPricing],
) -> ModelPricing:
    """Return a requested model price or raise the budget accounting error."""
    model_pricing = pricing.get(model_id)
    if model_pricing is None:
        raise BudgetTokenUsageMissing(
            module="llm_client",
            model_id=model_id,
            description="pricing entry missing",
        )
    return model_pricing


def calculate_model_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    pricing: Mapping[str, ModelPricing],
) -> float:
    """Calculate request cost from strict model pricing and token usage."""
    model_pricing = require_model_pricing(model_id, pricing)
    return (
        input_tokens * model_pricing.input_per_1m_tokens_usd / 1_000_000.0
        + output_tokens * model_pricing.output_per_1m_tokens_usd / 1_000_000.0
    )


def write_pricing_document(
    document: PricingDocument,
    path: Path = DEFAULT_OPENROUTER_PRICING_PATH,
) -> None:
    """Write a complete replacement OpenRouter pricing YAML document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(document.as_yaml_mapping(), sort_keys=False),
        encoding="utf-8",
    )


def update_openrouter_pricing(
    models: Mapping[str, ModelPricing],
    path: Path = DEFAULT_OPENROUTER_PRICING_PATH,
    *,
    last_updated_iso: str | None = None,
) -> PricingDocument:
    """Replace the local pricing document with a typed model table."""
    document = PricingDocument(
        models=dict(models),
        last_updated_iso=last_updated_iso or datetime.now(UTC).date().isoformat(),
    )
    write_pricing_document(document, path)
    return document


def parse_openrouter_models_payload(
    payload: str | Mapping[str, object],
    requested_model_ids: Iterable[str],
) -> dict[str, ModelPricing]:
    """Extract requested model prices from an OpenRouter /models payload."""
    root = json.loads(payload) if isinstance(payload, str) else payload
    root_mapping = _as_object_mapping(root, context="OpenRouter models payload")
    data = root_mapping.get("data")
    if not isinstance(data, list):
        raise PricingConfigError("OpenRouter models payload is missing data[].")

    parsed: dict[str, ModelPricing] = {}
    requested = tuple(requested_model_ids)
    for item in data:
        item_mapping = _as_object_mapping(item, context="OpenRouter model item")
        raw_model_id = item_mapping.get("id")
        if raw_model_id not in requested:
            continue
        model_id = _as_model_id(raw_model_id, context="OpenRouter model ID")
        pricing_raw = _as_object_mapping(
            item_mapping.get("pricing"),
            context=f"OpenRouter live pricing for {model_id}",
        )
        prompt_rate = _as_nonnegative_float(
            pricing_raw.get("prompt"),
            context=f"OpenRouter live pricing for {model_id}.prompt",
        )
        completion_rate = _as_nonnegative_float(
            pricing_raw.get("completion"),
            context=f"OpenRouter live pricing for {model_id}.completion",
        )
        parsed[model_id] = ModelPricing(
            input_per_1m_tokens_usd=prompt_rate * 1_000_000.0,
            output_per_1m_tokens_usd=completion_rate * 1_000_000.0,
        )

    missing = sorted(set(requested) - set(parsed))
    if missing:
        raise BudgetTokenUsageMissing(
            module="llm_client",
            model_id=", ".join(missing),
            description="pricing entry missing",
        )
    return parsed


def fetch_openrouter_models_payload(url: str, opener: UrlOpener) -> str:
    """Fetch an OpenRouter payload through a caller-supplied opener."""
    return opener(url)


def fetch_openrouter_pricing(
    payload_or_url: str | Mapping[str, object],
    requested_model_ids: Iterable[str],
    *,
    opener: UrlOpener | None = None,
) -> dict[str, dict[str, float]]:
    """Parse requested OpenRouter pricing from a payload or caller-supplied URL opener."""
    if isinstance(payload_or_url, str) and payload_or_url.startswith(("http://", "https://")):
        if opener is None:
            raise PricingConfigError("opener is required when fetching pricing from a URL.")
        payload: str | Mapping[str, object] = fetch_openrouter_models_payload(
            payload_or_url,
            opener,
        )
    else:
        payload = payload_or_url
    parsed = parse_openrouter_models_payload(payload, requested_model_ids)
    return {model_id: pricing.as_yaml_mapping() for model_id, pricing in parsed.items()}


def update_pricing_config(
    pricing_data: Mapping[str, Mapping[str, float]],
    config_path: Path = DEFAULT_OPENROUTER_PRICING_PATH,
) -> PricingDocument:
    """Replace the local YAML config with a validated pricing table."""
    models = {
        model_id: _parse_model_pricing(prices, model_id=model_id)
        for model_id, prices in pricing_data.items()
    }
    return update_openrouter_pricing(models, config_path)
