"""Versioned atomic checkpoints for surrogate models."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from factory.surrogate.training import KNearestSurrogateModel

SURROGATE_CHECKPOINT_VERSION: Literal[1] = 1


class SurrogateCheckpoint(BaseModel):
    """Serializable checkpoint envelope for rollback-safe surrogate model storage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    model_id: str
    created_at_utc: str
    parent_checkpoint_sha256: str | None
    model: KNearestSurrogateModel


def save_surrogate_checkpoint(
    model: KNearestSurrogateModel,
    checkpoint_path: Path,
    *,
    model_id: str,
    created_at_utc: str | None = None,
) -> SurrogateCheckpoint:
    """Atomically save a surrogate checkpoint and preserve the previous version for rollback."""
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    parent_hash = _file_sha256(checkpoint_path) if checkpoint_path.exists() else None
    checkpoint = SurrogateCheckpoint(
        version=SURROGATE_CHECKPOINT_VERSION,
        model_id=model_id,
        created_at_utc=created_at_utc or datetime.now(UTC).isoformat(),
        parent_checkpoint_sha256=parent_hash,
        model=model,
    )

    if checkpoint_path.exists():
        _atomic_write_bytes(_rollback_path(checkpoint_path), checkpoint_path.read_bytes())
    _atomic_write_bytes(
        checkpoint_path,
        checkpoint.model_dump_json(indent=2).encode("utf-8"),
    )
    return checkpoint


def load_surrogate_checkpoint(checkpoint_path: Path) -> SurrogateCheckpoint:
    """Load and validate a versioned surrogate checkpoint."""
    return SurrogateCheckpoint.model_validate_json(checkpoint_path.read_bytes())


def rollback_surrogate_checkpoint(checkpoint_path: Path) -> SurrogateCheckpoint:
    """Restore the previous checkpoint snapshot captured by the last save."""
    rollback_path = _rollback_path(checkpoint_path)
    if not rollback_path.exists():
        raise FileNotFoundError(f"rollback checkpoint not found: {rollback_path}")
    _atomic_write_bytes(checkpoint_path, rollback_path.read_bytes())
    return load_surrogate_checkpoint(checkpoint_path)


def _rollback_path(checkpoint_path: Path) -> Path:
    return checkpoint_path.with_name(f"{checkpoint_path.name}.rollback")


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "SURROGATE_CHECKPOINT_VERSION",
    "SurrogateCheckpoint",
    "load_surrogate_checkpoint",
    "rollback_surrogate_checkpoint",
    "save_surrogate_checkpoint",
]
