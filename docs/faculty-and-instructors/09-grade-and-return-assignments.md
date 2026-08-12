# Grade and return assignments

Autograde (optional) → add your marks → preview → distribute. Marks land in each student's
private `grades-<handle>` repo, never in their assignment repo.

## Prerequisites

- An assignment [released](08-release-assignment-to-cohort.md) to the cohort.
- *(autograding only)* hidden tests + `grading.yml` on the template's `solution` branch. Without
  them (or with `autograde: false`), skip step 1 and grade entirely by hand.
- *(emails only)* email sending is configured centrally by the DSL team; where it isn't live
  yet, step 5's email stays a preview (the grades still reach each student's repo).

## 1. Grade assignment (autograde)

Course `.github` → **Actions** → **Grade assignment**: `cohort_org`, `assignment`, plus `group`
and `dry_run` (both default **off**). It runs the hidden tests and writes into
`classroom-config`:

- `grades/<slug>.csv` → the `auto` column (individual) or `team_grade` (group). Columns you
  filled in by hand are preserved.
- `autograde/<slug>/<handle-or-team>.json` → the raw per-test result, for appeals.

There is **no deadline input**: the deadline is the cohort schedule's
`assignments.<slug>.due + grace_days`, and the graded commit is the one frozen into
`classroom-config/snapshots/<slug>.csv` (see
[Release assignment → Deadlines](08-release-assignment-to-cohort.md#deadlines)). A blank sha
there means nothing was pushed by the deadline, and that scores zero.

> ⚠️ **No snapshot = a spoofable pin.** With no `snapshots/<slug>.csv`, grading falls back to
> git committer dates, which students control - backdated late work passes. The run log says so
> (`! no ... snapshots/<slug>.csv`). Fix: check the schedule's `assignments:` block really has a
> `due` for this slug (a malformed one is
> [silently dropped](06-schedule-releases.md#silent-failures), and the deadline then defaults to
> *today*), then let the hourly cron freeze it before you grade.

Nothing is written to any student repo. Auditors are never graded.

## 2. Add your marks

Edit `classroom-config/grades/<slug>.csv` (web UI is fine). Columns:
`github_handle, team, auto, manual, team_grade, adjustment, final, comments, team_comments`.

- `auto` and `manual` are **faculty-internal** and never shown to the student.
- **`final` is what the student sees, and you own it** - nothing sums `auto` + `manual` for you.
  A hand-marked assignment just needs `final` + `comments`.
- Group project: `team_grade` (shared), each member's private `adjustment`, shared
  `team_comments`, plus each member's own `final`. No one sees another member's adjustment.

## 3. Sync gradebooks

Gives every onboarded, enrolled student a private `grades-<handle>` repo. Re-run after late
enrolments. `dry_run` defaults **off**.

## 4. Render grades (preview)

Opens **one** PR in `classroom-config` (branch `grades-update`, "Grades: review before
distribution") with a `gradebook/<handle>.yml` per student. **That diff is the preview.** Only
`final`, `comments` and the group fields cross over; `auto`/`manual` never do. It also
regenerates the faculty-only `cohort-gradebook.csv` at the repo root.

Review, then **merge**. Nothing reaches a student until you do.

## 5. Distribute grades

Copies each merged gradebook to `grades-<handle>/grades.yml` and emails the student a "your
grades have been updated" link (no marks in the email).

**`dry_run` defaults to `true`** - it pushes nothing and sends nothing until you untick it.
`silent` pushes the grades without emailing.

## Next

- Repeat 1-5 per assignment as deadlines pass. A `grade:` entry in the schedule runs step 1 for
  you - [Schedule releases](06-schedule-releases.md).

  > ⚠️ A `grade:` entry re-runs **every hour** once its `when` has passed - the full autograder,
  > every student, every tick. Remove it from the plan once the assignment is marked.

---
**Demo:** per-student `grades-<handle>` repos in [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026).
