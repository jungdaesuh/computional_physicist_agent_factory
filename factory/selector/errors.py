# errors.py — Module-specific errors for selector
#
# Defines the exception hierarchy for selector. All exceptions must inherit
# from FactoryError.


class FactoryError(Exception):
    """Base exception class for the factory."""

    pass


class SelectorError(FactoryError):
    """Base exception for the selector module."""

    pass


class SelectorConfigError(SelectorError):
    """Raised when selector weights configuration is missing, invalid, or doesn't sum to 1."""

    pass


class CatalogStaleError(SelectorError):
    """Raised when the catalog version hash drifts during a selection run."""

    pass
