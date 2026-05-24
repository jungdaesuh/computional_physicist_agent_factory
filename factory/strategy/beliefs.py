# beliefs.py — Bayesian Surprise and KL Divergence Functions
#
# This file implements the mathematics for calculating Bayesian surprise
# using closed-form KL divergence formulas for Beta and Dirichlet distributions,
# as well as the GuideLLM elicitation logic.

from __future__ import annotations

import asyncio
import logging
import math
from typing import Literal, Protocol

import scipy.special as sp

from factory.strategy.errors import (
    BucketCountsEmpty,
    DirichletDegenerateAlpha,
)

logger = logging.getLogger("factory.strategy.beliefs")

FeasibilityBucket = Literal["lt_10", "10_50", "gt_50"]


class GuideLLM(Protocol):
    """Protocol for the GuideLLM elicitation handle."""

    async def boolean(self, prompt: str) -> bool:
        """Elicit a yes/no response from the model as a boolean."""
        ...

    async def feasibility_bucket(self, prompt: str) -> FeasibilityBucket:
        """Elicit a feasibility bucket categorization from the model."""
        ...


# --------------------------------------------------------------------------
# Prompt templates
# --------------------------------------------------------------------------


def render_prior_template(strategy_md: str) -> str:
    """Render the prompt template for the binary prior probability."""
    return (
        "You are an expert computational physicist.\n"
        "Below is a proposed stellarator optimization strategy:\n"
        "---\n"
        f"{strategy_md}\n"
        "---\n"
        "Based on this strategy description alone, do you believe it will produce highly "
        "promising results "
        "(e.g. outperforming DESC/SIMSOPT baselines)?\n"
        'Respond with a single JSON object containing a boolean field "promising" '
        "set to true or false."
    )


def render_post_template(strategy_md: str, evidence: str) -> str:
    """Render the prompt template for the binary posterior probability."""
    return (
        "You are an expert computational physicist.\n"
        "Below is a proposed stellarator optimization strategy:\n"
        "---\n"
        f"{strategy_md}\n"
        "---\n"
        "We ran this strategy for one cycle and collected the following evidence:\n"
        "---\n"
        f"{evidence}\n"
        "---\n"
        "Based on both the strategy description and this evidence, do you believe it "
        "will produce highly promising results "
        "(e.g. outperforming DESC/SIMSOPT baselines)?\n"
        'Respond with a single JSON object containing a boolean field "promising" '
        "set to true or false."
    )


def render_graded_prior_template(strategy_md: str) -> str:
    """Render the prompt template for the graded prior probability."""
    return (
        "You are an expert computational physicist.\n"
        "Below is a proposed stellarator optimization strategy:\n"
        "---\n"
        f"{strategy_md}\n"
        "---\n"
        "Based on this strategy description alone, estimate the fraction of feasible "
        "candidates this strategy will yield.\n"
        "Categorize the fraction into one of three buckets:\n"
        '1. "lt_10": Less than 10% feasible candidates.\n'
        '2. "10_50": Between 10% and 50% feasible candidates.\n'
        '3. "gt_50": More than 50% feasible candidates.\n'
        'Respond with a single JSON object containing a field "feasibility_bucket" '
        'set to one of: "lt_10", "10_50", "gt_50".'
    )


def render_graded_post_template(strategy_md: str, evidence: str) -> str:
    """Render the prompt template for the graded posterior probability."""
    return (
        "You are an expert computational physicist.\n"
        "Below is a proposed stellarator optimization strategy:\n"
        "---\n"
        f"{strategy_md}\n"
        "---\n"
        "We ran this strategy for one cycle and collected the following evidence:\n"
        "---\n"
        f"{evidence}\n"
        "---\n"
        "Based on both the strategy description and this evidence, estimate the fraction "
        "of feasible candidates this strategy will yield.\n"
        "Categorize the fraction into one of three buckets:\n"
        '1. "lt_10": Less than 10% feasible candidates.\n'
        '2. "10_50": Between 10% and 50% feasible candidates.\n'
        '3. "gt_50": More than 50% feasible candidates.\n'
        'Respond with a single JSON object containing a field "feasibility_bucket" '
        'set to one of: "lt_10", "10_50", "gt_50".'
    )


# --------------------------------------------------------------------------
# Mathematical KL Formulas
# --------------------------------------------------------------------------


def beta_kl(a_post: float, b_post: float, a_pre: float, b_pre: float) -> float:
    """Calculate the closed-form KL divergence between two Beta distributions.

    KL(Beta(a_post, b_post) || Beta(a_pre, b_pre))
    """
    if a_post <= 0.0 or b_post <= 0.0 or a_pre <= 0.0 or b_pre <= 0.0:
        raise DirichletDegenerateAlpha("Beta parameters must be strictly positive.")

    log_b_pre = sp.betaln(a_pre, b_pre)
    log_b_post = sp.betaln(a_post, b_post)

    psi_sum_post = sp.digamma(a_post + b_post)

    kl = (
        log_b_pre
        - log_b_post
        + (a_post - a_pre) * (sp.digamma(a_post) - psi_sum_post)
        + (b_post - b_pre) * (sp.digamma(b_post) - psi_sum_post)
    )
    return float(kl)


