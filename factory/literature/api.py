"""Public implementation contract for the literature module."""

from __future__ import annotations

from factory.literature.client import (
    InMemoryOpenAlexClient,
    OpenAlexAuthor,
    OpenAlexClient,
    OpenAlexClientProtocol,
    OpenAlexResponse,
    OpenAlexTransport,
    OpenAlexWork,
    UrllibOpenAlexTransport,
    parse_openalex_work,
)
from factory.literature.graph_store import OpenAlexGraphStore
from factory.literature.miner import (
    TraversalPolicy,
    mine_gap_candidates,
    rank_works,
    traverse_openalex,
)
from factory.literature.paper_store import (
    PaperStore,
    PaperStoreEntry,
    UrlContentFetcher,
    synthesize_bibtex,
)
from factory.module_contracts import ModuleContract

MODULE_CONTRACT = ModuleContract(
    module_name="literature",
    spec_id="007",
    responsibility="Rank literature-derived gaps from OpenAlex traversal and evidence extraction.",
    required_inputs=(
        "OpenAlexWork",
        "TraversalPolicy",
    ),
    produced_outputs=("GapCandidate",),
)


def describe_contract() -> ModuleContract:
    """Return the stable public contract for this module."""
    return MODULE_CONTRACT


__all__ = [
    "InMemoryOpenAlexClient",
    "MODULE_CONTRACT",
    "OpenAlexAuthor",
    "OpenAlexClient",
    "OpenAlexClientProtocol",
    "OpenAlexGraphStore",
    "OpenAlexResponse",
    "OpenAlexTransport",
    "OpenAlexWork",
    "PaperStore",
    "PaperStoreEntry",
    "TraversalPolicy",
    "UrlContentFetcher",
    "describe_contract",
    "mine_gap_candidates",
    "parse_openalex_work",
    "rank_works",
    "synthesize_bibtex",
    "traverse_openalex",
    "UrllibOpenAlexTransport",
]
