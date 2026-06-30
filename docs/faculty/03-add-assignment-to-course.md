# Add an assignment to the course org

Scaffold an assignment **template** repo, then fill in the brief, starter, and (optionally)
the model solution + autograder. One per assignment: `assignment-N-{f/s}YYYY`.

## Prerequisites

- A bootstrapped [course org](01-new-course-org.md); you're in its `instructors` / `course-admin` team.

## Steps

1. **Scaffold the template.** Course org → `.github` → **Actions** →
   [New assignment](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/new-assignment.yml), inputs `number` = `1`, `tag` = `f2026` → creates **`assignment-1-f2026`**  with two branches:

   | Branch | Holds | Who sees it |
   |--------|-------|-------------|
   | `main` | `README.md` (brief) + `starter.*` | **what students get** |
   | `solution` | `solution/` (model answer) + `grading.yml` + hidden `tests/` | **faculty only** |

   Your `instructors` team is granted **write** on it automatically, so you can push straight away.

2. **Push your content.**
   - to **`main`**: the real brief (`README.md`) + starter (`starter.py`, a notebook, …).
   - to **`solution`**: the model solution, `grading.yml`, and the hidden `tests/` that the **`Grade assignment`** workflow runs after the deadline.

   Student repos are generated within the cohort org from **`main` only** - the `solution` branch is never distributed (unless you tick `include_solution` at release time).

3. **Refresh actions** so the assignment dropdowns update.
4. **Run the workflow**.

Repeat for each assignment (`number` = 2, 3, …). A group project uses the same flow with`type: group` in its `grading.yml`.

> **Deadlines aren't set here.** The due date students see is **per cohort** (it changes each year), set in the cohort's `schedule:` block - see [Release assignment → Deadlines](07-release-assignment-to-cohort.md#deadlines).

## Next

- [Release to a cohort](07-release-assignment-to-cohort.md) - freeze + hand out per-student repos.

---
**Demo:** [`DSL-Demo-Course-E1234`](https://github.com/DSL-Demo-Course-E1234) → New assignment.
