# errors.py — Module-specific errors for genver
#
# Defines the exception hierarchy for genver. All exceptions must inherit
# from FactoryError.


class FactoryError(Exception):
    """Base exception class for the factory."""

    pass


class GenverError(FactoryError):
    """Base exception for the genver module."""

    pass
