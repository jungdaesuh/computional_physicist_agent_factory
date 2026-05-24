# test_council_typical_usage.py — Integration test showing typical usage
#
# This test acts as live documentation for the module's public API.

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from factory.artifacts import CouncilId, CouncilVerdict
from factory.council.api import (
    CalibrationReport,
    Council,
)

logger = logging.getLogger("factory.council.tests.test_council_typical_usage")


def test_council_typical_usage(tmp_path: Path) -> None:
    """Demonstrates typical usage of the council module Python API and CLI subcommands."""
    logger.info("Running typical usage test for council")

    # 1. Initialize Council using mock lineup and mock_mode=True
    lineup = Council.mock_lineup()
    assert len(lineup.models) == 4
    assert set(lineup.persona_assignment.values()) == {"pessimist", "visionary", "pragmatist"}

    council = Council(
        lineup=lineup,
        session_dir=tmp_path,
        mock_mode=True,
    )

    # 2. Run deliberate API
    question = "Is StellaEvolve worthy of a C1 gate approval?"
    context = {"gap": "DESC optimization structural holes"}

    verdict = council.deliberate(
        council_id=CouncilId.C1_WORTHINESS,
        question=question,
        context=context,
    )

    # 3. Assert on the returned CouncilVerdict
    assert isinstance(verdict, CouncilVerdict)
    assert verdict.council_id == CouncilId.C1_WORTHINESS
    assert verdict.question == question
    assert verdict.chairman_decision == "qualified"
    assert len(verdict.preserved_dissents) == 2
    assert verdict.total_cost_usd > 0.0
    assert verdict.wall_clock_seconds > 0.0
    assert verdict.provenance_hash != ""

    # Check that session log file was written in session_dir
    session_file = tmp_path / f"{verdict.session_id}.jsonl"
    assert session_file.exists()

    # Read the session file to verify JSONL structure
    with open(session_file, encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) > 0
        # Start and end events
        start_event = json.loads(lines[0])
        assert start_event["event"] == "session_start"
        assert start_event["council_id"] == "C1"

        end_event = json.loads(lines[-1])
        assert end_event["event"] == "session_end"
        assert end_event["total_cost_usd"] > 0.0

    # 4. Run calibrate API
    report = council.calibrate()
    assert isinstance(report, CalibrationReport)
    assert len(report.probe_results) == 10  # there are 10 probes in probes.yaml
    assert report.overall_disagreement_rate >= 0.0
    assert isinstance(report.flagged_sycophancy, bool)
    assert len(report.notes) > 0

    # 5. Exercise CLI execution
    project_root = Path(__file__).resolve().parents[3]

    # Subcommand: show-lineup
    res_lineup = subprocess.run(
        [sys.executable, "-m", "factory.council", "show-lineup"],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(project_root),
    )
    assert "Council Lineup configuration" in res_lineup.stdout
    assert "openai/gpt-5.5" in res_lineup.stdout

    # Subcommand: deliberate
    cli_session_dir = tmp_path / "cli_sessions"
    res_deliberate = subprocess.run(
        [
            sys.executable,
            "-m",
            "factory.council",
            "deliberate",
            "--council-id",
            "C1",
            "--question-fixture",
            "sample_worthiness",
            "--session-dir",
            str(cli_session_dir),
            "--mock-mode",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(project_root),
    )
    assert "=== Council Verdict ===" in res_deliberate.stdout
    assert "Decision:   QUALIFIED" in res_deliberate.stdout
    assert "Total Cost:" in res_deliberate.stdout

    # Find generated session log from CLI
    generated_sessions = list(cli_session_dir.glob("*.jsonl"))
    assert len(generated_sessions) == 1
    cli_session_file = generated_sessions[0]

    # Subcommand: show-session
    res_show_sess = subprocess.run(
        [
            sys.executable,
            "-m",
            "factory.council",
            "show-session",
            "--path",
            str(cli_session_file),
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(project_root),
    )
    assert "SESSION START" in res_show_sess.stdout
    assert "SESSION END" in res_show_sess.stdout

    # Subcommand: calibrate (we'll capture the report file path in runs/_calibration/)
    calibration_runs_dir = project_root / "runs" / "_calibration"
    existing_reports = (
        set(calibration_runs_dir.glob("**/report.json")) if calibration_runs_dir.exists() else set()
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "factory.council",
            "calibrate",
            "--mock-mode",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(project_root),
    )

    new_reports = set(calibration_runs_dir.glob("**/report.json")) - existing_reports
    assert len(new_reports) == 1
    report_file = list(new_reports)[0]

    try:
        # Subcommand: show-report
        res_show_rep = subprocess.run(
            [
                sys.executable,
                "-m",
                "factory.council",
                "show-report",
                "--path",
                str(report_file),
            ],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(project_root),
        )
        assert "=== Calibration Report (" in res_show_rep.stdout
        assert "Overall Disagreement Rate" in res_show_rep.stdout

        # Subcommand: promote-calibration
        active_report_path = project_root / "config" / "council" / "active_report.json"
        backup_path = project_root / "config" / "council" / "active_report_backup.json"
        backup_exists = active_report_path.exists()

        if backup_exists:
            shutil.copy2(active_report_path, backup_path)

        try:
            res_promote = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "factory.council",
                    "promote-calibration",
                    "--path",
                    str(report_file),
                ],
                capture_output=True,
                text=True,
                check=True,
                cwd=str(project_root),
            )
            assert "Successfully promoted calibration report" in res_promote.stdout
            assert active_report_path.exists()
        finally:
            if backup_exists:
                shutil.copy2(backup_path, active_report_path)
                backup_path.unlink()
            elif active_report_path.exists():
                active_report_path.unlink()
    finally:
        # Clean up the generated calibration report folder
        if report_file.exists():
            report_file.unlink()
        parent_dir = report_file.parent
        if parent_dir.exists():
            parent_dir.rmdir()
