"""Public implementation contract for the writer module."""

from __future__ import annotations

from factory.literature import PaperStore, PaperStoreEntry
from factory.module_contracts import ModuleContract
from factory.writer.bibtex import extract_bibtex
from factory.writer.rag_compiler import RunReportDraftRequest, compile_run_report_draft
from factory.writer.related import PaperRecord, RelatedWorkSegment, generate_related_work_segment

MODULE_CONTRACT = ModuleContract(
    module_name="writer",
    spec_id="011",
    responsibility="Assemble evidence-grounded internal reports from claims, runs, and citations.",
    required_inputs=(
        "EvidenceLedgerEntry",
        "RunReportDraft",
    ),
    produced_outputs=("RunReport",),
)


def describe_contract() -> ModuleContract:
    """Return the stable public contract for this module."""
    return MODULE_CONTRACT


__all__ = [
    "MODULE_CONTRACT",
    "PaperRecord",
    "PaperStore",
    "PaperStoreEntry",
    "RelatedWorkSegment",
    "RunReportDraftRequest",
    "compile_run_report_draft",
    "describe_contract",
    "extract_bibtex",
    "generate_related_work_segment",
]
