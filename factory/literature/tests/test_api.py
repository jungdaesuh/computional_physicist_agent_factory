"""Unit tests for Phase B literature surfaces."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from factory.artifacts.api import GapType
from factory.literature.api import (
    InMemoryOpenAlexClient,
    OpenAlexAuthor,
    OpenAlexGraphStore,
    OpenAlexWork,
    PaperStore,
    TraversalPolicy,
    mine_gap_candidates,
    traverse_openalex,
)
from factory.literature.errors import (
    BibtexUnavailable,
    GapMinerProducedNoCandidates,
    OpenAlexAPIError,
    PaperStoreLookupError,
    TraversalBudgetExhausted,
)


class MutableOpenAlexClient:
    def __init__(self, work: OpenAlexWork) -> None:
        self.work = work

    def get_work(self, work_id: str) -> OpenAlexWork:
        if work_id != self.work.work_id:
            raise OpenAlexAPIError(f"missing work {work_id}")
        return self.work

    def search_works(
        self,
        query: str,
        filters: Mapping[str, str | int | bool] | None = None,
        *,
        limit: int,
    ) -> tuple[OpenAlexWork, ...]:
        _ = (query, filters)
        return (self.work,)[:limit]

    def get_backward_references(self, work_id: str) -> tuple[str, ...]:
        return self.get_work(work_id).referenced_work_ids

    def get_forward_citations(
        self,
        work_id: str,
        *,
        limit: int,
        max_pages: int,
    ) -> tuple[str, ...]:
        _ = (work_id, limit, max_pages)
        return ()

    def batch_get_works(self, work_ids: Sequence[str]) -> tuple[OpenAlexWork, ...]:
        return tuple(self.get_work(work_id) for work_id in work_ids)


class ExplodingOpenAlexClient:
    def get_work(self, work_id: str) -> OpenAlexWork:
        raise AssertionError(f"live get_work should not run for cached {work_id}")

    def search_works(
        self,
        query: str,
        filters: Mapping[str, str | int | bool] | None = None,
        *,
        limit: int,
    ) -> tuple[OpenAlexWork, ...]:
        raise AssertionError(f"live search should not run: {query} {filters} {limit}")

    def get_backward_references(self, work_id: str) -> tuple[str, ...]:
        raise AssertionError(f"live backward references should not run for {work_id}")

    def get_forward_citations(
        self,
        work_id: str,
        *,
        limit: int,
        max_pages: int,
    ) -> tuple[str, ...]:
        raise AssertionError(
            f"live forward citations should not run for {work_id} {limit} {max_pages}"
        )

    def batch_get_works(self, work_ids: Sequence[str]) -> tuple[OpenAlexWork, ...]:
        raise AssertionError(f"live batch fetch should not run for {work_ids}")


class PdfFetcher:
    def fetch(self, url: str) -> bytes:
        return f"pdf:{url}".encode()


class FailingPdfFetcher:
    def fetch(self, url: str) -> bytes:
        raise OpenAlexAPIError(f"pdf failed: {url}")


def test_openalex_traversal_respects_depth_branch_and_open_access() -> None:
    works = {
        "root": OpenAlexWork(
            work_id="root",
            title="Root",
            abstract="root",
            referenced_work_ids=("oa-child", "closed-child"),
            related_work_ids=("extra-child",),
            is_open_access=True,
            doi="10/root",
            citation_count=5,
            publication_year=2026,
            authors=(OpenAlexAuthor(name="Root Author"),),
        ),
        "oa-child": OpenAlexWork(
            work_id="oa-child",
            title="OA",
            abstract="open",
            referenced_work_ids=("grandchild",),
            related_work_ids=(),
            is_open_access=True,
            doi="10/oa",
            citation_count=2,
        ),
        "closed-child": OpenAlexWork(
            work_id="closed-child",
            title="Closed",
            abstract="closed",
            referenced_work_ids=(),
            related_work_ids=(),
            is_open_access=False,
            doi=None,
            citation_count=1,
        ),
        "extra-child": OpenAlexWork(
            work_id="extra-child",
            title="Extra",
            abstract="extra",
            referenced_work_ids=(),
            related_work_ids=(),
            is_open_access=True,
            doi="10/extra",
            citation_count=1,
        ),
        "grandchild": OpenAlexWork(
            work_id="grandchild",
            title="Grand",
            abstract="grand",
            referenced_work_ids=(),
            related_work_ids=(),
            is_open_access=True,
            doi="10/grand",
            citation_count=1,
        ),
    }

    traversed = asyncio.run(
        traverse_openalex(
            ("root",),
            InMemoryOpenAlexClient(works),
            TraversalPolicy(max_depth=1, branch_factor=2, require_open_access=True),
        )
    )

    assert tuple(work.work_id for work in traversed) == ("root", "oa-child")


def test_openalex_traversal_uses_cached_edges_without_live_client(tmp_path: Path) -> None:
    works = {
        "root": OpenAlexWork(
            work_id="root",
            title="Root",
            abstract="root",
            referenced_work_ids=(),
            related_work_ids=(),
            is_open_access=True,
            doi=None,
            citation_count=5,
        ),
        "citer": OpenAlexWork(
            work_id="citer",
            title="Citer",
            abstract="cites root",
            referenced_work_ids=("root",),
            related_work_ids=(),
            is_open_access=True,
            doi=None,
            citation_count=3,
        ),
    }
    graph_store = OpenAlexGraphStore(tmp_path / "graph.sqlite")

    asyncio.run(
        traverse_openalex(
            ("root",),
            InMemoryOpenAlexClient(works),
            TraversalPolicy(max_depth=1, branch_factor=3, require_open_access=True),
            graph_store,
        )
    )

    cached = asyncio.run(
        traverse_openalex(
            ("root",),
            ExplodingOpenAlexClient(),
            TraversalPolicy(max_depth=1, branch_factor=3, require_open_access=True),
            graph_store,
        )
    )

    assert tuple(work.work_id for work in cached) == ("root", "citer")


def test_openalex_traversal_persists_related_edges_and_node_budget(tmp_path: Path) -> None:
    works = {
        "root": OpenAlexWork(
            work_id="root",
            title="Root",
            abstract="root",
            referenced_work_ids=(),
            related_work_ids=("related",),
            is_open_access=True,
            doi=None,
            citation_count=5,
        ),
        "related": OpenAlexWork(
            work_id="related",
            title="Related",
            abstract="related",
            referenced_work_ids=(),
            related_work_ids=(),
            is_open_access=True,
            doi=None,
            citation_count=1,
        ),
    }
    graph_store = OpenAlexGraphStore(tmp_path / "graph.sqlite")

    traversed = asyncio.run(
        traverse_openalex(
            ("root",),
            InMemoryOpenAlexClient(works),
            TraversalPolicy(max_depth=1, branch_factor=2, require_open_access=True, max_nodes=1),
            graph_store,
        )
    )

    assert tuple(work.work_id for work in traversed) == ("root",)
    assert graph_store.edge_targets("root", "related") == ("related",)


def test_openalex_traversal_enforces_wall_clock_budget() -> None:
    work = OpenAlexWork(
        work_id="root",
        title="Root",
        abstract="root",
        referenced_work_ids=(),
        related_work_ids=(),
        is_open_access=True,
        doi=None,
        citation_count=5,
    )

    with pytest.raises(TraversalBudgetExhausted, match="wall-clock"):
        asyncio.run(
            traverse_openalex(
                ("root",),
                InMemoryOpenAlexClient({"root": work}),
                TraversalPolicy(
                    max_depth=1,
                    branch_factor=1,
                    require_open_access=True,
                    wall_clock_seconds=-1.0,
                ),
            )
        )


def test_mine_gap_candidates_emits_all_gap_types() -> None:
    work = OpenAlexWork(
        work_id="root",
        title="Root",
        abstract="root",
        referenced_work_ids=(),
        related_work_ids=(),
        is_open_access=True,
        doi="10/root",
        citation_count=5,
    )

    gaps = mine_gap_candidates((work,), seed_query="fusion")

    assert tuple(gap.gap_type for gap in gaps) == (
        GapType.STRUCTURAL_HOLE,
        GapType.METHODOLOGY_TRANSFER,
        GapType.CONTRADICTION,
        GapType.NEGATIVE_RESULT,
    )
    for gap in gaps:
        gap.verify_self()


def test_mine_gap_candidates_requires_promoted_papers() -> None:
    with pytest.raises(GapMinerProducedNoCandidates):
        mine_gap_candidates((), seed_query="fusion")


def test_paper_store_public_api_promotes_queries_and_guards_bibtex(tmp_path: Path) -> None:
    works = {
        "root": OpenAlexWork(
            work_id="root",
            title="Root Stellarator",
            abstract="quasi isodynamic stellarator",
            referenced_work_ids=(),
            related_work_ids=(),
            is_open_access=True,
            doi="10/root",
            citation_count=5,
            publication_year=2026,
            authors=(OpenAlexAuthor(name="Root Author"),),
            venue="Physics Journal",
        )
    }
    store = PaperStore(tmp_path, client=InMemoryOpenAlexClient(works))

    entries = store.promote(("root",))

    assert entries[0].work_id == "root"
    assert store.query("stellarator", 1)[0].work_id == "root"
    assert store.has_bibtex("root") is True
    assert "Root Author" in store.get_bibtex("root")
    paper_dir = tmp_path / "root"
    assert (paper_dir / "work.json").is_file()
    assert (paper_dir / "ocr.txt").read_text(encoding="utf-8").strip()
    assert (paper_dir / "evidence.json").is_file()
    assert (paper_dir / "PROVENANCE.json").is_file()
    assert (paper_dir / "bibtex.bib").is_file()


def test_paper_store_removes_stale_bibtex_and_verifies_hashes(tmp_path: Path) -> None:
    first = OpenAlexWork(
        work_id="root",
        title="Root Stellarator",
        abstract="quasi isodynamic stellarator",
        referenced_work_ids=(),
        related_work_ids=(),
        is_open_access=True,
        doi="10/root",
        citation_count=5,
        publication_year=2026,
        authors=(OpenAlexAuthor(name="Root Author"),),
    )
    second = OpenAlexWork(
        work_id="root",
        title="Root Stellarator",
        abstract="quasi isodynamic stellarator",
        referenced_work_ids=(),
        related_work_ids=(),
        is_open_access=True,
        doi="10/root",
        citation_count=5,
    )
    client = MutableOpenAlexClient(first)
    store = PaperStore(tmp_path, client=client)

    store.promote(("root",))
    assert (tmp_path / "root" / "bibtex.bib").is_file()
    client.work = second
    store.promote(("root",))

    assert not (tmp_path / "root" / "bibtex.bib").exists()
    assert store.has_bibtex("root") is False
    with pytest.raises(BibtexUnavailable):
        store.get_bibtex("root")

    (tmp_path / "root" / "work.json").write_text("{}", encoding="utf-8")
    with pytest.raises(PaperStoreLookupError, match="mismatch"):
        store.get("root")


def test_paper_store_rejects_unsafe_paths_and_missing_pdf_fetcher(tmp_path: Path) -> None:
    unsafe = OpenAlexWork(
        work_id="../escape",
        title="Unsafe",
        abstract="unsafe",
        referenced_work_ids=(),
        related_work_ids=(),
        is_open_access=True,
        doi=None,
        citation_count=1,
    )
    with pytest.raises(PaperStoreLookupError, match="Unsafe"):
        PaperStore(tmp_path, client=InMemoryOpenAlexClient({"../escape": unsafe})).promote(
            ("../escape",)
        )

    pdf_work = OpenAlexWork(
        work_id="root",
        title="PDF",
        abstract="pdf",
        referenced_work_ids=(),
        related_work_ids=(),
        is_open_access=True,
        doi=None,
        citation_count=1,
        pdf_url="https://example.test/paper.pdf",
    )
    with pytest.raises(OpenAlexAPIError, match="no content fetcher"):
        PaperStore(tmp_path, client=InMemoryOpenAlexClient({"root": pdf_work})).promote(
            ("root",),
            fetch_pdf=True,
        )
    assert not (tmp_path / ".root.staging").exists()
    assert not (tmp_path / "root").exists()

    with pytest.raises(OpenAlexAPIError, match="pdf failed"):
        PaperStore(
            tmp_path,
            client=InMemoryOpenAlexClient({"root": pdf_work}),
            content_fetcher=FailingPdfFetcher(),
        ).promote(("root",), fetch_pdf=True)
    assert not (tmp_path / ".root.staging").exists()
    assert not (tmp_path / "root").exists()

    store = PaperStore(
        tmp_path,
        client=InMemoryOpenAlexClient({"root": pdf_work}),
        content_fetcher=PdfFetcher(),
    )
    promoted = store.promote(("root",), fetch_pdf=True)
    assert promoted[0].pdf_path == tmp_path / "root" / "pdf.pdf"
    pdf_path = promoted[0].pdf_path
    assert pdf_path is not None
    assert pdf_path.read_bytes() == b"pdf:https://example.test/paper.pdf"
