from __future__ import annotations

import json

import pytest

import factory.llm_client.cli as cli
from factory.llm_client.pricing import ModelPricing, PricingDocument


def test_list_models_cli_emits_single_json_object(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_get_json(path: str, api_key: str | None = None) -> object:
        assert path == "/models"
        assert api_key == "test-key"
        return {"data": [{"id": "model/b"}, {"id": "model/a"}]}

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(cli, "_get_json", fake_get_json)

    cli.main(["list-models"])

    payload: object = json.loads(capsys.readouterr().out)
    assert payload == {"models": ["model/a", "model/b"]}


def test_pricing_check_cli_emits_single_json_object(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pricing_document = PricingDocument(
        models={"model/a": ModelPricing(1.0, 2.0)},
        last_updated_iso=None,
    )

    def fake_load_pricing_document() -> PricingDocument:
        return pricing_document

    def fake_models_payload() -> dict[str, object]:
        return {
            "data": [
                {
                    "id": "model/a",
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                }
            ]
        }

    monkeypatch.setattr(cli, "load_pricing_document", fake_load_pricing_document)
    monkeypatch.setattr(cli, "_models_payload", fake_models_payload)

    cli.main(["pricing-check"])

    payload: object = json.loads(capsys.readouterr().out)
    assert payload == {
        "checked_models": ["model/a"],
        "drifts": [],
        "status": "ok",
    }
