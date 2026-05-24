# __init__.py — Public exports for the council module
#
# This file exports the public API of the council module. Other modules should
# only import from `factory.council`, not from internal files.

from __future__ import annotations

import logging

from factory.council.api import (
    BudgetTokenUsageMissing,
    CalibrationReport,
    ChairmanDissentOmission,
    Council,
    CouncilBudgetExceeded,
    CouncilContext,
    CouncilContextValue,
    CouncilError,
    CouncilLineup,
    CouncilSycophancyDetected,
    ModelSpec,
    ModelTimeout,
    OpenRouterError,
    PersonaRefusal,
    ProbeResult,
)

logger = logging.getLogger("factory.council")

# Public exports
__all__ = [
    "Council",
    "CouncilContext",
    "CouncilContextValue",
    "ModelSpec",
    "CouncilLineup",
    "CalibrationReport",
    "ProbeResult",
    "CouncilError",
    "CouncilSycophancyDetected",
    "ChairmanDissentOmission",
    "PersonaRefusal",
    "ModelTimeout",
    "CouncilBudgetExceeded",
    "BudgetTokenUsageMissing",
    "OpenRouterError",
]