def dirichlet_kl(alpha_post: tuple[float, ...], alpha_pre: tuple[float, ...]) -> float:
    """Calculate the closed-form KL divergence between two Dirichlet distributions.

    KL(Dirichlet(alpha_post) || Dirichlet(alpha_pre))
    """
    if len(alpha_post) != len(alpha_pre):
        raise ValueError("alpha_post and alpha_pre vectors must have the same length.")

    for a in alpha_post:
        if a <= 0.0:
            raise DirichletDegenerateAlpha(f"alpha_post component {a} is non-positive.")
    for a in alpha_pre:
        if a <= 0.0:
            raise DirichletDegenerateAlpha(f"alpha_pre component {a} is non-positive.")

    sum_post = sum(alpha_post)
    sum_pre = sum(alpha_pre)

    log_b_pre = sum(sp.gammaln(a) for a in alpha_pre) - sp.gammaln(sum_pre)
    log_b_post = sum(sp.gammaln(a) for a in alpha_post) - sp.gammaln(sum_post)

    psi_sum_post = sp.digamma(sum_post)

    kl = log_b_pre - log_b_post
    for a_post, a_pre in zip(alpha_post, alpha_pre, strict=True):
        kl += (a_post - a_pre) * (sp.digamma(a_post) - psi_sum_post)

    return float(kl)


# --------------------------------------------------------------------------
# Polarity and Elicitation Helpers
# --------------------------------------------------------------------------


def _dominant_bucket(counts: tuple[int, int, int]) -> int | None:
    """Return the index of the unique dominant bucket, or None if tied."""
    max_val = max(counts)
    if counts.count(max_val) > 1:
        return None
    return counts.index(max_val)


async def binary_bayesian_surprise(
    strategy_md: str,
    evidence: str,
    guide_llm: GuideLLM,
    n: int = 5,
) -> float:
    """Elicit binary predictions and compute surprise via Beta KL."""
    logger.info("binary_bayesian_surprise called with n=%d", n)
    prior_q = render_prior_template(strategy_md)
    post_q = render_post_template(strategy_md, evidence)

    pre_res_raw = await asyncio.gather(
        *(guide_llm.boolean(prior_q) for _ in range(n)), return_exceptions=True
    )
    post_res_raw = await asyncio.gather(
        *(guide_llm.boolean(post_q) for _ in range(n)), return_exceptions=True
    )

    for r in pre_res_raw:
        if isinstance(r, BaseException):
            raise r
    for r in post_res_raw:
        if isinstance(r, BaseException):
            raise r

    pre_bools = [r for r in pre_res_raw if isinstance(r, bool)]
    post_bools = [r for r in post_res_raw if isinstance(r, bool)]

    if not pre_bools or not post_bools:
        raise BucketCountsEmpty(
            "Pre- or post-evidence elicitation yielded zero usable boolean responses."
        )

    k_pre = sum(1 for x in pre_bools if x)
    k_post = sum(1 for x in post_bools if x)

    n_pre = len(pre_bools)
    n_post = len(post_bools)

    a_pre, b_pre = 1 + k_pre, 1 + (n_pre - k_pre)
    a_post = 1 + k_pre + k_post
    b_post = 1 + (n_pre - k_pre) + (n_post - k_post)

    pre_mean = a_pre / (a_pre + b_pre)
    post_mean = a_post / (a_post + b_post)

    if (pre_mean - 0.5) * (post_mean - 0.5) > 0.0 or math.isclose(pre_mean, post_mean):
        return 0.0

    return beta_kl(a_post, b_post, a_pre, b_pre)


async def graded_bayesian_surprise(
    strategy_md: str,
    evidence: str,
    guide_llm: GuideLLM,
    n: int = 5,
) -> float:
    """Elicit categorical bucket predictions and compute surprise via Dirichlet KL."""
    logger.info("graded_bayesian_surprise called with n=%d", n)
    prior_q = render_graded_prior_template(strategy_md)
    post_q = render_graded_post_template(strategy_md, evidence)

    pre_res_raw = await asyncio.gather(
        *(guide_llm.feasibility_bucket(prior_q) for _ in range(n)), return_exceptions=True
    )
    post_res_raw = await asyncio.gather(
        *(guide_llm.feasibility_bucket(post_q) for _ in range(n)), return_exceptions=True
    )

    for r in pre_res_raw:
        if isinstance(r, BaseException):
            raise r
    for r in post_res_raw:
        if isinstance(r, BaseException):
            raise r

    pre_buckets = [r for r in pre_res_raw if r in ("lt_10", "10_50", "gt_50")]
    post_buckets = [r for r in post_res_raw if r in ("lt_10", "10_50", "gt_50")]

    if not pre_buckets or not post_buckets:
        raise BucketCountsEmpty(
            "Pre- or post-evidence elicitation yielded zero usable bucket responses."
        )

    pre_counts = (
        pre_buckets.count("lt_10"),
        pre_buckets.count("10_50"),
        pre_buckets.count("gt_50"),
    )
    post_counts = (
        post_buckets.count("lt_10"),
        post_buckets.count("10_50"),
        post_buckets.count("gt_50"),
    )

    pre_dom = _dominant_bucket(pre_counts)
    post_dom = _dominant_bucket(post_counts)

    if pre_dom is None or post_dom is None or pre_dom == post_dom:
        return 0.0

    alpha_pre = tuple(float(1 + c) for c in pre_counts)
    alpha_post = tuple(float(1 + cp + co) for cp, co in zip(pre_counts, post_counts, strict=True))

    return dirichlet_kl(alpha_post, alpha_pre)
