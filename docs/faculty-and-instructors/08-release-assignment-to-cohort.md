# Release an assignment to a cohort

Hand out one **private repo per student** from an assignment template, autograder included.

## Prerequisites

- A course [assignment template](03-add-assignment-to-course.md) with the brief + starter on `main`.
- A bootstrapped [cohort](04-new-cohort-org.md) with [students onboarded](05-enrol-students-to-cohort.md) -
  one repo is generated per onboarded student.

## The schedule normally does this

An `assignment:` entry in the cohort's `schedule.yml` hands out the same repos at the datetime
you give it, and keeps doing it - so a student who onboards late still gets their repo:
[Schedule releases](06-schedule-releases.md). Use the button for a demo, an ad-hoc hand-out, or
recovery while you fix the YAML.

## Release assignment (manual)

Course `.github` → **Actions** →
[Release assignment](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/release-assignment.yml).
It freezes a cohort-level copy `<slug>` of the chosen `assignment-*-fYYYY` template, then
creates one **private** `<slug>-<handle>` repo per onboarded student, with that student as
collaborator.

Other inputs, all default **off**: `include_solution` (also push the template's `solution`
branch into each student repo), `group` (one shared repo per **team** from `teams.csv` instead
of one per student - see [Enrol students → groups](05-enrol-students-to-cohort.md#group-assignments-optional)),
`dry_run` (list the repos that *would* be created).

Auditors (`role=auditor`) are skipped. The assignment brief appears on the cohort site
automatically.

## Deadlines

Set in the **cohort's** `classroom-config/schedule.yml`, keyed by the assignment **slug** (the
repo name minus `-fYYYY`/`-sYYYY`):

```yaml
assignments:
  assignment-1:
    due: 2026-10-13               # the due date students see
    grading_deadline: 2026-10-15  # OPTIONAL, grading-only - snapshot + autograde fire here
    grace_days: 2                 # LEGACY alternative: grading deadline = due + N days
```

- **The date students see** (cohort site + the brief's "due" event) is `assignments[slug].due`
  (23:59 that day). Edit → commit → **Sync site**. Omit it and a date is synthesised
  (fortnightly).
- **The grading deadline** is `grading_deadline` if set, else `due + grace_days`, else `due` -
  there is **no deadline input** on the Grade assignment button. Set it to grade later than
  the date students were told, without changing that date.
- **Autograding fires there, once.** At that moment the hourly cron freezes the snapshot and
  runs the autograder - no `grade:` entry needed. It never re-runs; delete
  `classroom-config/autograde/<slug>/` to re-grade.
- **The commit graded** is frozen for you shortly after the grading deadline passes, into
  `classroom-config/snapshots/<slug>.csv`. It is **write-once** - later pushes can't move the
  pin. To deliberately re-freeze (e.g. repos provisioned late), delete the CSV and the next
  hourly tick rebuilds it.

## Next

- [Grade and return the assignment](09-grade-and-return-assignments.md).

---
**Demo:** per-student repos in [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026).
