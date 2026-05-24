"""Staged validation and atomic promotion for generated candidates."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ValidationStage:
    """One deterministic validation stage required before promotion."""

    name: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class StageResult:
    """Observed result for one validation stage."""

    stage_name: str
    passed: bool
    output: str


@dataclass(frozen=True)
class PromotionCandidate:
    """Generated artifact waiting in a staging path."""

    staging_path: Path
    destination_path: Path
    validation_stages: tuple[ValidationStage, ...]


@dataclass(frozen=True)
class PromotionResult:
    """Result of staged validation and optional atomic promotion."""

    promoted: bool
    destination_path: Path
    stage_results: tuple[StageResult, ...]


StageRunner = Callable[[ValidationStage, Path], StageResult]


def validate_candidate(
    candidate: PromotionCandidate,
    run_stage: StageRunner,
) -> tuple[StageResult, ...]:
    """Run candidate validation stages in order and stop at the first failure."""
    results: list[StageResult] = []
    for stage in candidate.validation_stages:
        result = run_stage(stage, candidate.staging_path)
        results.append(result)
        if not result.passed:
            break
    return tuple(results)


def promote_candidate(candidate: PromotionCandidate, run_stage: StageRunner) -> PromotionResult:
    """Promote a candidate only after every validation stage passes."""
    stage_results = validate_candidate(candidate, run_stage)
    if not _all_stages_passed(candidate.validation_stages, stage_results):
        return PromotionResult(False, candidate.destination_path, stage_results)

    candidate.destination_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=candidate.destination_path.parent,
        prefix=f".{candidate.destination_path.name}.",
    ) as temp_dir:
        temp_path = Path(temp_dir) / candidate.destination_path.name
        temp_path.write_bytes(candidate.staging_path.read_bytes())
        os.replace(temp_path, candidate.destination_path)

    return PromotionResult(True, candidate.destination_path, stage_results)


def _all_stages_passed(
    stages: Sequence[ValidationStage],
    results: Sequence[StageResult],
) -> bool:
    if len(stages) != len(results):
        return False
    return all(result.passed for result in results)


__all__ = [
    "PromotionCandidate",
    "PromotionResult",
    "StageResult",
    "StageRunner",
    "ValidationStage",
    "promote_candidate",
    "validate_candidate",
]
