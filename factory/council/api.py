# api.py — Public interface of council
#
# This file defines the public-facing API for the council module.
# All functions/classes should have docstrings and log their calls.

from __future__ import annotations

import logging

from factory.council.deliberation import Council
from factory.council.errors import (
    BudgetTokenUsageMissing,
    ChairmanDissentOmission,
    CouncilBudgetExceeded,
    CouncilError,
    CouncilSycophancyDetected,
    ModelTimeout,
    OpenRouterError,
    PersonaRefusal,
)
from factory.council.types import (
    CalibrationReport,
    CouncilContext,
    CouncilContextValue,
    CouncilLineup,
    ModelSpec,
    ProbeResult,
)

logger = logging.getLogger("factory.council.api")

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
