# errors.py — Module-specific errors for ledger
#
# Defines the exception hierarchy for ledger. All exceptions must inherit
# from FactoryError.


class FactoryError(Exception):
    """Base exception class for the factory."""

    pass


class LedgerError(FactoryError):
    """Base exception for the ledger module."""

    pass
