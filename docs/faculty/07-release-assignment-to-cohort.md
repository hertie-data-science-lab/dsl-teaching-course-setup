# Release an assignment to a cohort

Freeze a cohort-level copy of an assignment template and hand out one **private repo per
student**, autograder included.

## Prerequisites

- A course [assignment template](03-add-assignment-to-course.md) with the brief + starter on `main`.
- A bootstrapped [cohort](04-new-cohort-org.md) with [students onboarded](05-enrol-students-to-cohort.md) -
  one repo is generated per onboarded student.

## Release assignment

Course `.github` → **Actions** →
[Release assignment](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/release-assignment.yml).
Two stages:

1. **Freeze** a cohort-level template repo `<slug>` from the chosen `assignment-*-fYYYY` template.
2. **Generate** one **private** `<slug>-<handle>` repo per onboarded student (student added as
   collaborator). The autograder rides along.

`include_solution` pushes the template's `solution` branch into each student repo (default off).

> Group projects (`grading.yml` `type: group`) release one shared repo per **team** instead of
> per student - see [Enrol students → groups](05-enrol-students-to-cohort.md#group-assignments-optional).

## Deadlines

**One source of truth** - the **cohort's** `.github/dsl-course.yml` `schedule:` block, keyed by
the assignment **slug** (the repo name minus `-fYYYY`/`-sYYYY`):

```yaml
schedule:
  assignments:
    assignment-1: 2026-10-13     # the due date students see
  grace_days:                    # OPTIONAL, grading-only (default 0)
    assignment-1: 2              # autograder pins to 2026-10-15; students still see 10-13
```

- **The due date students see** (cohort site schedule + the brief's "due" event) is
  `schedule.assignments[slug]` (23:59 that day). Edit → commit → **Sync site**. Omit it and the
  date is **synthesised** (fortnightly).
- **The grading pin** (which commit the autograder marks) is that **same date + `grace_days`** -
  there is **no separate deadline input** on the Grade assignment button. `grace_days` is the one
  knob for a quiet grace period: grade later than the published date without changing what
  students were told.

## The site

Releases call **Sync site** automatically (the assignment brief appears on the cohort site).

## Next

- Grading: **Grade assignment** → **Sync gradebooks** → **Render grades** → **Distribute
  grades**. The grade contract (`classroom-config/grades/<assignment>.csv`) is in
  [required-input-schema.md](required-input-schema.md).

---
**Demo:** per-student repos in [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026).
