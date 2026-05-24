"""Smoke-test baseline comparison for cataloged simulator images."""

from __future__ import annotations

import datetime
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from factory.catalog.api import ImageSha, SmokeTestRecord

JsonScalar = str | int | float | bool | None
JsonObject = Mapping[str, JsonScalar]


@dataclass(frozen=True)
class SmokeExecutionRequest:
    """Input passed to a runtime capable of executing one smoke target."""

    image_sha: ImageSha
    smoke_test_target: str


@dataclass(frozen=True)
class SmokeExecutionResult:
    """Raw smoke-test output returned by the runtime."""

    output: JsonObject
    runtime_seconds: float


@dataclass(frozen=True)
class SmokeBaseline:
    """Reference-output contract for one smoke-test comparison."""

    reference_path: Path
    residual_tolerance: float


class SmokeRuntime(Protocol):
    """Explicit interface for executing a smoke target in a built image."""

    def run_smoke(self, request: SmokeExecutionRequest) -> SmokeExecutionResult:
        """Execute the smoke target and return parsed output."""
        ...


class StaticSmokeRuntime:
    """Deterministic smoke runtime for tests."""

    def __init__(self, output: JsonObject, runtime_seconds: float = 0.5) -> None:
        self.output = output
        self.runtime_seconds = runtime_seconds

    def run_smoke(self, request: SmokeExecutionRequest) -> SmokeExecutionResult:
        del request
        return SmokeExecutionResult(output=self.output, runtime_seconds=self.runtime_seconds)


def run_smoke_against_baseline(
    runtime: SmokeRuntime,
    image_sha: ImageSha,
    smoke_test_target: str,
    baseline: SmokeBaseline,
    actual_output_path: Path,
    diff_path: Path,
) -> SmokeTestRecord:
    """Run a smoke test and compare numeric output against the reference JSON."""

    execution = runtime.run_smoke(
        SmokeExecutionRequest(image_sha=image_sha, smoke_test_target=smoke_test_target)
    )
    reference_output = _read_json_object(baseline.reference_path)
    comparison = compare_smoke_outputs(
        reference=reference_output,
        actual=execution.output,
        residual_tolerance=baseline.residual_tolerance,
    )

    actual_output_path.parent.mkdir(parents=True, exist_ok=True)
    actual_output_path.write_text(
        json.dumps(dict(execution.output), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    written_diff_path: str | None = None
    if not comparison.passed:
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(
            json.dumps(comparison.differences, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        written_diff_path = str(diff_path)

    return SmokeTestRecord(
        ran_at=datetime.datetime.now(datetime.UTC),
        image_sha=image_sha,
        reference_path=str(baseline.reference_path),
        actual_output_path=str(actual_output_path),
        diff_path=written_diff_path,
        max_field_residual=comparison.max_residual,
        passed=comparison.passed,
        runtime_seconds=execution.runtime_seconds,
    )


@dataclass(frozen=True)
class SmokeComparison:
    """Baseline diff summary for one smoke-test run."""

    passed: bool
    max_residual: float
    differences: dict[str, float | str]


def compare_smoke_outputs(
    reference: JsonObject,
    actual: JsonObject,
    residual_tolerance: float,
) -> SmokeComparison:
    """Compare scalar JSON outputs and fail on missing keys or numeric drift."""

    differences: dict[str, float | str] = {}
    max_residual = 0.0
    for key, reference_value in reference.items():
        if key not in actual:
            differences[key] = "missing"
            continue
        actual_value = actual[key]
        if isinstance(reference_value, (int, float)) and isinstance(actual_value, (int, float)):
            residual = abs(float(actual_value) - float(reference_value))
            max_residual = max(max_residual, residual)
            if residual > residual_tolerance:
                differences[key] = residual
        elif actual_value != reference_value:
            differences[key] = "mismatch"

    extra_keys = sorted(key for key in actual if key not in reference)
    for key in extra_keys:
        differences[key] = "extra"

    return SmokeComparison(
        passed=not differences,
        max_residual=max_residual,
        differences=differences,
    )


def _read_json_object(path: Path) -> JsonObject:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Smoke baseline must be a JSON object: {path}")
    output: dict[str, JsonScalar] = {}
    for key, value in raw.items():
        if isinstance(key, str) and _is_json_scalar(value):
            output[key] = value
        else:
            raise ValueError(f"Smoke baseline contains non-scalar field: {key}")
    return output


def _is_json_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))
