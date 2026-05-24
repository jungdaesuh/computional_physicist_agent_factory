# errors.py — Module-specific errors for telemetry
#
# Defines the exception hierarchy for telemetry. All exceptions must inherit
# from FactoryError.


class FactoryError(Exception):
    """Base exception class for the factory."""

    pass


class TelemetryError(FactoryError):
    """Base exception for the telemetry module."""

    pass


class EventTaxonomyViolation(TelemetryError):
    """Raised when event taxonomy or payload schema validation fails."""

    pass


class LogFileLocked(TelemetryError):
    """Raised when an exclusive log lock cannot be acquired within the timeout period."""

    pass


class JSONLineCorrupted(TelemetryError):
    """Raised/logged when a corruption or truncation is detected in a JSONL line."""

    pass


class AggregatorBacklog(TelemetryError):
    """Raised when the metrics aggregator falls too far behind the active cycle stream."""

    pass


class RetentionPolicyConflict(TelemetryError):
    """Raised when an operator action violates the indefinite retention policy for cycle logs."""

    pass
