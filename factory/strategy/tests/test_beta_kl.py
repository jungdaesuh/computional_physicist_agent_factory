# test_beta_kl.py — Unit tests for beta_kl function
#
# Verifies the mathematical properties, correctness against known analytical values,
# and degenerate parameter behavior of the Beta KL divergence.

import math

import pytest

from factory.strategy.beliefs import beta_kl
from factory.strategy.errors import DirichletDegenerateAlpha


def test_beta_kl_identical() -> None:
    """Verifies that KL divergence between identical Beta distributions is zero."""
    assert math.isclose(beta_kl(1.0, 1.0, 1.0, 1.0), 0.0, abs_tol=1e-9)
    assert math.isclose(beta_kl(2.5, 3.5, 2.5, 3.5), 0.0, abs_tol=1e-9)


def test_beta_kl_known_value() -> None:
    """Verifies beta_kl against a hand-calculated reference value.

    KL(Beta(2, 3) || Beta(1, 1)) = log B(1, 1) - log B(2, 3)
                                 + (2 - 1) * (psi(2) - psi(5))
                                 + (3 - 1) * (psi(3) - psi(5))
    Hand calculation yields approximately 0.2349066497880004.
    """
    expected = 0.2349066497880004
    actual = beta_kl(2.0, 3.0, 1.0, 1.0)
    assert math.isclose(actual, expected, rel_tol=1e-9)


def test_beta_kl_degenerate_raises() -> None:
    """Verifies that non-positive parameters raise DirichletDegenerateAlpha."""
    with pytest.raises(DirichletDegenerateAlpha):
        beta_kl(0.0, 1.0, 1.0, 1.0)
    with pytest.raises(DirichletDegenerateAlpha):
        beta_kl(1.0, -1.0, 1.0, 1.0)
    with pytest.raises(DirichletDegenerateAlpha):
        beta_kl(1.0, 1.0, 0.0, 1.0)
    with pytest.raises(DirichletDegenerateAlpha):
        beta_kl(1.0, 1.0, 1.0, -2.5)
