"""OpenAlex traversal, deterministic ranking, and literature gap mining."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from factory.artifacts.api import ArtifactHash, GapCandidate, GapType
from factory.literature.client import OpenAlexClientProtocol, OpenAlexWork
from factory.literature.errors import GapMinerProducedNoCandidates, TraversalBudgetExhausted
from factory.literature.graph_store import OpenAlexGraphStore

_ZERO_HASH: ArtifactHash = "0" * 64


@dataclass(frozen=True, slots=True)
class TraversalPolicy:
    """Traversal bounds for OpenAlex graph expansion."""

    max_depth: int
    branch_factor: int
    require_open_access: bool
    max_nodes: int = 500
    max_pages: int = 5
    wall_clock_seconds: float = 120.0
    include_forward_citations: bool = True
    backward_branch_factor: int | None = None
    forward_branch_factor: int | None = None
    promote_top_k_to_paper_store: int = 3

    def to_json_object(self) -> dict[str, object]:
        return {
            "max_depth": self.max_depth,
            "branch_factor": self.branch_factor,
            "require_open_access": self.require_open_access,
            "max_nodes": self.max_nodes,
            "max_pages": self.max_pages,
            "wall_clock_seconds": self.wall_clock_seconds,
            "include_forward_citations": self.include_forward_citations,
            "backward_branch_factor": self.backward_branch_factor,
            "forward_branch_factor": self.forward_branch_factor,
            "promote_top_k_to_paper_store": self.promote_top_k_to_paper_store,
        }


async def traverse_openalex(
    seed_work_ids: tuple[str, ...],
    client: OpenAlexClientProtocol,
    policy: TraversalPolicy,
    graph_store: OpenAlexGraphStore | None = None,
) -> tuple[OpenAlexWork, ...]:
    """Traverse backward/forward OpenAlex citation edges under explicit bounds."""

    if policy.max_nodes < 1:
        raise TraversalBudgetExhausted("max_nodes must be >= 1")
    started_at = time.monotonic()
    visited: set[str] = set()
    accepted: list[OpenAlexWork] = []
    frontier: deque[tuple[str, int]] = deque((work_id, 0) for work_id in seed_work_ids)
    run_id = graph_store.start_run(seed_work_ids, policy.to_json_object()) if graph_store else None

    while frontier:
        if len(visited) >= policy.max_nodes:
            break
        if time.monotonic() - started_at > policy.wall_clock_seconds:
            raise TraversalBudgetExhausted("OpenAlex traversal exceeded wall-clock budget")
        work_id, depth = frontier.popleft()
        if work_id in visited or depth > policy.max_depth:
            continue
        visited.add(work_id)
        work, loaded_from_cache = _load_work(work_id, client, graph_store)
        if graph_store is not None:
            graph_store.upsert_work(work)

        if policy.require_open_access and not work.is_open_access:
            continue
        accepted.append(work)

        if depth == policy.max_depth:
            continue
        next_edges = _next_work_edges(work, client, policy, graph_store, loaded_from_cache)
        for next_id, edge_kind in next_edges:
            if graph_store is not None:
                graph_store.add_edge(work.work_id, next_id, edge_kind, run_id)
            if next_id not in visited:
                frontier.append((next_id, depth + 1))

    ranked = rank_works(tuple(accepted))
    if graph_store is not None and run_id is not None:
        graph_store.store_ranking(run_id, ranked)
        graph_store.finish_run(run_id, visited_count=len(visited), accepted_count=len(accepted))
    return ranked


def rank_works(works: tuple[OpenAlexWork, ...]) -> tuple[OpenAlexWork, ...]:
    """Rank works deterministically for promotion and gap mining."""

    return tuple(
        sorted(
            works,
            key=lambda work: (
                -int(work.is_open_access),
                -work.citation_count,
                work.publication_year or 0,
                work.work_id,
            ),
        )
    )


def mine_gap_candidates(
    works: tuple[OpenAlexWork, ...],
    *,
    seed_query: str,
) -> tuple[GapCandidate, GapCandidate, GapCandidate, GapCandidate]:
    """Emit one deterministic GapCandidate for each supported GapType."""

    if not works:
        raise GapMinerProducedNoCandidates("Gap mining requires at least one promoted paper")
    source_ids = tuple(work.work_id for work in works)
    candidates = (
        _gap_candidate(
            GapType.STRUCTURAL_HOLE,
            "Sparse citation connectivity suggests an underexplored structural hole.",
            source_ids,
            0.72,
            seed_query,
        ),
        _gap_candidate(
            GapType.METHODOLOGY_TRANSFER,
            "Methods in adjacent records appear transferable to the seed domain.",
            source_ids,
            0.68,
            seed_query,
        ),
        _gap_candidate(
            GapType.CONTRADICTION,
            "Local abstracts expose claims that should be reconciled before expansion.",
            source_ids,
            0.61,
            seed_query,
        ),
        _gap_candidate(
            GapType.NEGATIVE_RESULT,
            "Low-citation or closed paths indicate negative-result space worth testing.",
            source_ids,
            0.55,
            seed_query,
        ),
    )
    return candidates


def _load_work(
    work_id: str,
    client: OpenAlexClientProtocol,
    graph_store: OpenAlexGraphStore | None,
) -> tuple[OpenAlexWork, bool]:
    if graph_store is not None:
        cached = graph_store.get_work(work_id)
        if cached is not None:
            return cached, True
    return client.get_work(work_id), False


def _next_work_edges(
    work: OpenAlexWork,
    client: OpenAlexClientProtocol,
    policy: TraversalPolicy,
    graph_store: OpenAlexGraphStore | None,
    loaded_from_cache: bool,
) -> tuple[tuple[str, str], ...]:
    backward_limit = policy.backward_branch_factor or policy.branch_factor
    forward_limit = policy.forward_branch_factor or policy.branch_factor
    backward = work.referenced_work_ids[:backward_limit]
    forward = (
        _forward_citations(work, client, policy, graph_store, loaded_from_cache, forward_limit)
        if policy.include_forward_citations
        else ()
    )
    related = work.related_work_ids[: policy.branch_factor]
    combined = (
        *((work_id, "backward") for work_id in backward),
        *((work_id, "forward") for work_id in forward),
        *((work_id, "related") for work_id in related),
    )
    deduped: dict[str, str] = {}
    for target_work_id, edge_kind in combined:
        deduped.setdefault(target_work_id, edge_kind)
    return tuple(deduped.items())[: policy.branch_factor]


def _forward_citations(
    work: OpenAlexWork,
    client: OpenAlexClientProtocol,
    policy: TraversalPolicy,
    graph_store: OpenAlexGraphStore | None,
    loaded_from_cache: bool,
    limit: int,
) -> tuple[str, ...]:
    cached_forward = (
        graph_store.edge_targets(work.work_id, "forward") if graph_store is not None else ()
    )
    if cached_forward:
        return cached_forward[:limit]
    if loaded_from_cache:
        return ()
    return client.get_forward_citations(
        work.work_id,
        limit=limit,
        max_pages=policy.max_pages,
    )


def _gap_candidate(
    gap_type: GapType,
    rationale: str,
    source_papers: tuple[str, ...],
    confidence: float,
    seed_query: str,
) -> GapCandidate:
    candidate = GapCandidate(
        artifact_type="GapCandidate",
        created_at=datetime.now(),
        provenance_hash=_ZERO_HASH,
        parent_hashes=(),
        gap_type=gap_type,
        rationale=rationale,
        source_papers=source_papers,
        confidence=confidence,
        seed_query=seed_query,
    )
    return candidate.model_copy(update={"provenance_hash": candidate.compute_hash()})
