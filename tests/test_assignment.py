"""HIDDEN tests for Assignment 2 - run faculty-side, never shipped to students.

The grading runner converts every notebook in the submission to a script with `nbconvert`,
so `starter.ipynb` becomes an importable `starter` module. Standard library only: the runner
installs pytest and nbconvert, nothing else.

Eight test cases, one mark each (grading.yml: max_auto: 8).
"""

import math

import pytest

from starter import (
    choose_threshold,
    confusion_counts,
    fit_logistic,
    log_loss,
    precision_recall_f1,
    predict_proba,
    sigmoid,
)

# The same 24 applications the notebook uses.
X = [
    [1.2, -0.4], [0.3, 0.9], [-0.8, 1.6], [2.1, -1.1], [-1.4, 0.2], [0.7, 0.5],
    [-0.2, -0.9], [1.8, 0.3], [-1.1, 1.2], [0.9, -1.4], [-0.5, 0.7], [1.5, 1.1],
    [-1.7, -0.3], [0.4, 1.8], [1.1, -0.7], [-0.9, -1.2], [2.3, 0.6], [-0.3, 1.4],
    [0.6, -0.2], [-1.2, 0.9], [1.4, -1.6], [-0.7, 0.4], [0.2, 1.3], [1.9, -0.9],
]
Y = [0, 1, 1, 0, 1, 0, 0, 0, 1, 0, 1, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 0]


def test_sigmoid_values_and_stability():
    """Midpoint, monotonicity, and no OverflowError at either extreme."""
    assert sigmoid(0) == pytest.approx(0.5, abs=1e-12)
    assert sigmoid(1) == pytest.approx(1 / (1 + math.exp(-1)), abs=1e-12)
    assert sigmoid(-1) < sigmoid(0) < sigmoid(1)
    assert 0.0 <= sigmoid(-1000) < 1e-300 or sigmoid(-1000) == 0.0
    assert sigmoid(1000) == pytest.approx(1.0, abs=1e-12)


def test_log_loss_known_value():
    """Coin-flip probabilities give exactly log 2, whatever the labels."""
    assert log_loss([1, 0], [0.5, 0.5]) == pytest.approx(math.log(2), abs=1e-9)
    assert log_loss([1, 1, 1], [1.0, 1.0, 1.0]) == pytest.approx(0.0, abs=1e-9)


def test_log_loss_punishes_confident_errors():
    """Confidently wrong must cost far more than merely uncertain, and stay finite."""
    uncertain = log_loss([1], [0.45])
    wrong = log_loss([1], [0.01])
    assert wrong > 3 * uncertain
    assert math.isfinite(log_loss([1, 0], [0.0, 1.0]))   # clipping, not log(0)


def test_predict_proba_uses_intercept_first():
    """beta = [intercept, b1, b2]; a zero row must return sigmoid(intercept)."""
    probs = predict_proba([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], [0.5, 2.0, -3.0])
    assert probs[0] == pytest.approx(sigmoid(0.5), abs=1e-12)
    assert probs[1] == pytest.approx(sigmoid(2.5), abs=1e-12)
    assert probs[2] == pytest.approx(sigmoid(-2.5), abs=1e-12)


def test_fit_logistic_reduces_the_loss():
    """Descent must beat the all-zero starting point (log 2) by a clear margin."""
    beta = fit_logistic(X, Y)
    assert len(beta) == 3
    fitted = log_loss(Y, predict_proba(X, beta))
    assert fitted < math.log(2) - 0.05


def test_fit_logistic_recovers_the_signs():
    """Separable data: y = 1 whenever x1 - x2 < 0, so b1 < 0 < b2."""
    Xs = [[a, b] for a in (-2.0, -1.0, 0.0, 1.0, 2.0) for b in (-2.0, -1.0, 1.0, 2.0)]
    ys = [1 if a - b < 0 else 0 for a, b in Xs]
    beta = fit_logistic(Xs, ys, alpha=0.5, n_iter=3000)
    assert beta[1] < 0 < beta[2]


def test_confusion_and_metrics():
    """Hand-checked: tp=2, fp=1, tn=2, fn=1 -> precision 2/3, recall 2/3, f1 2/3."""
    y_true = [1, 1, 0, 0, 0, 1]
    y_pred = [1, 1, 1, 0, 0, 0]
    assert confusion_counts(y_true, y_pred) == (2, 1, 2, 1)
    precision, recall, f1 = precision_recall_f1(y_true, y_pred)
    assert (precision, recall, f1) == pytest.approx((2 / 3, 2 / 3, 2 / 3), abs=1e-9)

    # Flagging nothing must give zeros, not a ZeroDivisionError.
    assert precision_recall_f1([1, 0], [0, 0]) == pytest.approx((0.0, 0.0, 0.0), abs=1e-12)


def test_choose_threshold_follows_the_costs():
    """An expensive false negative pulls the threshold DOWN; an expensive FP pushes it up."""
    probs = [0.1, 0.25, 0.4, 0.55, 0.7, 0.85]
    y_true = [0, 0, 1, 0, 1, 1]
    low, low_cost = choose_threshold(y_true, probs, cost_fn=20, cost_fp=1)
    high, _ = choose_threshold(y_true, probs, cost_fn=1, cost_fp=20)
    assert low < high
    assert low_cost >= 0
    # With FN 20x FP, catching every positive is worth two false alarms.
    labels = [1 if p >= low else 0 for p in probs]
    assert sum(1 for a, p in zip(y_true, labels) if a == 1 and p == 0) == 0
