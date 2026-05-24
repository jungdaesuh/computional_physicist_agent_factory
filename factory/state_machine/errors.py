# errors.py — Module-specific errors for state_machine
#
# Defines the exception hierarchy for state_machine. All exceptions must inherit
# from FactoryError.


class FactoryError(Exception):
    """Base exception class for the factory."""

    pass


class StateMachineError(FactoryError):
    """Base exception for the state_machine module."""

    pass
