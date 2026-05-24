"""Container build verification and runtime abstraction for catalog onboarding."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import yaml
from pydantic import ValidationError

from factory.catalog.api import ImageSha, SimulatorManifest
from factory.catalog.errors import ContainerBuildFailed, ManifestValidationError

RuntimeKind = Literal["docker", "apptainer", "mock"]


@dataclass(frozen=True)
class VerifiedBuildRecipe:
    """Container recipe with Dockerfile integrity checks already applied."""

    manifest_path: Path
    context_path: Path
    dockerfile_path: Path
    manifest_hash: str
    install_steps_hash: str
    runtime_kind: RuntimeKind


@dataclass(frozen=True)
class BuildRequest:
    """Typed request passed to a concrete container runtime."""

    recipe: VerifiedBuildRecipe
    attempt_id: str | None


@dataclass(frozen=True)
class BuildResult:
    """Result returned by a concrete container runtime."""

    image_sha: ImageSha
    build_log_path: Path | None = None


@dataclass(frozen=True)
class BuildCommand:
    """Concrete build command plan passed to an explicit command runner."""

    executable: str
    arguments: tuple[str, ...]


class BuildCommandRunner(Protocol):
    """Boundary for live command execution owned by infrastructure code."""

    def run_build(self, command: BuildCommand) -> BuildResult:
        """Execute an already planned container build command."""
        ...


class ContainerRuntime(Protocol):
    """Explicit interface for live or mock container builds."""

    kind: RuntimeKind

    def build_image(self, request: BuildRequest) -> BuildResult:
        """Build an image for a verified recipe and return the immutable image SHA."""
        ...


class MockContainerRuntime:
    """Deterministic build runtime for tests and dry-run onboarding."""

    kind: RuntimeKind = "mock"

    def build_image(self, request: BuildRequest) -> BuildResult:
        combined = (
            request.recipe.manifest_hash
            + request.recipe.install_steps_hash
            + request.recipe.runtime_kind
        ).encode("utf-8")
        return BuildResult(image_sha=ImageSha(f"sha256:{hashlib.sha256(combined).hexdigest()}"))


@dataclass(frozen=True)
class DockerContainerRuntime:
    """Docker build runtime adapter backed by an explicit command runner."""

    runner: BuildCommandRunner
    executable: str = "docker"
    kind: RuntimeKind = "docker"

    def build_image(self, request: BuildRequest) -> BuildResult:
        command = BuildCommand(
            executable=self.executable,
            arguments=(
                "buildx",
                "build",
                "--file",
                str(request.recipe.dockerfile_path),
                str(request.recipe.context_path),
            ),
        )
        return self.runner.run_build(command)


@dataclass(frozen=True)
class ApptainerContainerRuntime:
    """Apptainer build runtime adapter backed by an explicit command runner."""

    runner: BuildCommandRunner
    executable: str = "apptainer"
    kind: RuntimeKind = "apptainer"

    def build_image(self, request: BuildRequest) -> BuildResult:
        image_path = request.recipe.context_path / "image.sif"
        command = BuildCommand(
            executable=self.executable,
            arguments=(
                "build",
                str(image_path),
                str(request.recipe.dockerfile_path),
            ),
        )
        return self.runner.run_build(command)


class BuildManager:
    """Verifies catalog build recipes and delegates execution to a typed runtime."""

    def __init__(self, runtime: ContainerRuntime) -> None:
        self.runtime = runtime

    def build(self, manifest_path: Path, attempt_id: str | None = None) -> BuildResult:
        recipe = verify_build_recipe(manifest_path, self.runtime.kind)
        return self.runtime.build_image(BuildRequest(recipe=recipe, attempt_id=attempt_id))


def verify_build_recipe(manifest_path: Path, runtime_kind: RuntimeKind) -> VerifiedBuildRecipe:
    """Validate manifest container metadata against the repository Dockerfile."""

    path = Path(manifest_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ManifestValidationError(f"Manifest must be a YAML object: {path}")
    if "manifest_hash" not in raw:
        raw["manifest_hash"] = "temp"

    try:
        manifest = SimulatorManifest(**raw)
    except ValidationError as exc:
        raise ManifestValidationError(f"Manifest validation failed: {exc}") from exc

    dockerfile_path = path.parent / manifest.container_recipe.dockerfile_path
    if not dockerfile_path.is_file():
        raise ContainerBuildFailed(f"Dockerfile not found: {dockerfile_path}")

    install_steps_hash = compute_dockerfile_run_hash(dockerfile_path)
    expected_hash = manifest.container_recipe.install_steps_hash
    if install_steps_hash != expected_hash:
        raise ContainerBuildFailed(
            "Integrity check failed: install_steps_hash mismatch. "
            f"Expected {expected_hash}, got {install_steps_hash}"
        )

    return VerifiedBuildRecipe(
        manifest_path=path,
        context_path=path.parent,
        dockerfile_path=dockerfile_path,
        manifest_hash=manifest.manifest_hash,
        install_steps_hash=install_steps_hash,
        runtime_kind=runtime_kind,
    )


def compute_dockerfile_run_hash(dockerfile_path: Path) -> str:
    """Hash normalized Dockerfile RUN instructions for manifest integrity checks."""

    run_lines = []
    for line in Path(dockerfile_path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("RUN "):
            run_lines.append(" ".join(stripped.split()))
    return hashlib.sha256(" ".join(run_lines).encode("utf-8")).hexdigest()
