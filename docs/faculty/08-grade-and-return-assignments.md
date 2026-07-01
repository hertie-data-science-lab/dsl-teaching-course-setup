# Grade and return assignments

Autograde (optional) → fold in manual marks → preview → distribute. Grades never touch a
student's assignment repo directly - each student has one private `grades-<handle>` repo,
the single home for every grade they get all course.

## Prerequisites

- An assignment [released](07-release-assignment-to-cohort.md) to the cohort.
- (optional, for autograding) The template's `solution` branch carries hidden tests and a
  `grading.yml` with `autograde: true` (scaffolded automatically when the assignment was
  [added to the course](03-add-assignment-to-course.md); set `autograde: false` there, or
  delete the file, for a purely manually-graded assignment).

## Grade

1. **Grade assignment** (skip this step entirely if `autograde: false`). Course `.github` →
   **Actions** → Grade assignment. Pins each submission to the assignment's deadline (the
   cohort's `schedule.assignments[slug]` + `grace_days` - see
   [Release assignment → Deadlines](07-release-assignment-to-cohort.md#deadlines); there is
   no separate deadline input here), runs the hidden tests, and writes the machine score into
   `classroom-config/grades/<assignment>.csv` - the `auto` column for individual assignments,
   `team_grade` for group ones. Nothing is written to a student's repo.

2. **Add manual marks.** Edit `classroom-config/grades/<assignment>.csv` directly (GitHub web
   UI is fine). Columns: `github_handle, team, auto, manual, team_grade, adjustment, final,
   comments, team_comments`.
   - `auto` / `manual` are faculty-internal working columns - the autograder's score and your
     hand mark respectively. Neither is ever shown to the student.
   - `final` is the authoritative mark the student sees - you own combining `auto`+`manual`
     into it (no automatic rounding/summing), so a purely manual assignment just has `final`
     + `comments` filled in and `auto` left blank.
   - Group assignments use `team_grade` (the shared mark, duplicated into every member's
     gradebook), that member's private `adjustment`, and `team_comments` (shared) alongside
     each member's own `final`/`comments`.

## Return

3. **Sync gradebooks.** Ensures every onboarded student has a private `grades-<handle>` repo
   (student = read). Idempotent - safe to re-run after new enrolments.

4. **Render grades (preview).** Pivots every `grades/<assignment>.csv` into one
   `gradebook/<handle>.yml` per student and opens a **single pull request** in
   `classroom-config` - that diff is the all-students-at-once preview (review it before
   merging; nothing reaches a student until the PR is merged).

5. **Distribute grades.** Run after merging the preview PR. Copies each merged gradebook into
   that student's private `grades-<handle>` repo and emails them (unless run silently).

## Next

- Nothing further for this assignment - repeat **Grade → Return** for the next one as
  deadlines pass.

---
**Demo:** grades in [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026)'s per-student
`grades-<handle>` repos.
