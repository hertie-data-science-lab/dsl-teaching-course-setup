# Grade and return assignments

Autograde (optional) → add your marks → preview → distribute. Marks land in each student's
private `grades-<handle>` repo, never in their assignment repo.

## Prerequisites

- An assignment [released](08-release-assignment-to-cohort.md) to the cohort.
- *(autograding only)* hidden tests + `grading.yml` on the template's `solution` branch. Without
  them (or with `autograde: false`), skip step 1 and grade entirely by hand.

## 1. Grade assignment (for autograde only)

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

Nothing is written to any student repo. Auditors are never graded.

## 2. Add your marks (on top of / instead of autograde)

Edit `classroom-config/grades/<slug>.csv` (directly editing via web UI is fine; otherwise edit a local copy of the repo, commit & push)

> NB: autograding via `Grade assignments` workflow already creates `classroom-config/grades/<slug>.csv` to edit; otherwise you will need to create your own??? OR is there a scaffold already there?????

| Column | You fill? | The student sees it? | What it's for |
|--------|-----------|----------------------|---------------|
| `github_handle` | no - roster | - | which student the row is |
| `team` | no - autograder | yes (group only) | their team, on group assignments |
| `auto` | no - autograder | **no** | the machine score |
| `manual` | yes | **no** | your hand-marked part - a working column |
| `team_grade` | yes (group) | yes | the shared team mark |
| `adjustment` | yes (group) | only their own | that member's individual adjustment |
| `final` | **yes** | **yes** | **the mark. Nothing computes it for you** |
| `comments` | yes | yes | feedback for that student |
| `team_comments` | yes (group) | yes | feedback shared with the whole team |

- **For group projects**:
  - `team_grade` (shared), each member's private `adjustment`, shared
  `team_comments`, plus each member's own `final`.
  - No one sees another member's adjustment.
- **For no-autograde**: A hand-marked assignment just needs `final` + `comments`.
- `auto` and `manual` are faculty-internal and never shown to the student.
- `final` is what the student sees, and you own it - nothing sums `auto` + `manual` for you.
- Values stay as you type them - a letter, a percentage, `+4` - nothing is coerced or rounded.

## 3. Sync gradebooks
- IS THIS A WORKFLOW TO BE RUN? IF SO GIVE DIRECTIONS
- Gives every onboarded, enrolled student a private `grades-<handle>` repo.
- Re-run after late enrolments.
- `dry_run` defaults **off**.

## 4. Render grades (preview)
- IS THIS A WORKFLOW TO BE RUN? IF SO GIVE DIRECTIONS
- Opens **one** PR in `classroom-config` (branch `grades-update`, "Grades: review before
distribution") with a `gradebook/<handle>.yml` per student.
- **That diff is the preview.**
  - Only `final`, `comments` and the group fields cross over into the students' (what????)
  - `auto`/`manual` never do.
  - It also regenerates the faculty-only `cohort-gradebook.csv` at the repo root.
  - CHECK ACTUAL CODE THAT ALL OF THIS IS CORRECTLY SETUP TO BE PRIVATE / PUBLIC ETC
- Review, then **merge**. Nothing reaches a student until you do.

## 5. Distribute grades
- IS THIS A WORKFLOW TO BE RUN? IF SO GIVE DIRECTIONS
Copies each merged gradebook to `grades-<handle>/grades.yml` and emails the student a "your grades have been updated" link (no marks in the email). 

> *NB: the automated email functionality is configured centrally by the DSL team; if/when it isn't live, the grades still reach each student's repo, but no email notification will be dispatched.

**`dry_run` defaults to `true`** - it pushes nothing and sends nothing until you untick it.
`silent` pushes the grades without emailing.

## Next

- Repeat 1-5 per assignment as deadlines pass. A `grade:` entry in the schedule runs step 1 for
  you - [Schedule releases](06-schedule-releases.md).

  > ⚠️ A `grade:` entry re-runs **every hour** once its `when` has passed - the full autograder,
  > every student, every tick. Remove it from the plan once the assignment is marked. WHAT DOES THIS MEAN???? CAN WE REMOVE THIS? DO THEY REALLY NEED TO REMOVE IT?? CAN THEY NOT JUST FIRE ONCE OR SOEMTHING? ??

---
**Demo:** per-student `grades-<handle>` repos in [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026).
