# Grade and return assignments

> **This workflow is a prototype - and entirely optional.** It works best where parts of the
> grading are automatable (hidden tests against code submissions). If it doesn't suit how you
> plan to grade your course, skip it and grade as you always have. Feedback is very welcome,
> and we're happy to customise it to your course's needs - just get in touch with the DSL team.

Autograde (optional) → add your marks → preview → distribute. Marks land in each student's
private `grades-<handle>` repo, never in their assignment repo.

## Prerequisites

- An assignment [released](08-release-assignment-to-cohort.md) to the cohort.
- *(autograding only)* hidden tests + `grading.yml` on the template's `solution` branch. Without
  them (or with `autograde: false`), skip step 1 and grade entirely by hand.

## 1. Grade assignment (for autograde only)

**This runs itself.** At each assignment's grading deadline the hourly cron autogrades it
**once** - no `grade:` entry, no button press. Use the button only for a deliberate re-grade.

Course `.github` → **Actions** → **Grade assignment**: `cohort_org`, `assignment`, plus `group`
and `dry_run` (both default **off**). It runs the hidden tests and writes into
`classroom-config`:

- `grades/<slug>.csv` → the `auto` column (individual) or `team_grade` (group). **Write-once:**
  a cell that already holds a value is never overwritten - re-running fills empty cells only,
  so your hand-edits stand. For fresh machine scores, blank those cells first.
- `autograde/<slug>/<handle-or-team>.json` → the raw per-test result, for appeals. This folder
  is also the **fire-once marker**: while it exists the cron will not grade this assignment
  again. Delete it to let the next hourly tick re-grade.

There is **no deadline input**: the deadline is the cohort schedule's
`assignments.<slug>.grading_deadline` (default: the `due` date), and the graded commit is the one frozen into
`classroom-config/snapshots/<slug>.csv` (see
[Release assignment → Deadlines](08-release-assignment-to-cohort.md#deadlines)). A blank sha
there means nothing was pushed by the deadline, and that scores zero.

Nothing is written to any student repo. Auditors are never graded.

## 2. Add your marks (on top of / instead of autograde)

Live example: [`example-course/cohort-org/grades/assignment-1.csv`](../../example-course/cohort-org/grades/assignment-1.csv).

Edit `classroom-config/grades/<slug>.csv` (directly editing via web UI is fine; otherwise edit a local copy of the repo, commit & push)

> **Where does the CSV come from?** Step 1 creates it. If you're not autograding, create it
> yourself: `classroom-config/grades/<slug>.csv` (the folder is seeded empty), with the header
> row below and one row per student handle. Any column you leave out is treated as blank.

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

Course `.github` → **Actions** → **Sync gradebooks**: pick `cohort_org`, plus `dry_run`
(defaults **off**).

- Gives every onboarded, enrolled student a **private** `grades-<handle>` repo, with that
  student added as a read-only collaborator. Auditors get none.
- Idempotent - re-run after late enrolments.

## 4. Render grades (preview)

Course `.github` → **Actions** → **Render grades (preview)**: pick `cohort_org`. No other
inputs - it never sends anything.

- Opens **one** PR in `classroom-config` (branch `grades-update`, "Grades: review before
  distribution") holding a `gradebook/<handle>.yml` per student - what that student will
  receive in step 5.
- **That diff is the preview.** Only `final`, `comments` and, for group work, `team`,
  `team_grade`, that member's own `adjustment` and `team_comments` are copied into a student's
  file. `auto` and `manual` never are.
- It also regenerates `cohort-gradebook.csv` at the repo root - a wide all-students view for
  you, which stays in `classroom-config` and is never distributed.
- Review, then **merge**. Nothing reaches a student until you do.

> **Everything here is private.** `classroom-config` and every `grades-<handle>` repo are
> private; a student is a read-only collaborator on their own gradebook repo and has no access
> to `classroom-config`, so they can't see the source CSVs, the preview PR, or anyone else's
> marks.

## 5. Distribute grades

Course `.github` → **Actions** → **Distribute grades**: pick `cohort_org`, plus `dry_run` and
`silent`. Run it **after merging step 4's PR** - it distributes what was merged.

Copies each merged gradebook to `grades-<handle>/grades.yml` and emails the student a "your grades have been updated" link (no marks in the email). 

> *NB: the automated email functionality is configured centrally by the DSL team; if/when it isn't live, the grades still reach each student's repo, but no email notification will be dispatched.

**`dry_run` defaults to `true`** - it pushes nothing and sends nothing until you untick it.
`silent` pushes the grades without emailing.

## Next

- Repeat 2-5 per assignment as deadlines pass. Step 1 has already run itself -
  [Schedule releases](06-schedule-releases.md).

  > ℹ️ **Autograding fires once**, at each assignment's grading deadline, and never again -
  > the `autograde/<slug>/` folder is the marker. To re-grade: delete that folder (the next
  > hourly tick regrades) or press **Grade assignment**. Either way, clear the `auto` /
  > `team_grade` cells you want recomputed first - they are write-once and are otherwise left
  > exactly as you left them.

---
**Demo:** per-student `grades-<handle>` repos in [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026).
