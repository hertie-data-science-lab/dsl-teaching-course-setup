# Add an assignment to the course org

Scaffold an assignment **template** repo, then fill in the brief, starter, and (optionally)
the model solution + autograder. One per assignment: `assignment-N-{f/s}YYYY`.

## Prerequisites

- A bootstrapped [course org](01-new-course-org.md); you're in its `instructors` / `course-admin` team.

## Steps

1. **Scaffold the template.** Course org → `.github` → **Actions** →
   [New assignment](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/new-assignment.yml), inputs `number` = `1`, `tag` = `f2026` → creates **`assignment-1-f2026`**  with two branches:

   | Branch | Holds (all stubs, for you to replace) | Who sees it |
   |--------|-------|-------------|
   | `main` | `README.md` (brief) + `starter.*` | **what students get** |
   | `solution` | `solution/` (model answer) + `grading.yml` + hidden `tests/` | **faculty & instructors only** |

   Your `instructors` team is granted **write** on it automatically, so you can push straight away.

2. **Push your content** - the real brief + starter to `main`; the model solution,
   `grading.yml` and the hidden `tests/` that **Grade assignment** runs to `solution`. Student
   repos are generated from **`main` only**; the `solution` branch is never distributed unless
   you tick `include_solution` at release time. Set `autograde: false` in `grading.yml` (or
   delete that file) for a fully hand-marked assignment.

3. **Refresh actions** so the assignment dropdowns update.

Repeat for each assignment (`number` = 2, 3, …). A group project uses the same flow - whether it
releases per-team or per-student is decided at **release** time (the `group` checkbox), not here.
`grading.yml`'s `type:` is only the autograder's fallback when that checkbox is left unticked.

> **Deadlines aren't set here.** The due date students see is **per cohort**, in that cohort's `schedule.yml` - see [Release assignment → Deadlines](07-release-assignment-to-cohort.md#deadlines).

## Next

- [Release to a cohort](07-release-assignment-to-cohort.md) - freeze + hand out per-student repos.

---
**Demo:** [`DSL-Demo-Course-E1234`](https://github.com/DSL-Demo-Course-E1234) → New assignment.
