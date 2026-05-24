# errors.py — Module-specific errors for validation
#
# Defines the exception hierarchy for validation. All exceptions must inherit
# from FactoryError.


class FactoryError(Exception):
    """Base exception class for the factory."""

    pass


class ValidationError(FactoryError):
    """Base exception for the validation module."""

    pass
