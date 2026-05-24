from __future__ import annotations

import json
from pathlib import Path

import pytest

from factory.literature.cli import main


def test_literature_cli_mine_gaps_mock_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(
        (
            "--mock-mode",
            "--graph-db",
            str(tmp_path / "graph.sqlite"),
            "--paper-store",
            str(tmp_path / "papers"),
            "mine-gaps",
            "--seed-query",
            "stellarator coil",
            "--max-depth",
            "1",
            "--branch-factor",
            "2",
        )
    )

    output = json.loads(capsys.readouterr().out)
    assert output["gap_types"] == [
        "structural_hole",
        "methodology_transfer",
        "contradiction",
        "negative_result",
    ]
    assert output["promoted"]
    assert output["source_papers"] == output["promoted"]


def test_literature_cli_mine_gaps_limits_sources_to_promoted_papers(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(
        (
            "--mock-mode",
            "--graph-db",
            str(tmp_path / "graph.sqlite"),
            "--paper-store",
            str(tmp_path / "papers"),
            "mine-gaps",
            "--seed-query",
            "stellarator coil",
            "--limit",
            "3",
            "--promote-top-k",
            "1",
            "--max-depth",
            "1",
            "--branch-factor",
            "3",
        )
    )

    output = json.loads(capsys.readouterr().out)
    assert output["promoted"] == ["W-MOCK-BACKWARD"]
    assert output["source_papers"] == ["W-MOCK-BACKWARD"]


def test_literature_cli_core_subcommands_work_in_mock_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph_db = tmp_path / "graph.sqlite"
    paper_store = tmp_path / "papers"
    base_args = (
        "--mock-mode",
        "--graph-db",
        str(graph_db),
        "--paper-store",
        str(paper_store),
    )

    main((*base_args, "seed-search", "--query", "quasi isodynamic", "--limit", "1"))
    seed_output = json.loads(capsys.readouterr().out)
    assert seed_output["work_ids"] == ["W-MOCK-ROOT"]

    main(
        (
            *base_args,
            "traverse",
            "--seed-ids",
            "W-MOCK-ROOT",
            "--max-depth",
            "1",
            "--branch-factor",
            "3",
        )
    )
    traverse_output = json.loads(capsys.readouterr().out)
    assert set(traverse_output["work_ids"]) == {
        "W-MOCK-ROOT",
        "W-MOCK-BACKWARD",
        "W-MOCK-RELATED",
    }

    main(
        (
            *base_args,
            "rank",
            "--seed-ids",
            "W-MOCK-ROOT",
            "--max-depth",
            "1",
            "--branch-factor",
            "3",
        )
    )
    rank_output = json.loads(capsys.readouterr().out)
    assert rank_output["work_ids"][0] == "W-MOCK-BACKWARD"

    main((*base_args, "promote", "--work-ids", "W-MOCK-ROOT"))
    promote_output = json.loads(capsys.readouterr().out)
    assert promote_output == {"promoted": ["W-MOCK-ROOT"]}
    assert (paper_store / "W-MOCK-ROOT" / "work.json").is_file()

    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("OPENALEX_EMAIL", raising=False)
    main(("--graph-db", str(graph_db), "show-graph"))
    show_output = json.loads(capsys.readouterr().out)
    assert show_output["works"] >= 1
