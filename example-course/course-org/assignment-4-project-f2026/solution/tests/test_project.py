# HIDDEN tests - run faculty-side against each team's submission.
from starter import solve


def test_sum_second_column():
    assert solve([(1, 2), (3, 4)]) == 6


def test_empty():
    assert solve([]) == 0
