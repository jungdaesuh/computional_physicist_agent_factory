"""Filesystem-backed PaperStore owned by the literature module."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import shutil
import tempfile
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from factory.literature.client import OpenAlexAuthor, OpenAlexClientProtocol, OpenAlexWork
from factory.literature.errors import BibtexUnavailable, OpenAlexAPIError, PaperStoreLookupError
from factory.literature.graph_store import OpenAlexGraphStore


class ContentFetcher(Protocol):
    """Boundary for optional OA PDF downloads during paper promotion."""

    def fetch(self, url: str) -> bytes:
        """Return binary content for one URL."""


class UrlContentFetcher:
    """Timeout-bound URL fetcher for optional open-access PDF capture."""

    def __init__(self, timeout_seconds: int = 30, max_bytes: int = 25_000_000) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes

    def fetch(self, url: str) -> bytes:
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                raw_payload = response.read(self._max_bytes + 1)
        except urllib.error.URLError as exc:
            raise OpenAlexAPIError(f"PDF fetch failed: {exc.reason}") from exc
        if not isinstance(raw_payload, bytes):
            raise OpenAlexAPIError("PDF fetch returned non-bytes payload")
        payload = raw_payload
        if len(payload) > self._max_bytes:
            raise OpenAlexAPIError("PDF fetch exceeded maximum byte budget")
        return payload


@dataclass(frozen=True, slots=True)
class PaperStoreEntry:
    """Promoted paper metadata and local text/citation payloads."""

    work_id: str
    title: str
    authors: tuple[OpenAlexAuthor, ...]
    publication_year: int | None
    doi: str | None
    abstract: str
    text: str
    bibtex: str | None
    work_path: Path
    evidence_path: Path
    pdf_path: Path | None


class PaperStore:
    """Persist promoted OpenAlex works for citation-grounded RAG writing."""

    def __init__(
        self,
        root: Path,
        *,
        graph_store: OpenAlexGraphStore | None = None,
        client: OpenAlexClientProtocol | None = None,
        content_fetcher: ContentFetcher | None = None,
    ) -> None:
        self.root = root
        self._graph_store = graph_store
        self._client = client
        self._content_fetcher = content_fetcher

    def query(self, topic: str, limit: int) -> tuple[PaperStoreEntry, ...]:
        if limit < 1 or not self.root.exists():
            return ()
        terms = tuple(term for term in topic.lower().split() if term)
        entries = tuple(
            self.get(path.parent.name) for path in sorted(self.root.glob("*/entry.json"))
        )
        ranked = sorted(
            entries,
            key=lambda entry: (-_text_score(entry, terms), entry.work_id),
        )
        return tuple(entry for entry in ranked if _text_score(entry, terms) > 0)[:limit]

    def get(self, work_id: str) -> PaperStoreEntry:
        entry_path = self._entry_path(work_id)
        if not entry_path.is_file():
            raise PaperStoreLookupError(f"PaperStore entry not found: {work_id}")
        payload: object = json.loads(entry_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise PaperStoreLookupError(f"PaperStore entry must be an object: {work_id}")
        entry = PaperStoreEntry(
            work_id=_string_field(payload, "work_id"),
            title=_string_field(payload, "title"),
            authors=_authors(payload.get("authors")),
            publication_year=_optional_int(payload.get("publication_year")),
            doi=_optional_string(payload.get("doi")),
            abstract=_string_field(payload, "abstract"),
            text=_string_field(payload, "text"),
            bibtex=_optional_string(payload.get("bibtex")),
            work_path=Path(_string_field(payload, "work_path")),
            evidence_path=Path(_string_field(payload, "evidence_path")),
            pdf_path=_optional_path(payload.get("pdf_path")),
        )
        self._verify_entry(entry)
        return entry

    def get_bibtex(self, work_id: str) -> str:
        bibtex = self.get(work_id).bibtex
        if bibtex is None:
            raise BibtexUnavailable(f"BibTeX unavailable for {work_id}")
        return bibtex

    def has_bibtex(self, work_id: str) -> bool:
        return self.get(work_id).bibtex is not None

    def promote(
        self,
        work_ids: Sequence[str],
        *,
        fetch_pdf: bool = False,
    ) -> tuple[PaperStoreEntry, ...]:
        entries: list[PaperStoreEntry] = []
        for work_id in work_ids:
            work = self._load_work(work_id)
            entry = self._write_entry(work, fetch_pdf=fetch_pdf)
            entries.append(entry)
        return tuple(entries)

    @classmethod
    def mock(cls) -> PaperStore:
        store = cls(Path(tempfile.mkdtemp(prefix="factory-paper-store-")))
        work = OpenAlexWork(
            work_id="W-MOCK-1",
            title="Mock QI Stellarator Paper",
            abstract="quasi isodynamic stellarator coil simplicity",
            referenced_work_ids=(),
            related_work_ids=(),
            is_open_access=True,
            doi="10.0000/mock",
            citation_count=10,
            publication_year=2026,
            authors=(OpenAlexAuthor(name="Mock Author"),),
            venue="Mock Journal",
        )
        store._write_entry(work, fetch_pdf=False)
        return store

    def _load_work(self, work_id: str) -> OpenAlexWork:
        if self._graph_store is not None:
            cached = self._graph_store.get_work(work_id)
            if cached is not None:
                return cached
        if self._client is None:
            raise PaperStoreLookupError(f"No OpenAlex work source configured for {work_id}")
        work = self._client.get_work(work_id)
        if self._graph_store is not None:
            self._graph_store.upsert_work(work)
        return work

    def _write_entry(self, work: OpenAlexWork, *, fetch_pdf: bool) -> PaperStoreEntry:
        paper_dir = self._paper_dir(work.work_id)
        safe_work_id = paper_dir.name
        pdf_payload = self._fetch_pdf_payload(work) if fetch_pdf else None
        self.root.mkdir(parents=True, exist_ok=True)
        staging_dir = self.root / f".{safe_work_id}.staging"
        backup_dir = self.root / f".{safe_work_id}.old"
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        staging_dir.mkdir(parents=True)

        work_path = paper_dir / "work.json"
        evidence_path = paper_dir / "evidence.json"
        staging_work_path = staging_dir / "work.json"
        staging_evidence_path = staging_dir / "evidence.json"
        staging_provenance_path = staging_dir / "PROVENANCE.json"
        staging_ocr_path = staging_dir / "ocr.txt"
        staging_bibtex_path = staging_dir / "bibtex.bib"
        staging_pdf_path = staging_dir / "pdf.pdf"
        if pdf_payload is not None:
            staging_pdf_path.write_bytes(pdf_payload)
        pdf_path = paper_dir / "pdf.pdf" if pdf_payload is not None else None
        text = work.abstract or work.title
        bibtex = synthesize_bibtex(work)
        work_json = json.dumps(work.to_json_object(), sort_keys=True, indent=2) + "\n"
        work_sha256 = hashlib.sha256(work_json.encode("utf-8")).hexdigest()

        staging_work_path.write_text(work_json, encoding="utf-8")
        staging_ocr_path.write_text(text + "\n", encoding="utf-8")
        staging_evidence_path.write_text(
            json.dumps({"work_id": work.work_id, "evidence": []}, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        staging_provenance_path.write_text(
            json.dumps(
                {
                    "provider": "openalex",
                    "work_id": work.work_id,
                    "promoted_at": datetime.datetime.now(datetime.UTC).isoformat(),
                    "work_sha256": work_sha256,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if bibtex is not None:
            staging_bibtex_path.write_text(bibtex + "\n", encoding="utf-8")

        entry = PaperStoreEntry(
            work_id=work.work_id,
            title=work.title,
            authors=work.authors,
            publication_year=work.publication_year,
            doi=work.doi,
            abstract=work.abstract,
            text=text,
            bibtex=bibtex,
            work_path=work_path,
            evidence_path=evidence_path,
            pdf_path=pdf_path,
        )
        entry_payload = {
            "work_id": entry.work_id,
            "title": entry.title,
            "authors": [
                {"name": author.name, "openalex_id": author.openalex_id, "orcid": author.orcid}
                for author in entry.authors
            ],
            "publication_year": entry.publication_year,
            "doi": entry.doi,
            "abstract": entry.abstract,
            "text": entry.text,
            "bibtex": entry.bibtex,
            "work_path": str(entry.work_path),
            "evidence_path": str(entry.evidence_path),
            "pdf_path": str(entry.pdf_path) if entry.pdf_path is not None else None,
        }
        (staging_dir / "entry.json").write_text(
            json.dumps(entry_payload, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        if paper_dir.exists():
            paper_dir.replace(backup_dir)
        staging_dir.replace(paper_dir)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        return entry

    def _fetch_pdf_payload(self, work: OpenAlexWork) -> bytes | None:
        if work.pdf_url is None:
            return None
        if self._content_fetcher is None:
            raise OpenAlexAPIError(
                f"PDF fetch requested for {work.work_id}, but no content fetcher is configured"
            )
        return self._content_fetcher.fetch(work.pdf_url)

    def _entry_path(self, work_id: str) -> Path:
        return self._paper_dir(work_id) / "entry.json"

    def _paper_dir(self, work_id: str) -> Path:
        return self.root / _safe_work_id(work_id)

    def _verify_entry(self, entry: PaperStoreEntry) -> None:
        paper_dir = self._paper_dir(entry.work_id)
        expected_work_path = paper_dir / "work.json"
        expected_evidence_path = paper_dir / "evidence.json"
        expected_pdf_path = paper_dir / "pdf.pdf"
        if entry.work_path != expected_work_path or entry.evidence_path != expected_evidence_path:
            raise PaperStoreLookupError(f"PaperStore entry path mismatch: {entry.work_id}")
        if entry.pdf_path is not None and entry.pdf_path != expected_pdf_path:
            raise PaperStoreLookupError(f"PaperStore PDF path mismatch: {entry.work_id}")
        for required_path in (
            expected_work_path,
            expected_evidence_path,
            paper_dir / "ocr.txt",
            paper_dir / "PROVENANCE.json",
        ):
            if not required_path.is_file():
                raise PaperStoreLookupError(f"PaperStore file missing: {required_path}")

        work_json = expected_work_path.read_text(encoding="utf-8")
        work_payload = _read_json_object(expected_work_path)
        if work_payload.get("work_id") != entry.work_id:
            raise PaperStoreLookupError(f"PaperStore work ID mismatch: {entry.work_id}")
        provenance = _read_json_object(paper_dir / "PROVENANCE.json")
        expected_hash = hashlib.sha256(work_json.encode("utf-8")).hexdigest()
        if provenance.get("provider") != "openalex" or provenance.get("work_id") != entry.work_id:
            raise PaperStoreLookupError(f"PaperStore provenance mismatch: {entry.work_id}")
        if provenance.get("work_sha256") != expected_hash:
            raise PaperStoreLookupError(f"PaperStore work hash mismatch: {entry.work_id}")

        bibtex_path = paper_dir / "bibtex.bib"
        if entry.bibtex is None:
            if bibtex_path.exists():
                raise PaperStoreLookupError(f"PaperStore stale BibTeX file: {entry.work_id}")
        elif (
            not bibtex_path.is_file()
            or bibtex_path.read_text(encoding="utf-8").strip() != entry.bibtex
        ):
            raise PaperStoreLookupError(f"PaperStore BibTeX mismatch: {entry.work_id}")
        if entry.pdf_path is None:
            if expected_pdf_path.exists():
                raise PaperStoreLookupError(f"PaperStore stale PDF file: {entry.work_id}")
        elif not expected_pdf_path.is_file():
            raise PaperStoreLookupError(f"PaperStore PDF missing: {entry.work_id}")


def synthesize_bibtex(work: OpenAlexWork) -> str | None:
    if not work.title or not work.authors or work.publication_year is None:
        return None
    first_author = work.authors[0].name.split()[-1].lower()
    key = re.sub(r"[^a-z0-9]+", "", f"{first_author}{work.publication_year}{work.work_id}".lower())
    author_value = " and ".join(author.name for author in work.authors)
    fields = [
        f"  title = {{{work.title}}}",
        f"  author = {{{author_value}}}",
        f"  year = {{{work.publication_year}}}",
    ]
    if work.venue is not None:
        fields.append(f"  journal = {{{work.venue}}}")
    if work.doi is not None:
        fields.append(f"  doi = {{{work.doi}}}")
    return "@article{" + key + ",\n" + ",\n".join(fields) + "\n}"


def _safe_work_id(work_id: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", work_id) is None:
        raise PaperStoreLookupError(f"Unsafe OpenAlex work ID for PaperStore path: {work_id}")
    return work_id


def _read_json_object(path: Path) -> dict[str, object]:
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PaperStoreLookupError(f"PaperStore JSON file must contain an object: {path}")
    return payload


def _text_score(entry: PaperStoreEntry, terms: tuple[str, ...]) -> int:
    haystack = f"{entry.title} {entry.abstract} {entry.text}".lower()
    return sum(term in haystack for term in terms)


def _string_field(payload: dict[object, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or value == "":
        raise PaperStoreLookupError(f"PaperStore field {key} must be a non-empty string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PaperStoreLookupError("PaperStore optional field must be a string")
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise PaperStoreLookupError("PaperStore optional field must be an integer")
    return value


def _optional_path(value: object) -> Path | None:
    text = _optional_string(value)
    return Path(text) if text is not None else None


def _authors(value: object) -> tuple[OpenAlexAuthor, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise PaperStoreLookupError("PaperStore authors must be a list")
    authors: list[OpenAlexAuthor] = []
    for item in value:
        if not isinstance(item, dict):
            raise PaperStoreLookupError("PaperStore author must be an object")
        authors.append(
            OpenAlexAuthor(
                name=_string_field(item, "name"),
                openalex_id=_optional_string(item.get("openalex_id")),
                orcid=_optional_string(item.get("orcid")),
            )
        )
    return tuple(authors)


__all__ = [
    "ContentFetcher",
    "PaperStore",
    "PaperStoreEntry",
    "UrlContentFetcher",
    "synthesize_bibtex",
]
