"""Compile grounded writer segments into unapproved RunReport drafts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from factory.artifacts.api import ArtifactHash, HypothesisId, RunReport
from factory.writer.bibtex import extract_bibtex
from factory.writer.related import PaperRecord, generate_related_work_segment

_ZERO_HASH: ArtifactHash = "0" * 64


@dataclass(frozen=True, slots=True)
class RunReportDraftRequest:
    """Inputs for a grounded RunReport draft; G6 approval is intentionally absent."""

    hypothesis_id: HypothesisId
    title: str
    abstract: str
    topic: str
    paper_records: tuple[PaperRecord, ...]
    figure_paths: tuple[str, ...] = ()
    embedded_council_verdict_hashes: tuple[ArtifactHash, ...] = ()
    parent_hashes: tuple[ArtifactHash, ...] = ()
    created_at: datetime | None = None


def compile_run_report_draft(request: RunReportDraftRequest) -> RunReport:
    """Compile a RunReport draft that cannot carry G6 approval."""
    related_work = generate_related_work_segment(request.paper_records, request.topic)
    bibtex = extract_bibtex(request.paper_records)
    created_at = request.created_at or datetime.now()
    latex_source = "\n\n".join(
        (
            "\\section{Abstract}",
            request.abstract,
            "\\section{Related Work}",
            related_work.text,
        )
    )
    draft = RunReport(
        artifact_type="RunReport",
        created_at=created_at,
        provenance_hash=_ZERO_HASH,
        parent_hashes=request.parent_hashes,
        hypothesis_id=request.hypothesis_id,
        title=request.title,
        abstract=request.abstract,
        latex_source=latex_source,
        figure_paths=request.figure_paths,
        bibtex=bibtex,
        embedded_council_verdict_hashes=request.embedded_council_verdict_hashes,
        g6_approved=False,
        g6_approver=None,
        g6_approved_at=None,
    )
    return draft.model_copy(update={"provenance_hash": draft.compute_hash()})
