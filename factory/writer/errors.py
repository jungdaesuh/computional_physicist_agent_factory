# errors.py — Module-specific errors for writer
#
# Defines the exception hierarchy for writer. All exceptions must inherit
# from FactoryError.


class FactoryError(Exception):
    """Base exception class for the factory."""

    pass


class WriterError(FactoryError):
    """Base exception for the writer module."""

    pass
