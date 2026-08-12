# Release an assignment to a cohort

> Releases assignments templates from the course org (hidden historical registry of course assignments) -> cohort org (a private repo, assigned to students/groups to complete and submit)

Hand out one **private repo per student** from an assignment template, optional autograder included.

## Prerequisites

- A course org level [assignment template](03-add-assignment-to-course.md) with the brief + starter on `main`.
- A bootstrapped [cohort org](04-new-cohort-org.md) with [students onboarded](05-enrol-students-to-cohort.md) - one repo is generated per onboarded student/group.

## The schedule normally does this (recommended)

A `handout:` datetime under `assignments.<slug>` in the cohort's `schedule.yml` hands out the
same repos automatically - the assignment's whole lifecycle (handout, due date, grading
deadline, team-size cap) sits in one block: [Schedule releases](06-schedule-releases.md).
This is the recommended method for releasing assignments, as the assignment also appears on
the deployed `<course>.github.io` site, so students can clearly understand the course plan in
advance.


## Release assignment via manual dispatch


In the course org, use either (1) the **materials repo's own** `Release materials` button (it knows that repo's sections and
sessions), or (2) the **course org's`.github` repo's** `release materials` button 

e.g. → [Release materials](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/release-materials.yml):



In the course org's `.github` → **Actions** → **Release assignment** (e.g. ([Release assignment](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/release-assignment.yml)).
- It freezes a cohort-level copy `<slug>` of the chosen `assignment-*-fYYYY` template
- then it creates one **private** `<slug>-<handle>` repo per onboarded student/group, with that student as
collaborator.

Other inputs, all default **off**: 
- `include_solution` (also push the template's `solution`
branch into each student repo)
- `group` (**force** one shared repo per **team** from `teams.csv`. Normally unneeded: an
assignment declared `type: group` - in the cohort's `schedule.yml` (`assignments.<slug>.type`,
which wins) or the template's `grading.yml` (fallback) - provisions per team without the tick;
see [Enrol students → groups](05-enrol-students-to-cohort.md#group-assignments))
- `dry_run` (list the repos that *would* be created).

Auditors (`role=auditor`) are skipped. The assignment brief appears on the cohort site automatically.

## Group or individual? How it's decided

One resolution, used identically by handout (scheduled and manual) and grading:

1. **The cohort's `schedule.yml`** - `assignments.<slug>.type: group | individual` - wins.
   This is the cohort-level say: the same template can even run group one year and
   individual the next, without touching the template.
2. Else **the template's `grading.yml`** (`type:` on its `solution` branch) - the
   design-time default, written by the **New assignment** button's `type` input.
3. Else **individual**.

`group` = one shared repo per team from `teams.csv` (repo `<slug>-<team>`, every member a
collaborator), graded per team into each member's `team`/`team_grade` columns.
`individual` = one private repo per onboarded, enrolled student (`<slug>-<handle>`),
graded into `auto`. The resolution is read-side only - a cohort's declaration never
writes back into the course org - and the release/grade buttons' `group` checkbox is a
last-resort force-override for a template that declares nothing.

## Group assignments: creating the teams

Live example: [`example-course/cohort-org/teams.csv`](../example-course/cohort-org/teams.csv).

Teams must exist **before** you release a group assignment. Two ways to form them - both end
up in `classroom-config/teams.csv` (`assignment, team, github_handle`), and **Sync membership**
turns each into a GitHub team on push:

- **Instructor-allocated**: you edit `teams.csv` directly - add one row per member.
- **Student self-service**: students open a **Join team** issue in the cohort's `welcome` repo
  (capped per assignment by `max_team_size` under `assignments:` in `schedule.yml`, default 5)
  and name their team; the workflow writes the row for them (team size is capped).

The release then grants each team its one shared repo. Full flow:
[Enrol students → groups](05-enrol-students-to-cohort.md#group-assignments).

## Deadlines

Set in the **cohort's** `classroom-config/schedule.yml`, keyed by the assignment **slug** (the
repo name minus `-fYYYY`/`-sYYYY`):

```yaml
assignments:
  assignment-1:
    due: 2026-10-13               # the due date students see
    grading_deadline: 2026-10-15  # OPTIONAL, grading-only - snapshot + autograde fire here
```

- **The date students see** (cohort site + the brief's "due" event) is `assignments[slug].due`
  (23:59 that day). Edit → commit → **Sync site**.
- **The grading deadline** is `grading_deadline` if set, else `due` -
  there is **no deadline input** on the Grade assignment button. Set it to grade later than
  the date students were told, without changing that date.
- **Autograding fires there, once.** At that moment the hourly cron freezes the snapshot and
  runs the autograder - no `grade:` entry needed. It never re-runs; delete
  `classroom-config/autograde/<slug>/` to re-grade.
- **The commit that is considered submitted for grading** is frozen right after the grading deadline passes, into
  `classroom-config/snapshots/<slug>.csv`. It is **write-once** - later pushes can't move the
  pin. To deliberately re-freeze (e.g. repos provisioned late), delete the CSV and the next
  hourly tick rebuilds it.

## Next

- [Grade and return the assignment](09-grade-and-return-assignments.md).

---
**Demo:** per-student repos in [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026).
