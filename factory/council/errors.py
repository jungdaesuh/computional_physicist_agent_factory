# errors.py — Module-specific errors for council
#
# Defines the exception hierarchy for council. All exceptions must inherit
# from FactoryError.

from __future__ import annotations

from factory.artifacts import FactoryError
from factory.budget import BudgetTokenUsageMissing


class CouncilError(FactoryError):
    """Base exception for the council module."""

    pass


class CouncilSycophancyDetected(CouncilError):  # noqa: N818
    """Raised when sycophancy (excessive agreement) is detected among first opinions."""

    pass


class ChairmanDissentOmission(CouncilError):  # noqa: N818
    """Raised when the chairman fails to preserve dissent in the verdict."""

    pass


class PersonaRefusal(CouncilError):  # noqa: N818
    """Raised when a model refuses to adopt a persona due to RLHF or safety policies."""

    pass


class ModelTimeout(CouncilError):  # noqa: N818
    """Raised when a model call times out and no backup is allowed."""

    pass


class CouncilBudgetExceeded(CouncilError):  # noqa: N818
    """Raised when the deliberation cost exceeds the budget threshold."""

    pass


class OpenRouterError(CouncilError):
    """Raised when OpenRouter returns an API error or rate limit."""

    pass


__all__ = [
    "BudgetTokenUsageMissing",
    "ChairmanDissentOmission",
    "CouncilBudgetExceeded",
    "CouncilError",
    "CouncilSycophancyDetected",
    "ModelTimeout",
    "OpenRouterError",
    "PersonaRefusal",
]
