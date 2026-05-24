# test_guide_llm_refusal.py — Unit tests for GuideLLMRefusal propagation
#
# Verifies that both binary_bayesian_surprise and graded_bayesian_surprise
# immediately propagate a GuideLLMRefusal exception when raised by the GuideLLM.

import pytest

from factory.strategy.beliefs import (
    FeasibilityBucket,
    binary_bayesian_surprise,
    graded_bayesian_surprise,
)
from factory.strategy.errors import GuideLLMRefusal


class RefusingGuideLLM:
    """Mock GuideLLM that raises GuideLLMRefusal on query."""

    async def boolean(self, prompt: str) -> bool:
        del prompt
        raise GuideLLMRefusal("Model refused due to safety filters.")

    async def feasibility_bucket(self, prompt: str) -> FeasibilityBucket:
        del prompt
        raise GuideLLMRefusal("Model refused due to safety filters.")


@pytest.mark.anyio
async def test_binary_surprise_refusal_propagation() -> None:
    """Verifies that binary_bayesian_surprise propagates GuideLLMRefusal immediately."""
    guide = RefusingGuideLLM()
    with pytest.raises(GuideLLMRefusal, match="safety filters"):
        await binary_bayesian_surprise("strategy", "evidence", guide, n=5)


@pytest.mark.anyio
async def test_graded_surprise_refusal_propagation() -> None:
    """Verifies that graded_bayesian_surprise propagates GuideLLMRefusal immediately."""
    guide = RefusingGuideLLM()
    with pytest.raises(GuideLLMRefusal, match="safety filters"):
        await graded_bayesian_surprise("strategy", "evidence", guide, n=5)
