# errors.py — Module-specific errors for operator
#
# Defines the exception hierarchy for operator. All exceptions must inherit
# from FactoryError.


class FactoryError(Exception):
    """Base exception class for the factory."""

    pass


class OperatorError(FactoryError):
    """Base exception for the operator module."""

    pass


class FactoryNotRunning(OperatorError):
    """Raised when an operation requires a running factory state machine."""

    pass


class CycleNotFound(OperatorError):
    """Raised when the specified cycle ID is not found."""

    pass


class AmbiguousHypothesisId(OperatorError):
    """Raised when a short hypothesis ID matches multiple entries."""

    pass


class ApprovalDenied(OperatorError):
    """Raised when a G6 approval command fails or is rejected."""

    pass


class TelemetryUnavailable(OperatorError):
    """Raised when the telemetry event bus is unavailable."""

    pass


class ConfigurationInvalid(OperatorError):
    """Raised when the operator configuration is malformed or invalid."""

    pass


class NonLoopbackBindRejected(OperatorError):
    """Raised when attempting to bind the HTTP daemon to a non-loopback interface."""

    pass

