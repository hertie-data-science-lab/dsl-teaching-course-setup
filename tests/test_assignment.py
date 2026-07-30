"""HIDDEN tests for Assignment 1 - run faculty-side, never shipped to students.

They import the submitted module (`starter.py` at the repository root) and are deliberately
standard-library only: the grading runner installs pytest and nbconvert, nothing else.

Ten test cases, one mark each (grading.yml: max_auto: 10).
"""

import pytest

from starter import (
    fit_linear_regression,
    predict,
    r_squared,
    solve_linear_system,
)

TOL = 1e-6

# The twelve flats from the lectures: area, distance to metro -> rent.
HOUSING_X = [[32, 0.3], [45, 0.9], [52, 0.4], [60, 1.6], [68, 0.7], [75, 2.1],
             [80, 1.1], [95, 0.5], [38, 1.8], [55, 0.6], [110, 1.4], [48, 2.6]]
HOUSING_Y = [540, 510, 640, 545, 720, 620, 770, 860, 420, 640, 930, 400]


def rss(X, y, beta):
    return sum((yi - yh) ** 2 for yi, yh in zip(y, predict(X, beta)))


# --------------------------------------------------------------- solve_linear_system


def test_solve_two_by_two():
    """2x + y = 5, x - y = 1  ->  x = 2, y = 1."""
    z = solve_linear_system([[2.0, 1.0], [1.0, -1.0]], [5.0, 1.0])
    assert z == pytest.approx([2.0, 1.0], abs=TOL)


def test_solve_requires_pivoting():
    """A zero leading entry: solvable, but only if the rows are swapped first."""
    A = [[0.0, 2.0, 1.0], [1.0, 1.0, 1.0], [2.0, 1.0, 0.0]]
    b = [5.0, 6.0, 5.0]
    z = solve_linear_system(A, b)
    for row, rhs in zip(A, b):
        assert sum(a * zi for a, zi in zip(row, z)) == pytest.approx(rhs, abs=1e-6)


def test_solve_rejects_singular():
    """Duplicated rows have no unique solution: raise ValueError, as the stub documents."""
    with pytest.raises(ValueError):
        solve_linear_system([[1.0, 2.0], [2.0, 4.0]], [3.0, 6.0])


# ------------------------------------------------------------ exact recovery


def test_recovers_exact_line():
    """Noiseless y = 3 + 2x must be recovered exactly."""
    X = [[0], [1], [2], [3], [4]]
    y = [3 + 2 * row[0] for row in X]
    assert fit_linear_regression(X, y) == pytest.approx([3.0, 2.0], abs=TOL)


def test_recovers_exact_plane_with_negative_slope():
    """Two features, one negative coefficient: y = 10 + 4*x1 - 3*x2."""
    X = [[1, 2], [2, 1], [3, 5], [4, 3], [5, 8], [6, 4]]
    y = [10 + 4 * a - 3 * b for a, b in X]
    assert fit_linear_regression(X, y) == pytest.approx([10.0, 4.0, -3.0], abs=1e-5)


# ------------------------------------------------- the defining properties of OLS


def test_residuals_sum_to_zero():
    """An intercept in the model forces the residuals to sum to zero."""
    beta = fit_linear_regression(HOUSING_X, HOUSING_Y)
    resid = [yi - yh for yi, yh in zip(HOUSING_Y, predict(HOUSING_X, beta))]
    assert sum(resid) == pytest.approx(0.0, abs=1e-6)


def test_residuals_orthogonal_to_each_feature():
    """Least squares projects y onto the column space, so residuals are orthogonal to it."""
    beta = fit_linear_regression(HOUSING_X, HOUSING_Y)
    resid = [yi - yh for yi, yh in zip(HOUSING_Y, predict(HOUSING_X, beta))]
    for j in range(len(HOUSING_X[0])):
        dot = sum(r * row[j] for r, row in zip(resid, HOUSING_X))
        assert dot == pytest.approx(0.0, abs=1e-5)


def test_no_perturbation_lowers_the_rss():
    """It is a MINIMISER: nudging any coefficient in either direction must not improve it."""
    beta = fit_linear_regression(HOUSING_X, HOUSING_Y)
    best = rss(HOUSING_X, HOUSING_Y, beta)
    for j in range(len(beta)):
        for step in (-1.0, -0.1, 0.1, 1.0):
            nudged = list(beta)
            nudged[j] += step
            assert rss(HOUSING_X, HOUSING_Y, nudged) >= best - 1e-9


# ------------------------------------------------------------------ r_squared


def test_r_squared_boundaries():
    """1.0 for a perfect fit, 0.0 for predicting the mean."""
    y = [1.0, 2.0, 3.0, 4.0]
    assert r_squared(y, y) == pytest.approx(1.0, abs=TOL)
    assert r_squared(y, [2.5] * 4) == pytest.approx(0.0, abs=TOL)


def test_r_squared_goes_negative():
    """Worse than the mean must give a NEGATIVE value, not zero and not an error."""
    y = [1.0, 2.0, 3.0, 4.0]
    assert r_squared(y, [10.0, -5.0, 12.0, -3.0]) < 0.0
