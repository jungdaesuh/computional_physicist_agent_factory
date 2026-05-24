# __init__.py — Public exports for the selector module
#
# This file exports the public API of the selector module. Other modules should
# only import from `factory.selector`, not from internal files.

from __future__ import annotations

import logging

from factory.selector.api import (
    Candidate,
    CostEstimate,
    SelectionResult,
    Selector,
    SelectorWeights,
    TelemetryReader,
    TelemetryStub,
)
from factory.selector.errors import (
    CatalogStaleError,
    SelectorConfigError,
    SelectorError,
)

logger = logging.getLogger("factory.selector")

# Public exports
__all__ = [
    "Selector",
    "SelectorWeights",
    "Candidate",
    "CostEstimate",
    "SelectionResult",
    "TelemetryReader",
    "TelemetryStub",
    "SelectorError",
    "SelectorConfigError",
    "CatalogStaleError",
]
