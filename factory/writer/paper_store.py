"""Paper store indexing primitives for grounded report writing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PaperStoreRecord:
    """Indexed paper text and citation metadata."""

    paper_id: str
    title: str
    source_path: Path
    text_sha256: str
    text: str
    bibtex: str | None = None


class PaperStore:
    """Filesystem-backed paper text index used by the writer pipeline."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, paper_id: str) -> Path:
        """Return the JSON metadata path for one indexed paper."""
        return self._root / f"{paper_id}.json"

    def put(self, record: PaperStoreRecord) -> Path:
        """Persist one indexed paper record as deterministic JSON."""
        self._root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(record.paper_id)
        payload = {
            "paper_id": record.paper_id,
            "title": record.title,
            "source_path": str(record.source_path),
            "text_sha256": record.text_sha256,
            "text": record.text,
            "bibtex": record.bibtex,
        }
        path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        return path

    def get(self, paper_id: str) -> PaperStoreRecord:
        """Load one indexed paper record."""
        payload = json.loads(self.path_for(paper_id).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"paper record {paper_id} must be a JSON object")
        return PaperStoreRecord(
            paper_id=_string_field(payload, "paper_id"),
            title=_string_field(payload, "title"),
            source_path=Path(_string_field(payload, "source_path")),
            text_sha256=_string_field(payload, "text_sha256"),
            text=_string_field(payload, "text"),
            bibtex=_optional_string_field(payload, "bibtex"),
        )


def index_paper_text(
    *,
    paper_id: str,
    title: str,
    source_path: Path,
    text: str,
    bibtex: str | None = None,
) -> PaperStoreRecord:
    """Create an indexed paper record from extracted/OCR text."""
    return PaperStoreRecord(
        paper_id=paper_id,
        title=title,
        source_path=source_path,
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
        bibtex=bibtex,
    )


def _string_field(payload: dict[object, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"paper record field {key} must be a non-empty string")
    return value


def _optional_string_field(payload: dict[object, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"paper record field {key} must be a string when present")
    return value


__all__ = ["PaperStore", "PaperStoreRecord", "index_paper_text"]
