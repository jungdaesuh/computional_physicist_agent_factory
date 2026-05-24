"""Unit tests for Phase B writer surfaces."""

from __future__ import annotations

import pytest

from factory.artifacts.api import HypothesisId
from factory.writer.api import (
    PaperRecord,
    RunReportDraftRequest,
    compile_run_report_draft,
    extract_bibtex,
    generate_related_work_segment,
)
from factory.writer.errors import WriterError


def _paper(
    paper_id: str,
    *,
    doi: str | None = "10.1000/example",
    citation_key: str | None = "smith2026",
    local_path: str | None = "/papers/smith2026.pdf",
) -> PaperRecord:
    return PaperRecord(
        paper_id=paper_id,
        title="Local Method Study",
        abstract="A local archived paper.",
        authors=("Smith", "Ng"),
        year=2026,
        doi=doi,
        citation_key=citation_key,
        local_path=local_path,
    )


def test_related_work_uses_only_local_paper_records() -> None:
    segment = generate_related_work_segment(
        (_paper("local"), _paper("remote", local_path=None)),
        "surrogate validation",
    )

    assert segment.source_paper_ids == ("local",)
    assert "\\cite{smith2026}" in segment.text


def test_bibtex_rejects_missing_doi_or_citation_key() -> None:
    with pytest.raises(WriterError, match="missing DOI"):
        extract_bibtex((_paper("missing-doi", doi=None),))

    with pytest.raises(WriterError, match="missing citation key"):
        extract_bibtex((_paper("missing-key", citation_key=None),))


def test_rag_compiler_produces_unapproved_run_report_draft() -> None:
    report = compile_run_report_draft(
        RunReportDraftRequest(
            hypothesis_id=HypothesisId("hyp-1"),
            title="Draft",
            abstract="Draft abstract.",
            topic="surrogate validation",
            paper_records=(_paper("local"),),
        )
    )

    assert report.g6_approved is False
    assert report.g6_approver is None
    assert report.g6_approved_at is None
    assert "\\section{Related Work}" in report.latex_source
    report.verify_self()
