# test_chairman_policy.py — Unit tests for chairman selection policy
#
# Verifies the behavior of random, round_robin, and weighted_by_cost selection policies.

import logging
from typing import Literal

import pytest

from factory.artifacts import PersonaName
from factory.budget import BudgetTokenUsageMissing
from factory.council.chairman import PricingTable, select_chairman
from factory.council.deliberation import Council
from factory.council.types import CouncilLineup, ModelSpec

logger = logging.getLogger("factory.council.tests.test_chairman_policy")


def create_valid_lineup(
    policy: Literal["random", "round_robin", "weighted_by_cost"],
) -> CouncilLineup:
    """Helper to create a valid CouncilLineup for tests."""
    models = [
        ModelSpec(openrouter_id="openai/gpt-5.5", vendor="openai"),
        ModelSpec(openrouter_id="anthropic/claude-opus-4.7", vendor="anthropic"),
        ModelSpec(openrouter_id="google/gemini-3.1-pro-preview", vendor="google"),
        ModelSpec(openrouter_id="x-ai/grok-4.3", vendor="x-ai"),
    ]
    persona_assignment = {
        "openai/gpt-5.5": PersonaName.PESSIMIST,
        "anthropic/claude-opus-4.7": PersonaName.VISIONARY,
        "google/gemini-3.1-pro-preview": PersonaName.PESSIMIST,
        "x-ai/grok-4.3": PersonaName.PRAGMATIST,
    }
    return CouncilLineup(
        models=models,
        persona_assignment=persona_assignment,
        chairman_policy=policy,
    )


def test_select_chairman_random() -> None:
    """Verifies that random policy selects a model from the lineup."""
    logger.info("Running test_select_chairman_random")
    lineup = create_valid_lineup("random")
    model_ids = {m.openrouter_id for m in lineup.models}

    # Call multiple times to check random selections
    selections = set()
    for _ in range(50):
        selected = select_chairman(lineup, session_counter=0)
        assert selected.openrouter_id in model_ids
        selections.add(selected.openrouter_id)

    # With 50 trials, we should see multiple different selections
    assert len(selections) > 1


def test_select_chairman_round_robin() -> None:
    """Verifies that round_robin policy selects models in a deterministic order."""
    logger.info("Running test_select_chairman_round_robin")
    lineup = create_valid_lineup("round_robin")

    # session_counter modulo length of models (4)
    expected_order = [
        lineup.models[0].openrouter_id,
        lineup.models[1].openrouter_id,
        lineup.models[2].openrouter_id,
        lineup.models[3].openrouter_id,
        lineup.models[0].openrouter_id,
    ]

    for counter, expected_id in enumerate(expected_order):
        selected = select_chairman(lineup, session_counter=counter)
        assert selected.openrouter_id == expected_id


def test_select_chairman_weighted_by_cost() -> None:
    """Verifies that weighted_by_cost policy weights selection by inverse output cost."""
    logger.info("Running test_select_chairman_weighted_by_cost")
    lineup = create_valid_lineup("weighted_by_cost")

    # Setup a mock pricing table with extreme differences
    # openai: very expensive (cost = 100) -> weight = 1/100 = 0.01
    # anthropic: average (cost = 10) -> weight = 1/10 = 0.1
    # google: cheap (cost = 1) -> weight = 1/1 = 1.0
    # x-ai: free (cost = 0) -> weight = 1e9
    pricing_data = {
        "openai/gpt-5.5": {"output_per_1m_tokens_usd": 100.0},
        "anthropic/claude-opus-4.7": {"output_per_1m_tokens_usd": 10.0},
        "google/gemini-3.1-pro-preview": {"output_per_1m_tokens_usd": 1.0},
        "x-ai/grok-4.3": {"output_per_1m_tokens_usd": 0.0},
    }
    pricing_table = PricingTable(pricing_data)

    # Perform multiple trials
    counts = {m.openrouter_id: 0 for m in lineup.models}
    for _ in range(100):
        selected = select_chairman(lineup, session_counter=0, pricing_table=pricing_table)
        counts[selected.openrouter_id] += 1

    # Since x-ai cost is 0, its weight is 1e9 which dominates completely
    assert counts["x-ai/grok-4.3"] == 100
    assert counts["openai/gpt-5.5"] == 0

    # Let's test again with non-zero costs where google is cheaper than openai and anthropic
    pricing_data_nonzero = {
        "openai/gpt-5.5": {"output_per_1m_tokens_usd": 10.0},  # weight 0.1
        "anthropic/claude-opus-4.7": {"output_per_1m_tokens_usd": 5.0},  # weight 0.2
        "google/gemini-3.1-pro-preview": {"output_per_1m_tokens_usd": 1.0},  # weight 1.0
        "x-ai/grok-4.3": {"output_per_1m_tokens_usd": 1.0},  # weight 1.0
    }
    pricing_table_nonzero = PricingTable(pricing_data_nonzero)

    counts_nonzero = {m.openrouter_id: 0 for m in lineup.models}
    for _ in range(1000):
        selected = select_chairman(lineup, session_counter=0, pricing_table=pricing_table_nonzero)
        counts_nonzero[selected.openrouter_id] += 1

    # The cheaper models (google/gemini-3.1-pro-preview and x-ai/grok-4.3) should have much
    # higher selection counts than openai/gpt-5.5
    assert counts_nonzero["google/gemini-3.1-pro-preview"] > counts_nonzero["openai/gpt-5.5"]
    assert counts_nonzero["x-ai/grok-4.3"] > counts_nonzero["anthropic/claude-opus-4.7"]


def test_pricing_table_missing_model_raises_typed_budget_error() -> None:
    """Council pricing misses preserve the shared typed budget exception."""
    pricing_table = PricingTable({})

    with pytest.raises(BudgetTokenUsageMissing) as exc_info:
        pricing_table.lookup("missing/model", "input")

    assert exc_info.value.module == "council"
    assert exc_info.value.model_id == "missing/model"
    assert exc_info.value.description == "pricing entry missing"


def test_council_exception_mapper_preserves_typed_budget_error() -> None:
    """LLM-client usage accounting errors are not wrapped as OpenRouterError."""
    council = object.__new__(Council)
    original = BudgetTokenUsageMissing(
        module="llm_client",
        model_id="google/gemini-3.5-flash",
        description="usage block absent",
    )

    with pytest.raises(BudgetTokenUsageMissing) as exc_info:
        council._raise_mapped_exception("google/gemini-3.5-flash", original)

    assert exc_info.value is original
