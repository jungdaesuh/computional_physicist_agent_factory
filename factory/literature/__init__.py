# __init__.py — Public exports for the literature module
#
# This file exports the public API of the literature module. Other modules should
# only import from `factory.literature`, not from internal files.

import logging

from factory.literature.api import (
    MODULE_CONTRACT,
    InMemoryOpenAlexClient,
    OpenAlexAuthor,
    OpenAlexClient,
    OpenAlexClientProtocol,
    OpenAlexGraphStore,
    OpenAlexResponse,
    OpenAlexTransport,
    OpenAlexWork,
    PaperStore,
    PaperStoreEntry,
    TraversalPolicy,
    UrlContentFetcher,
    UrllibOpenAlexTransport,
    describe_contract,
    mine_gap_candidates,
    parse_openalex_work,
    rank_works,
    synthesize_bibtex,
    traverse_openalex,
)

logger = logging.getLogger("factory.literature")

# Public exports
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
    "UrllibOpenAlexTransport",
    "describe_contract",
    "mine_gap_candidates",
    "parse_openalex_work",
    "rank_works",
    "synthesize_bibtex",
    "traverse_openalex",
]
