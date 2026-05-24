"""Related-work segment generation grounded in local paper records."""

from __future__ import annotations

from dataclasses import dataclass

from factory.writer.errors import WriterError


@dataclass(frozen=True, slots=True)
class PaperRecord:
    """Local paper metadata record used as the only source for writer output."""

    paper_id: str
    title: str
    abstract: str
    authors: tuple[str, ...]
    year: int
    doi: str | None
    citation_key: str | None
    local_path: str | None


@dataclass(frozen=True, slots=True)
class RelatedWorkSegment:
    """Generated prose plus the exact local citation keys it depends on."""

    text: str
    citation_keys: tuple[str, ...]
    source_paper_ids: tuple[str, ...]


def generate_related_work_segment(
    records: tuple[PaperRecord, ...],
    topic: str,
    *,
    max_records: int = 4,
) -> RelatedWorkSegment:
    """Create a related-work segment from local records only."""
    local_records = tuple(record for record in records if record.local_path is not None)
    if not local_records:
        raise WriterError("Related work generation requires at least one local paper record.")

    selected = local_records[:max_records]
    missing_keys = tuple(record.paper_id for record in selected if record.citation_key is None)
    if missing_keys:
        joined = ", ".join(missing_keys)
        raise WriterError(f"Related work records missing citation keys: {joined}")

    sentences = [
        f"Local literature around {topic} is grounded in {len(selected)} archived records."
    ]
    citation_keys: list[str] = []
    for record in selected:
        citation_key = record.citation_key
        if citation_key is None:
            raise WriterError(f"Paper record missing citation key: {record.paper_id}")
        citation_keys.append(citation_key)
        authors = ", ".join(record.authors) if record.authors else "Unknown authors"
        sentences.append(
            f"{record.title} ({authors}, {record.year}) contributes local evidence "
            f"for this direction \\cite{{{citation_key}}}."
        )

    return RelatedWorkSegment(
        text=" ".join(sentences),
        citation_keys=tuple(citation_keys),
        source_paper_ids=tuple(record.paper_id for record in selected),
    )
