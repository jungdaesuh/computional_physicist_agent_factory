"""BibTeX extraction from complete local citation records."""

from __future__ import annotations

from factory.writer.errors import WriterError
from factory.writer.related import PaperRecord


def extract_bibtex(records: tuple[PaperRecord, ...]) -> str:
    """Return deterministic BibTeX, rejecting records without DOI or citation key."""
    entries: list[str] = []
    for record in sorted(records, key=lambda item: item.citation_key or item.paper_id):
        if record.doi is None or record.doi.strip() == "":
            raise WriterError(f"BibTeX record missing DOI: {record.paper_id}")
        if record.citation_key is None or record.citation_key.strip() == "":
            raise WriterError(f"BibTeX record missing citation key: {record.paper_id}")
        authors = " and ".join(record.authors) if record.authors else "Unknown"
        entries.append(
            "\n".join(
                (
                    f"@article{{{record.citation_key},",
                    f"  title = {{{record.title}}},",
                    f"  author = {{{authors}}},",
                    f"  year = {{{record.year}}},",
                    f"  doi = {{{record.doi}}}",
                    "}",
                )
            )
        )
    return "\n\n".join(entries)
