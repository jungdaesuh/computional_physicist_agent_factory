# __init__.py — Public exports for the telemetry module
#
# This file exports the public API of the telemetry module. Other modules should
# only import from `factory.telemetry`, not from internal files.

import logging

from factory.telemetry.api import (
    KNOWN_NAMESPACES,
    Aggregator,
    AuditQuery,
    EventRegistry,
    TelemetryEmitter,
    emit,
    set_active_emitter,
)
from factory.telemetry.errors import (
    AggregatorBacklog,
    EventTaxonomyViolation,
    JSONLineCorrupted,
    LogFileLocked,
    RetentionPolicyConflict,
    TelemetryError,
)

logger = logging.getLogger("factory.telemetry")

# Public exports
__all__ = [
    "TelemetryError",
    "EventTaxonomyViolation",
    "LogFileLocked",
    "JSONLineCorrupted",
    "AggregatorBacklog",
    "RetentionPolicyConflict",
    "KNOWN_NAMESPACES",
    "EventRegistry",
    "TelemetryEmitter",
    "set_active_emitter",
    "emit",
    "AuditQuery",
    "Aggregator",
]
