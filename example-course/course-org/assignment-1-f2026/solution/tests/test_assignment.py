# HIDDEN tests - run faculty-side; imports the student's submission.
from starter import solve


def test_basic_mean():
    assert solve([1, 2, 3]) == 2


def test_floats():
    assert abs(solve([1.0, 2.0]) - 1.5) < 1e-9


def test_single():
    assert solve([7]) == 7
