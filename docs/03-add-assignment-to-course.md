# Add an assignment to the course org

Scaffold an assignment **template** repo, then fill in the brief, starter, and (optionally)
the model solution + autograder. One per assignment: `assignment-N-{f/s}YYYY`.

## Prerequisites

- A bootstrapped [course org](01-new-course-org.md) and push access on its content repos - see
  [Add materials → Prerequisites](02-add-materials-to-course.md#prerequisites).

## Steps

Live example: [`example-course/course-org/assignment-1-f2026/`](../example-course/course-org/assignment-1-f2026).

1. **Scaffold the template.** Course org → `.github` → **Actions** →
   [New assignment](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/new-assignment.yml),
   inputs `number` = `1`, `tag` = `f2026`, plus `format` (`py` starter script or `notebook`)
   and `type` (`individual` or `group` - one repo per student vs per team) → creates
   **`assignment-1-f2026`** with two branches of stubs for you to replace:

   | Branch | Holds | Who sees it |
   |--------|-------|-------------|
   | `main` | `README.md` (brief) + `starter.*` | **what students get** |
   | `solution` | `solution/` (model answer) + `grading.yml` + hidden `tests/` | **faculty & instructors only** |

2. **Push your content** - brief + starter to `main`; model solution, `grading.yml` and the
   hidden `tests/` to `solution`. Student repos are generated from **`main` only**, unless you
   tick `include_solution` at release time. For a hand-marked assignment, set
   `autograde: false` in `grading.yml` (or delete the file).

3. **Run Refresh actions** so the assignment dropdowns update.

Repeat for each assignment (`number` = 2, 3, …). A group project is the same flow with
`type` = `group`: the choice is recorded in the solution branch's `grading.yml`, and both
handout and grading then run per team automatically (the release/grade buttons' `group`
checkbox only force-overrides a template that doesn't declare it). Change your mind later by
editing `grading.yml`.

> **Deadlines aren't set here.** The due date students see is **per cohort**, in that cohort's `schedule.yml` - see [Release assignment → Deadlines](08-release-assignment-to-cohort.md#deadlines).

## Next

- [Schedule the hand-out](06-schedule-releases.md) - the normal way to get it to students.
- [Release to a cohort](08-release-assignment-to-cohort.md) - freeze + hand out per-student repos by hand.

---
**Demo:** [`DSL-Demo-Course-E1234`](https://github.com/DSL-Demo-Course-E1234) → New assignment.
