"""Model solution for Assignment 1 - linear regression from scratch.

Standard library only. This is the file students' `starter.py` is compared against; the
hidden tests in ../tests/ import the same four names from whichever module is present.
"""


def solve_linear_system(A, b):
    """Solve `A z = b` by Gaussian elimination with partial pivoting."""
    n = len(A)
    # Work on a copy of the augmented matrix so the caller's data is untouched.
    M = [list(map(float, row)) + [float(rhs)] for row, rhs in zip(A, b)]

    for col in range(n):
        # Partial pivoting: the largest available |value| in this column becomes the pivot.
        # Without it, a small pivot divides the whole row and amplifies rounding error.
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-12:
            raise ValueError("matrix is singular - no unique solution")
        M[col], M[pivot] = M[pivot], M[col]

        for row in range(col + 1, n):
            factor = M[row][col] / M[col][col]
            if factor == 0.0:
                continue
            for k in range(col, n + 1):
                M[row][k] -= factor * M[col][k]

    # Back-substitution.
    z = [0.0] * n
    for row in reversed(range(n)):
        total = M[row][n] - sum(M[row][k] * z[k] for k in range(row + 1, n))
        z[row] = total / M[row][row]
    return z


def fit_linear_regression(X, y):
    """Ordinary least squares via the normal equations, intercept first."""
    if not X or len(X) != len(y):
        raise ValueError("X and y must be non-empty and of equal length")

    design = [[1.0] + [float(v) for v in row] for row in X]  # prepend the intercept column
    p = len(design[0])

    # X'X and X'y, accumulated directly - no inversion anywhere.
    xtx = [[sum(row[i] * row[j] for row in design) for j in range(p)] for i in range(p)]
    xty = [sum(row[i] * yi for row, yi in zip(design, y)) for i in range(p)]
    return solve_linear_system(xtx, xty)


def predict(X, beta):
    """Fitted values: the intercept plus the dot product of each row with the slopes."""
    return [beta[0] + sum(b * v for b, v in zip(beta[1:], row)) for row in X]


def r_squared(y_true, y_pred):
    """1 - RSS/TSS. Negative when the model is worse than predicting the mean."""
    mean_y = sum(y_true) / len(y_true)
    rss = sum((a - p) ** 2 for a, p in zip(y_true, y_pred))
    tss = sum((a - mean_y) ** 2 for a in y_true)
    if tss == 0.0:
        raise ValueError("y_true has zero variance - R-squared is undefined")
    return 1.0 - rss / tss


if __name__ == "__main__":
    X = [[32], [45], [52], [60], [68], [75], [80], [95]]
    y = [540, 510, 640, 545, 720, 620, 770, 860]
    beta = fit_linear_regression(X, y)
    print("coefficients:", [round(b, 4) for b in beta])
    print("R-squared:", round(r_squared(y, predict(X, beta)), 4))


# ----------------------------------------------------------------------------------
# SHORT ANSWERS (the model answers, for marking)
#
# 1. Partial pivoting swaps the row with the largest absolute value in the current column
#    into the pivot position before eliminating. Elimination divides by the pivot, so a
#    pivot that is small relative to the other entries multiplies existing rounding error
#    by a large factor, and that error then propagates through every subsequent row and
#    through back-substitution. Without pivoting the algorithm also fails outright on a
#    perfectly solvable system whose leading entry happens to be exactly zero - the
#    division is by zero even though a unique solution exists. Pivoting costs one scan per
#    column and bounds the growth factor, which is why every production solver does it.
#
# 2. `area_in_sqft` is an exact multiple of `area_in_sqm`, so one column of the design
#    matrix is a linear combination of another and X has linearly dependent columns. Then
#    X'X is singular: its determinant is zero, no inverse exists, and infinitely many
#    coefficient vectors give exactly the same fitted values, so the estimator is not
#    identified. Numerically the elimination hits a pivot at machine-epsilon scale and
#    either raises or returns wild coefficients that are meaningless individually. The fix
#    is to drop one of the two columns - they carry identical information - or, if the
#    collinearity is approximate rather than exact, to regularise (ridge adds lambda*I to
#    X'X, which restores invertibility) and to report that the individual coefficients are
#    not separately interpretable.
# ----------------------------------------------------------------------------------
