# errors.py — Module-specific errors for budget
#
# Defines the exception hierarchy for budget. All exceptions must inherit
# from FactoryError.


class FactoryError(Exception):
    """Base exception class for the factory."""

    pass


class BudgetError(FactoryError):
    """Base exception for the budget module."""

    pass
