# test_binary_polarity_gate.py — Unit tests for the binary surprise polarity gate
#
# Verifies that binary_bayesian_surprise returns 0.0 (gate closed) when beliefs
# remain on the same side of the 0.5 threshold, and returns positive KL (gate open)
# when they cross the 0.5 boundary.

import pytest

from factory.strategy.beliefs import FeasibilityBucket, binary_bayesian_surprise
from factory.strategy.errors import BucketCountsEmpty


class MockGuideLLM:
    """Mock GuideLLM that yields a scripted sequence of booleans."""

    def __init__(self, pre_responses: list[bool], post_responses: list[bool]) -> None:
        self.pre_responses = pre_responses
        self.post_responses = post_responses
        self.pre_idx = 0
        self.post_idx = 0

    async def boolean(self, prompt: str) -> bool:
        if "evidence" in prompt.lower():
            val = self.post_responses[self.post_idx]
            self.post_idx += 1
            return val
        else:
            val = self.pre_responses[self.pre_idx]
            self.pre_idx += 1
            return val

    async def feasibility_bucket(self, prompt: str) -> FeasibilityBucket:
        raise NotImplementedError()


@pytest.mark.anyio
async def test_binary_gate_same_side_high() -> None:
    """Gate closes (returns 0.0) if both pre and post means are > 0.5."""
    # Pre: 4/5 True -> k_pre = 4, mean = 5/7 ≈ 0.71 > 0.5
    # Post: 4/5 True -> k_post = 4, total_mean = (1 + 4 + 4) / 12 = 9/12 = 0.75 > 0.5
    guide = MockGuideLLM(
        pre_responses=[True, True, True, True, False],
        post_responses=[True, True, True, True, False],
    )
    val = await binary_bayesian_surprise("strategy", "evidence", guide, n=5)
    assert val == 0.0


@pytest.mark.anyio
async def test_binary_gate_same_side_low() -> None:
    """Gate closes (returns 0.0) if both pre and post means are < 0.5."""
    # Pre: 1/5 True -> k_pre = 1, mean = 2/7 ≈ 0.28 < 0.5
    # Post: 1/5 True -> k_post = 1, total_mean = (1 + 1 + 1) / 12 = 3/12 = 0.25 < 0.5
    guide = MockGuideLLM(
        pre_responses=[True, False, False, False, False],
        post_responses=[True, False, False, False, False],
    )
    val = await binary_bayesian_surprise("strategy", "evidence", guide, n=5)
    assert val == 0.0


@pytest.mark.anyio
async def test_binary_gate_cross_boundary() -> None:
    """Gate opens (returns positive KL) if pre and post means cross 0.5."""
    # Pre: 1/5 True -> k_pre = 1, mean = 2/7 ≈ 0.28 < 0.5
    # Post: 5/5 True -> k_post = 5, total_mean = (1 + 1 + 5) / 12 = 7/12 ≈ 0.58 > 0.5
    guide = MockGuideLLM(
        pre_responses=[True, False, False, False, False],
        post_responses=[True, True, True, True, True],
    )
    val = await binary_bayesian_surprise("strategy", "evidence", guide, n=5)
    assert val > 0.0


@pytest.mark.anyio
async def test_binary_gate_empty_responses() -> None:
    """BucketCountsEmpty raised if no responses return."""
    guide = MockGuideLLM(pre_responses=[], post_responses=[])
    with pytest.raises(BucketCountsEmpty):
        # n = 0 is invalid / results in empty lists
        await binary_bayesian_surprise("strategy", "evidence", guide, n=0)
