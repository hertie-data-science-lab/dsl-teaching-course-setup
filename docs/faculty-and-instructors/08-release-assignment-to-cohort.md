# Release an assignment to a cohort

Freeze a cohort-level copy of an assignment template and hand out one **private repo per
student**, autograder included.

## Prerequisites

- A course [assignment template](03-add-assignment-to-course.md) with the brief + starter on `main`.
- A bootstrapped [cohort](04-new-cohort-org.md) with [students onboarded](05-enrol-students-to-cohort.md) -
  one repo is generated per onboarded student.

## The schedule normally does this

An `assignment:` entry in the cohort's `schedule.yml` `materials_releases:` plan does exactly
what the button below does, at the datetime you gave it - and keeps doing it, so a student who
onboards late gets their repo on the next hourly tick. Write the plan once:
[Schedule releases](06-schedule-releases.md).

**The button below is the manual override** - for a demo, an early or ad-hoc hand-out, or
recovery while you fix the YAML.

## Release assignment (manual)

Course `.github` → **Actions** →
[Release assignment](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/release-assignment.yml).
Two stages:

1. **Freeze** a cohort-level template repo `<slug>` from the chosen `assignment-*-fYYYY` template.
2. **Generate** one **private** `<slug>-<handle>` repo per onboarded student (student added as
   collaborator). The autograder rides along.

Other inputs, all default **off**: `include_solution` (also push the template's `solution`
branch into each student repo), `group` (one shared repo per **team** from `teams.csv` instead
of one per student - see [Enrol students → groups](05-enrol-students-to-cohort.md#group-assignments-optional)),
`dry_run` (list the repos that *would* be created).

Auditors (`role=auditor` on the roster) are skipped - read-only means no assignment repo.

## Deadlines

**One source of truth** - the **cohort's** `classroom-config/schedule.yml` `assignments:`
block, keyed by the assignment **slug** (the repo name minus `-fYYYY`/`-sYYYY`):

```yaml
assignments:
  assignment-1:
    due: 2026-10-13               # the due date students see
    grace_days: 2                 # OPTIONAL, grading-only (default 0)
                                   # autograder pins to 2026-10-15; students still see 10-13
```

- **The due date students see** (cohort site schedule + the brief's "due" event) is
  `assignments[slug].due` (23:59 that day). Edit → commit → **Sync site**. Omit it and the
  date is **synthesised** (fortnightly).
- **The grading deadline** is that **same date + `grace_days`** - there is **no separate
  deadline input** on the Grade assignment button. `grace_days` is the one knob for a quiet
  grace period: grade later than the published date without changing what students were told.
- **The commit that gets graded** is frozen for you. Shortly after the grading deadline
  passes, the hourly cron records each submission repo's HEAD into
  `classroom-config/snapshots/<slug>.csv` (`repo,sha,recorded_at`) using the **server's**
  clock - a git committer date is client-supplied, so a backdated late push would otherwise
  slip past. The file is **write-once**: later pushes can't move the pin. To deliberately
  re-freeze (e.g. repos were provisioned late), delete the CSV and the next tick rebuilds it.

## The site

Releases call **Sync site** automatically (the assignment brief appears on the cohort site).

## Next

- [Grade and return the assignment](09-grade-and-return-assignments.md).

---
**Demo:** per-student repos in [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026).
