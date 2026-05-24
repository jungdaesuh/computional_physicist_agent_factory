"""Manifest proposal extraction for simulator catalog onboarding."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class DependencyProposal:
    """Dependency signal extracted from repository metadata."""

    name: str
    source_file: str
    version_specifier: str | None = None


@dataclass(frozen=True)
class ManifestProposal:
    """Draft manifest fields inferred from repository files before human approval."""

    simulator_id: str
    display_name: str
    domain: str
    repo_root: Path
    dockerfile_path: str | None
    license_path: str | None
    dependency_files: tuple[str, ...]
    dependencies: tuple[DependencyProposal, ...]
    computed_observables: tuple[str, ...]
    proposal_hash: str


_KNOWN_DEPENDENCY_FILES = (
    "pyproject.toml",
    "requirements.txt",
    "requirements.in",
    "environment.yml",
    "environment.yaml",
)


def propose_manifest_from_repo(
    repo_root: Path,
    simulator_id: str,
    domain: str,
    computed_observables: Sequence[str],
) -> ManifestProposal:
    """Infer a manifest proposal from common repository files.

    This is a proposal generator only: it never approves onboarding or invents
    license/build facts that must be verified by the dedicated Phase B gates.
    """

    root = Path(repo_root)
    dockerfile_path = _relative_file(root, ("Dockerfile", "Containerfile"))
    license_path = _relative_file(root, ("LICENSE", "LICENSE.md", "COPYING", "COPYING.md"))
    dependency_files = tuple(
        rel_path for rel_path in _KNOWN_DEPENDENCY_FILES if (root / rel_path).is_file()
    )
    dependencies = tuple(
        dependency
        for rel_path in dependency_files
        for dependency in _extract_dependencies(root / rel_path, rel_path)
    )
    observables = tuple(computed_observables)
    display_name = simulator_id.replace("-", " ").replace("_", " ").title()

    hash_payload = "|".join(
        (
            simulator_id,
            domain,
            dockerfile_path or "",
            license_path or "",
            ",".join(dependency_files),
            ",".join(f"{dep.name}:{dep.version_specifier or ''}" for dep in dependencies),
            ",".join(observables),
        )
    )
    proposal_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()

    return ManifestProposal(
        simulator_id=simulator_id,
        display_name=display_name,
        domain=domain,
        repo_root=root,
        dockerfile_path=dockerfile_path,
        license_path=license_path,
        dependency_files=dependency_files,
        dependencies=dependencies,
        computed_observables=observables,
        proposal_hash=proposal_hash,
    )


def _relative_file(root: Path, names: tuple[str, ...]) -> str | None:
    for name in names:
        if (root / name).is_file():
            return name
    return None


def _extract_dependencies(path: Path, rel_path: str) -> tuple[DependencyProposal, ...]:
    if rel_path in {"requirements.txt", "requirements.in"}:
        return _extract_requirements_dependencies(path, rel_path)
    if rel_path in {"environment.yml", "environment.yaml"}:
        return _extract_environment_dependencies(path, rel_path)
    if rel_path == "pyproject.toml":
        return _extract_pyproject_dependency_names(path, rel_path)
    return ()


def _extract_requirements_dependencies(path: Path, rel_path: str) -> tuple[DependencyProposal, ...]:
    dependencies: list[DependencyProposal] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped or stripped.startswith(("-", "http://", "https://")):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)\s*(.*)$", stripped)
        if match is not None:
            specifier = match.group(2).strip() or None
            dependencies.append(
                DependencyProposal(
                    name=match.group(1),
                    version_specifier=specifier,
                    source_file=rel_path,
                )
            )
    return tuple(dependencies)


def _extract_environment_dependencies(path: Path, rel_path: str) -> tuple[DependencyProposal, ...]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return ()
    raw_dependencies = raw.get("dependencies")
    if not isinstance(raw_dependencies, list):
        return ()

    dependencies: list[DependencyProposal] = []
    for item in raw_dependencies:
        if isinstance(item, str):
            name, specifier = _split_conda_dependency(item)
            dependencies.append(
                DependencyProposal(name=name, version_specifier=specifier, source_file=rel_path)
            )
    return tuple(dependencies)


def _extract_pyproject_dependency_names(
    path: Path, rel_path: str
) -> tuple[DependencyProposal, ...]:
    text = path.read_text(encoding="utf-8")
    dependencies: list[DependencyProposal] = []
    in_dependencies = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "dependencies = [":
            in_dependencies = True
            continue
        if in_dependencies and stripped == "]":
            break
        if in_dependencies:
            cleaned = stripped.rstrip(",").strip("\"'")
            if cleaned:
                name, specifier = _split_python_dependency(cleaned)
                dependencies.append(
                    DependencyProposal(name=name, version_specifier=specifier, source_file=rel_path)
                )
    return tuple(dependencies)


def _split_python_dependency(raw: str) -> tuple[str, str | None]:
    match = re.match(r"^([A-Za-z0-9_.-]+)\s*(.*)$", raw)
    if match is None:
        return raw, None
    specifier = match.group(2).strip() or None
    return match.group(1), specifier


def _split_conda_dependency(raw: str) -> tuple[str, str | None]:
    parts = raw.split("=", 1)
    if len(parts) == 1:
        return raw, None
    return parts[0], f"={parts[1]}"
