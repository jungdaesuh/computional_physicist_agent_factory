"""Content-addressed artifact byte storage."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from factory.artifacts.core import ArtifactHash, ArtifactHashStr


@dataclass(frozen=True)
class DedupStoreEntry:
    """Resolved store entry for a SHA-256 addressed blob."""

    sha256: ArtifactHash
    path: Path
    size_bytes: int
    existed: bool


def sha256_bytes(content: bytes) -> ArtifactHash:
    """Return the deterministic SHA-256 digest for raw artifact bytes."""
    return hashlib.sha256(content).hexdigest()


class ContentAddressedStore:
    """Global dedup store with one immutable file per SHA-256 digest."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, sha256: ArtifactHash) -> Path:
        digest = ArtifactHashStr(sha256)
        return self._root / digest

    def lookup(self, sha256: ArtifactHash) -> Path | None:
        path = self.path_for(sha256)
        if path.exists():
            return path
        return None

    def manifest(self) -> dict[ArtifactHash, Path]:
        if not self._root.exists():
            return {}
        return {
            ArtifactHashStr(path.name): path
            for path in sorted(self._root.iterdir())
            if path.is_file() and ArtifactHashStr._PATTERN.match(path.name)
        }

    def put_bytes(self, content: bytes) -> DedupStoreEntry:
        digest = sha256_bytes(content)
        existing_path = self.lookup(digest)
        if existing_path is not None:
            return DedupStoreEntry(
                sha256=digest,
                path=existing_path,
                size_bytes=existing_path.stat().st_size,
                existed=True,
            )

        self._root.mkdir(parents=True, exist_ok=True)
        final_path = self.path_for(digest)
        with tempfile.TemporaryDirectory(dir=self._root, prefix=f".{digest}.") as temp_dir:
            temp_path = Path(temp_dir) / "blob"
            with temp_path.open("xb") as temp_file:
                temp_file.write(content)
                temp_file.flush()
                os.fsync(temp_file.fileno())

            existed = False
            try:
                os.link(temp_path, final_path)
            except FileExistsError:
                existed = True

        return DedupStoreEntry(
            sha256=digest,
            path=final_path,
            size_bytes=final_path.stat().st_size,
            existed=existed,
        )

    def put_path(self, source_path: Path) -> DedupStoreEntry:
        return self.put_bytes(source_path.read_bytes())
