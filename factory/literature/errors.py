# errors.py — Module-specific errors for literature
#
# Defines the exception hierarchy for literature. All exceptions must inherit
# from FactoryError.


class FactoryError(Exception):
    """Base exception class for the factory."""

    pass


class LiteratureError(FactoryError):
    """Base exception for the literature module."""

    pass


class OpenAlexAuthError(LiteratureError):
    """Raised when live OpenAlex credentials are missing or stale."""

    pass


class OpenAlexAPIError(LiteratureError):
    """Raised when OpenAlex returns a non-recoverable or exhausted API failure."""

    pass


class GraphStoreCorruption(LiteratureError):
    """Raised when the local OpenAlex graph cache schema marker is invalid."""

    pass


class TraversalBudgetExhausted(LiteratureError):
    """Raised when traversal cannot proceed within the configured bounds."""

    pass


class GapMinerProducedNoCandidates(LiteratureError):
    """Raised when literature evidence cannot support any gap candidates."""

    pass


class PaperStoreLookupError(LiteratureError):
    """Raised when a requested paper-store record is absent."""

    pass


class BibtexUnavailable(LiteratureError):
    """Raised when a promoted paper has insufficient metadata for BibTeX."""

    pass
