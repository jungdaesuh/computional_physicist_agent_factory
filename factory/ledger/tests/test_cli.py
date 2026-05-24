"""Ledger CLI tests."""

from __future__ import annotations

import pytest

from factory.ledger.cli import main


def test_strategy_surprise_query_check_cli(capsys: pytest.CaptureFixture[str]) -> None:
    main(("queries", "check-strategy-surprise"))

    assert capsys.readouterr().out.strip() == (
        '{"check": "strategy-surprise", "row_count": 0, "status": "ok"}'
    )
