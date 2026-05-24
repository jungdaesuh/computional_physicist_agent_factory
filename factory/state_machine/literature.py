"""State-machine entry point for bounded literature discovery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from factory.literature import (
    InMemoryOpenAlexClient,
    OpenAlexClient,
    OpenAlexClientProtocol,
    OpenAlexGraphStore,
    OpenAlexWork,
    PaperStore,
    TraversalPolicy,
    mine_gap_candidates,
    traverse_openalex,
)


@dataclass(frozen=True, slots=True)
class LiteratureDiscoveryRequest:
    """Inputs the state machine needs to run spec-007 discovery as one bounded step."""

    seed_query: str
    graph_db_path: Path
    paper_store_root: Path
    max_depth: int = 2
    branch_factor: int = 10
    max_nodes: int = 500
    max_pages: int = 5
    wall_clock_seconds: float = 120.0
    promote_top_k: int = 3
    mock_mode: bool = False
    rebuild_graph_store: bool = False


@dataclass(frozen=True, slots=True)
class LiteratureDiscoveryResult:
    """Serializable summary handed from literature discovery into G0/G1 scheduling."""

    source_work_ids: tuple[str, ...]
    promoted_work_ids: tuple[str, ...]
    gap_types: tuple[str, ...]
    graph_summary: dict[str, int | str]


def run_literature_discovery(
    request: LiteratureDiscoveryRequest,
    client: OpenAlexClientProtocol | None = None,
) -> LiteratureDiscoveryResult:
    """Run seed search, traversal, PaperStore promotion, and gap mining for a cycle."""

    graph_store = OpenAlexGraphStore(
        request.graph_db_path,
        rebuild=request.rebuild_graph_store,
    )
    resolved_client = client or _default_client(request.mock_mode)
    seed_works = resolved_client.search_works(
        request.seed_query,
        {"open_access.is_oa": True},
        limit=request.branch_factor,
    )
    policy = TraversalPolicy(
        max_depth=request.max_depth,
        branch_factor=request.branch_factor,
        require_open_access=True,
        max_nodes=request.max_nodes,
        max_pages=request.max_pages,
        wall_clock_seconds=request.wall_clock_seconds,
        promote_top_k_to_paper_store=request.promote_top_k,
    )
    ranked_works = asyncio.run(
        traverse_openalex(
            tuple(work.work_id for work in seed_works),
            resolved_client,
            policy,
            graph_store,
        )
    )
    paper_store = PaperStore(
        request.paper_store_root,
        graph_store=graph_store,
        client=resolved_client,
    )
    promoted = paper_store.promote(
        tuple(work.work_id for work in ranked_works[: request.promote_top_k])
    )
    gaps = mine_gap_candidates(ranked_works, seed_query=request.seed_query)
    return LiteratureDiscoveryResult(
        source_work_ids=tuple(work.work_id for work in ranked_works),
        promoted_work_ids=tuple(entry.work_id for entry in promoted),
        gap_types=tuple(gap.gap_type.value for gap in gaps),
        graph_summary=graph_store.summary(),
    )


def _default_client(mock_mode: bool) -> OpenAlexClientProtocol:
    if mock_mode:
        return InMemoryOpenAlexClient(
            {
                "W-MOCK-ROOT": OpenAlexWork(
                    work_id="W-MOCK-ROOT",
                    title="Mock State Machine Literature Seed",
                    abstract="quasi isodynamic stellarator coil simplicity",
                    referenced_work_ids=(),
                    related_work_ids=(),
                    is_open_access=True,
                    doi="10.0000/state-machine-mock",
                    citation_count=1,
                    publication_year=2026,
                )
            }
        )
    return OpenAlexClient()


__all__ = [
    "LiteratureDiscoveryRequest",
    "LiteratureDiscoveryResult",
    "run_literature_discovery",
]
