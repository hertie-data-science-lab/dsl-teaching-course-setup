# Grade and return assignments

Autograde (optional) → add manual marks → preview → distribute. Grades never touch a
student's assignment repo: each student has one private `grades-<handle>` repo, the single
home for every mark they get all course.

## Prerequisites

- An assignment [released](07-release-assignment-to-cohort.md) to the cohort.
- *(autograding only)* hidden tests + a `grading.yml` on the template's `solution` branch (both
  scaffolded for you). With no `solution` branch, no `grading.yml`, or `autograde: false`, step 1
  is a no-op - grade entirely by hand.
- *(emails only)* the `GRAPH_*` or `SMTP_*` secrets. Without them, step 5's email is a preview.

## 1. Grade assignment (autograde)

Course `.github` → **Actions** → **Grade assignment**: `cohort_org`, `assignment`, plus
`group` and `dry_run` (both default **off**).

There is **no deadline input** - the grading deadline is the cohort schedule's
`assignments.<slug>.due + grace_days`, and the commit graded is the one the hourly cron froze
into `classroom-config/snapshots/<slug>.csv` (see
[Release assignment → Deadlines](07-release-assignment-to-cohort.md#deadlines)). A blank sha
there means nothing was pushed by the deadline, and that scores zero.

It runs the hidden tests faculty-side, then writes into `classroom-config`:

- `grades/<slug>.csv` → the `auto` column (individual) or `team_grade` (group, one row per
  member). An upsert: columns you filled in by hand are preserved.
- `autograde/<slug>/<handle-or-team>.json` → the raw per-test result, for appeals.

Nothing is written to any student repo. Auditors are never graded.

## 2. Add your marks

Edit `classroom-config/grades/<slug>.csv` (web UI is fine). Columns:
`github_handle, team, auto, manual, team_grade, adjustment, final, comments, team_comments`.

- `auto` and `manual` are **faculty-internal** and never shown to the student.
- **`final` is what the student sees, and you own it** - nothing sums or rounds `auto` +
  `manual` for you. A hand-marked assignment just needs `final` + `comments`.
- A group project: `team_grade` (shared), that member's private `adjustment`, shared
  `team_comments`, plus each member's own `final`. No one sees another member's adjustment.

## 3. Sync gradebooks

Ensures every onboarded, enrolled student has a private `grades-<handle>` repo (student =
read). Idempotent - re-run after late enrolments. `dry_run` defaults **off**.

## 4. Render grades (preview)

Pivots every `grades/*.csv` into one `gradebook/<handle>.yml` per student and opens **one**
PR in `classroom-config` (branch `grades-update`, "Grades: review before distribution").
**That diff is the preview** - every student at once. Only `final`, `comments`, and the group
fields cross over; `auto`/`manual` never do.

It also regenerates `cohort-gradebook.csv` at the repo root - a wide, faculty-only glance view
of every column for every student. Generated, never hand-edited; the per-assignment CSVs stay
the source of truth.

Review, then **merge**. Nothing reaches a student until you do.

## 5. Distribute grades

Copies each merged gradebook to `grades-<handle>/grades.yml` and emails the student a
"your grades have been updated" link (the marks themselves aren't in the email).

**`dry_run` defaults to `true`** - it pushes nothing and sends nothing until you untick it.
`silent` pushes the grades without emailing.

## Next

- Repeat 1-5 per assignment as deadlines pass. A `grade:` entry in the schedule's
  `materials_releases` plan runs step 1 for you -
  [the schedule does the work](06-release-materials-to-cohort.md#the-schedule-does-the-work).

---
**Demo:** per-student `grades-<handle>` repos in [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026).
