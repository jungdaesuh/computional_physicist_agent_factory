# errors.py — Module-specific errors for surrogate
#
# Defines the exception hierarchy for surrogate. All exceptions must inherit
# from FactoryError.


class FactoryError(Exception):
    """Base exception class for the factory."""

    pass


class SurrogateError(FactoryError):
    """Base exception for the surrogate module."""

    pass
