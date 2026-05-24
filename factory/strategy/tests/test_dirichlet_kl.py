# test_dirichlet_kl.py — Unit tests for dirichlet_kl function
#
# Verifies the mathematical properties, correctness, length validation,
# and degenerate parameter behavior of the Dirichlet KL divergence.

import math

import pytest

from factory.strategy.beliefs import dirichlet_kl
from factory.strategy.errors import DirichletDegenerateAlpha


def test_dirichlet_kl_identical() -> None:
    """Verifies that KL divergence between identical Dirichlet distributions is zero."""
    assert math.isclose(dirichlet_kl((1.0, 1.0, 1.0), (1.0, 1.0, 1.0)), 0.0, abs_tol=1e-9)
    assert math.isclose(dirichlet_kl((2.0, 3.0, 4.0, 5.0), (2.0, 3.0, 4.0, 5.0)), 0.0, abs_tol=1e-9)


def test_dirichlet_kl_length_mismatch() -> None:
    """Verifies that vector length mismatch raises ValueError."""
    with pytest.raises(ValueError, match="vectors must have the same length"):
        dirichlet_kl((1.0, 1.0, 1.0), (1.0, 1.0))


def test_dirichlet_kl_degenerate_raises() -> None:
    """Verifies that non-positive parameters raise DirichletDegenerateAlpha."""
    with pytest.raises(DirichletDegenerateAlpha):
        dirichlet_kl((0.0, 1.0, 1.0), (1.0, 1.0, 1.0))
    with pytest.raises(DirichletDegenerateAlpha):
        dirichlet_kl((1.0, 1.0, 1.0), (1.0, -1.0, 1.0))


def test_dirichlet_kl_value_check() -> None:
    """Verifies that dirichlet_kl matches beta_kl for 2-dimensional parameters.

    Dirichlet with 2 components is equivalent to Beta distribution.
    """
    beta_val = dirichlet_kl((2.0, 3.0), (1.0, 1.0))
    from factory.strategy.beliefs import beta_kl

    assert math.isclose(beta_val, beta_kl(2.0, 3.0, 1.0, 1.0), rel_tol=1e-9)
