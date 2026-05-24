"""Command line interface for OpenAlex literature discovery."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from factory.literature.client import InMemoryOpenAlexClient, OpenAlexClient, OpenAlexWork
from factory.literature.graph_store import OpenAlexGraphStore
from factory.literature.miner import (
    TraversalPolicy,
    mine_gap_candidates,
    rank_works,
    traverse_openalex,
)
from factory.literature.paper_store import PaperStore, UrlContentFetcher

logger = logging.getLogger("factory.literature.cli")


def main(argv: Sequence[str] = sys.argv[1:]) -> None:
    """Run literature-discovery subcommands."""

    parser = argparse.ArgumentParser(description="Literature Discovery CLI")
    parser.add_argument(
        "--mock-mode",
        action="store_true",
        help="Use deterministic mock OpenAlex data",
    )
    parser.add_argument("--graph-db", default="runs/_graph_store/openalex.sqlite")
    parser.add_argument("--paper-store", default="runs/_paper_store")
    parser.add_argument("--rebuild-graph-store", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_search = subparsers.add_parser("seed-search")
    seed_search.add_argument("--query", required=True)
    seed_search.add_argument("--limit", type=int, default=5)

    traverse = subparsers.add_parser("traverse")
    traverse.add_argument("--seed-ids", required=True)
    _add_policy_args(traverse)

    rank = subparsers.add_parser("rank")
    rank.add_argument("--seed-ids", required=True)
    _add_policy_args(rank)

    promote = subparsers.add_parser("promote")
    promote.add_argument("--work-ids", required=True)
    promote.add_argument("--fetch-pdf", action="store_true")

    mine_gaps = subparsers.add_parser("mine-gaps")
    mine_gaps.add_argument("--seed-query", required=True)
    mine_gaps.add_argument("--limit", type=int, default=5)
    mine_gaps.add_argument("--promote-top-k", type=int, default=3)
    _add_policy_args(mine_gaps)

    show_graph = subparsers.add_parser("show-graph")
    show_graph.add_argument("--run-id")

    args = parser.parse_args(argv)
    graph_store = OpenAlexGraphStore(Path(args.graph_db), rebuild=args.rebuild_graph_store)

    if args.command == "show-graph":
        print(_json(graph_store.summary(args.run_id)))
        return

    client = _client(mock_mode=args.mock_mode)

    if args.command == "seed-search":
        works = client.search_works(args.query, {"open_access.is_oa": True}, limit=args.limit)
        print(_json({"work_ids": [work.work_id for work in works]}))
    elif args.command == "traverse":
        works = asyncio.run(
            traverse_openalex(_ids(args.seed_ids), client, _policy(args), graph_store)
        )
        print(_json({"work_ids": [work.work_id for work in works]}))
    elif args.command == "rank":
        works = asyncio.run(
            traverse_openalex(_ids(args.seed_ids), client, _policy(args), graph_store)
        )
        print(_json({"work_ids": [work.work_id for work in rank_works(works)]}))
    elif args.command == "promote":
        paper_store = _paper_store(args, graph_store, client)
        entries = paper_store.promote(_ids(args.work_ids), fetch_pdf=args.fetch_pdf)
        print(_json({"promoted": [entry.work_id for entry in entries]}))
    elif args.command == "mine-gaps":
        seed_works = client.search_works(
            args.seed_query,
            {"open_access.is_oa": True},
            limit=args.limit,
        )
        works = asyncio.run(
            traverse_openalex(
                tuple(work.work_id for work in seed_works),
                client,
                _policy(args),
                graph_store,
            )
        )
        paper_store = _paper_store(args, graph_store, client)
        promoted_works = works[: args.promote_top_k]
        promoted = paper_store.promote(
            tuple(work.work_id for work in promoted_works),
            fetch_pdf=False,
        )
        gaps = mine_gap_candidates(promoted_works, seed_query=args.seed_query)
        print(
            _json(
                {
                    "promoted": [entry.work_id for entry in promoted],
                    "gap_types": [gap.gap_type.value for gap in gaps],
                    "source_papers": [work.work_id for work in promoted_works],
                }
            )
        )


def _add_policy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--branch-factor", type=int, default=10)
    parser.add_argument("--backward-branch-factor", type=int)
    parser.add_argument("--forward-branch-factor", type=int)
    parser.add_argument("--max-nodes", type=int, default=500)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--wall-clock-seconds", type=float, default=120.0)
    parser.add_argument("--allow-closed", action="store_true")
    parser.add_argument("--no-forward-citations", action="store_true")


def _policy(args: argparse.Namespace) -> TraversalPolicy:
    return TraversalPolicy(
        max_depth=args.max_depth,
        branch_factor=args.branch_factor,
        require_open_access=not args.allow_closed,
        max_nodes=args.max_nodes,
        max_pages=args.max_pages,
        wall_clock_seconds=args.wall_clock_seconds,
        include_forward_citations=not args.no_forward_citations,
        backward_branch_factor=args.backward_branch_factor,
        forward_branch_factor=args.forward_branch_factor,
        promote_top_k_to_paper_store=getattr(args, "promote_top_k", 3),
    )


def _client(*, mock_mode: bool) -> OpenAlexClient | InMemoryOpenAlexClient:
    if mock_mode:
        return InMemoryOpenAlexClient(_mock_works())
    return OpenAlexClient()


def _ids(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _paper_store(
    args: argparse.Namespace,
    graph_store: OpenAlexGraphStore,
    client: OpenAlexClient | InMemoryOpenAlexClient,
) -> PaperStore:
    return PaperStore(
        Path(args.paper_store),
        graph_store=graph_store,
        client=client,
        content_fetcher=UrlContentFetcher(),
    )


def _json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True)


def _mock_works() -> dict[str, OpenAlexWork]:
    return {
        "W-MOCK-ROOT": OpenAlexWork(
            work_id="W-MOCK-ROOT",
            title="Quasi Isodynamic Stellarator Coil Simplicity",
            abstract="quasi isodynamic stellarator coil simplicity",
            referenced_work_ids=("W-MOCK-BACKWARD",),
            related_work_ids=("W-MOCK-RELATED",),
            is_open_access=True,
            doi="10.0000/root",
            citation_count=20,
            publication_year=2026,
        ),
        "W-MOCK-BACKWARD": OpenAlexWork(
            work_id="W-MOCK-BACKWARD",
            title="Earlier Stellarator Optimization",
            abstract="stellarator optimization method",
            referenced_work_ids=(),
            related_work_ids=(),
            is_open_access=True,
            doi="10.0000/backward",
            citation_count=50,
            publication_year=2024,
        ),
        "W-MOCK-RELATED": OpenAlexWork(
            work_id="W-MOCK-RELATED",
            title="Related Coil Design",
            abstract="related coil design",
            referenced_work_ids=("W-MOCK-ROOT",),
            related_work_ids=(),
            is_open_access=True,
            doi="10.0000/related",
            citation_count=5,
            publication_year=2025,
        ),
    }


if __name__ == "__main__":
    main()
