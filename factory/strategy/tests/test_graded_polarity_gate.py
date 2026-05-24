# test_graded_polarity_gate.py — Unit tests for the graded surprise polarity gate
#
# Verifies that graded_bayesian_surprise returns 0.0 (gate closed) when there are
# tied modes, or when the dominant bucket remains unchanged, and returns positive KL
# when the dominant bucket changes.

import pytest

from factory.strategy.beliefs import FeasibilityBucket, graded_bayesian_surprise


class MockGradedGuideLLM:
    """Mock GuideLLM that yields a scripted sequence of feasibility buckets."""

    def __init__(
        self, pre_responses: list[FeasibilityBucket], post_responses: list[FeasibilityBucket]
    ) -> None:
        self.pre_responses = pre_responses
        self.post_responses = post_responses
        self.pre_idx = 0
        self.post_idx = 0

    async def boolean(self, prompt: str) -> bool:
        raise NotImplementedError()

    async def feasibility_bucket(self, prompt: str) -> FeasibilityBucket:
        if "evidence" in prompt.lower():
            val = self.post_responses[self.post_idx]
            self.post_idx += 1
            return val
        else:
            val = self.pre_responses[self.pre_idx]
            self.pre_idx += 1
            return val


@pytest.mark.anyio
async def test_graded_gate_tied_modes() -> None:
    """Gate closes (returns 0.0) if prior or posterior has tied modes."""
    # Pre counts: {"lt_10": 2, "10_50": 2, "gt_50": 1} -> tie between lt_10 and 10_50
    guide = MockGradedGuideLLM(
        pre_responses=["lt_10", "lt_10", "10_50", "10_50", "gt_50"],
        post_responses=["gt_50", "gt_50", "gt_50", "gt_50", "gt_50"],
    )
    val = await graded_bayesian_surprise("strategy", "evidence", guide, n=5)
    assert val == 0.0


@pytest.mark.anyio
async def test_graded_gate_unchanged_bucket() -> None:
    """Gate closes (returns 0.0) if the dominant bucket is the same pre and post."""
    # Pre: lt_10 is dominant (3 counts)
    # Post: lt_10 is dominant (3 counts)
    guide = MockGradedGuideLLM(
        pre_responses=["lt_10", "lt_10", "lt_10", "10_50", "gt_50"],
        post_responses=["lt_10", "lt_10", "lt_10", "10_50", "gt_50"],
    )
    val = await graded_bayesian_surprise("strategy", "evidence", guide, n=5)
    assert val == 0.0


@pytest.mark.anyio
async def test_graded_gate_changed_bucket() -> None:
    """Gate opens (returns positive KL) if the dominant bucket changes."""
    # Pre: lt_10 is dominant (3 counts)
    # Post: gt_50 is dominant (4 counts)
    guide = MockGradedGuideLLM(
        pre_responses=["lt_10", "lt_10", "lt_10", "10_50", "gt_50"],
        post_responses=["gt_50", "gt_50", "gt_50", "gt_50", "lt_10"],
    )
    val = await graded_bayesian_surprise("strategy", "evidence", guide, n=5)
    assert val > 0.0
