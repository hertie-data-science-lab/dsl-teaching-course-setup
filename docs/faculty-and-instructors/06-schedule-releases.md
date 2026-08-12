# Schedule releases

Write the term's plan into the cohort's `classroom-config/schedule.yml` once, and the hourly
cron runs the term for you - every materials release, every assignment hand-out, every
autograde run.

## Prerequisites

- A bootstrapped [cohort](04-new-cohort-org.md) - *Bootstrap cohort* seeds both
  `classroom-config/schedule.yml` and the cron.
- The course-org repos you'll name as sources: [materials](02-add-materials-to-course.md),
  [assignment templates](03-add-assignment-to-course.md), [code](10-release-code.md).

## Write your term's plan

Live example (a full term): [`example-course/cohort-org/schedule.yml`](../../example-course/cohort-org/schedule.yml).

`materials_releases:` maps a free-form label to a `when` plus any mix of two actions:

| Action | Does |
|--------|------|
| `deploy` | copy a source path from a course repo → a cohort repo (materials, code, datasets) |
| `assignment` | provision one private repo per onboarded student from a template - or per **team**, when the template's `grading.yml` says `type: group` |

Grading never appears in this plan: each assignment is snapshotted and autograded
automatically, once, at its `grading_deadline`
(see [below](#deadline-snapshots-and-autograding)).

```yaml
timezone: Europe/Berlin
materials_releases:
  week-2:
    when: 2026-09-15T09:00
    deploy:
      - {source_repo: course-materials-f2026, source_path: lectures/02_week-2, dest_repo: materials}
      - {source_repo: lecture-code-f2026, source_path: mlpkg/simulation, dest_repo: materials}
  assignment-1-handout:
    when: 2026-09-22T09:00
    assignment: assignment-1-f2026

assignments:
  assignment-1:
    due: 2026-10-13                 # what students see
    grading_deadline: 2026-10-15    # optional - when the snapshot freezes and it is autograded
```

No `grade:` entry is needed: `assignment-1` is autograded once, at `2026-10-15T23:59:59`.

Full schema: [the schedule](required-input-schema.md#scheduleyml). 

## Verify your schedule before trusting it

1. **Dry-run the cron.** Run **Scheduled release** by hand - `dry_run` defaults to **`true`**,
   so it lists what *would* open and releases nothing. The best preflight there is.
2. **Dump the parsed schedule.**
   `python3 -m dsl_course.schedule --cohort-org DSL-Demo-f2026` prints the schedule *as parsed*,
   as JSON. A mistyped entry simply isn't there - which is how you catch a silent drop.
3. **Read the counts.** **Show status** reports the release plan as
   *"N scheduled release(s), M action(s)"* and the due dates as *"start=…, N due date(s),
   N exam(s)"*. Counts lower than what you wrote means something didn't parse.

## Silent failures

> **The schedule never errors - it drops.** Nothing below fails a run:
> - a malformed or missing **`when`** → that whole release is dropped;
> - a malformed or missing **`due`** → the whole `assignments:` entry is dropped, and the
>   grading deadline then falls back to *today* at grading time;
> - a malformed **`grading_deadline`** → ignored, and the deadline falls back to `due`;
> - an unknown or misspelt **`timezone:`** → silently falls back to `Europe/Berlin`;
> - a `deploy` entry missing **`source_repo`** or **`source_path`** → silently skipped.
>
> Which is exactly why you run the three checks above rather than assuming the file is right.

## Timezones and bare dates

- Everything naive is read in the cohort's `timezone:` (default `Europe/Berlin`).
- An explicit offset (`2026-09-15T14:00+02:00`) is honoured as written.
- A **bare date** with no time means **00:00** on a release `when` (the day opens), **23:59:59** on an assignment `due` (the day closes), and a whole day for an exam `date` (the site shows a 09:00 placeholder).

## Deadline snapshots and autograding

Each assignment's **grading deadline** is `grading_deadline` if you set it, else `due`.
Shortly after it passes, the hourly run does two things,
once each:

1. **Freezes** each submission repo's HEAD into `classroom-config/snapshots/<slug>.csv`, using
   the **server's** clock. **Write-once** - a later push can't move the pin. To re-freeze
   (repos provisioned late, say), delete the CSV and the next tick rebuilds it.
2. **Autogrades** it, against the `<slug>-<tag>` template in the course org. The marker is the
   `classroom-config/autograde/<slug>/` folder: while it exists, no further grading happens.
   To re-grade, delete it. An assignment with no template repo, no hidden tests, or
   `autograde: false` is skipped, not failed.

If grading runs with **no snapshot at all**, it falls back to a date-based pin over
student-supplied committer dates and says so loudly in the run log. Full flow:
[Grade and return assignments](09-grade-and-return-assignments.md).

## What happens on each tick

**Freeze**, then **autograde**, each passed grading deadline - once, ever - then **fire every
due release**.

```mermaid
flowchart TB
  cron["Scheduled release - hourly cron"] --> parse["parse the cohort's schedule.yml"]
  parse --> p1["`1 · freeze passed deadlines
every assignment past its grading deadline`"]
  p1 --> snap{"`snapshot CSV
already written?`"}
  snap -- no --> freeze["`write snapshots/<slug>.csv
write-once - the pin never moves again`"]
  snap -- yes --> skip["skip"]
  parse --> p2["`2 · autograde those same assignments`"]
  p2 --> mark{"`autograde/<slug>/
already there?`"}
  mark -- no --> grade["`run the hidden tests, fill EMPTY auto cells
the folder it writes is the fire-once marker`"]
  mark -- yes --> skip2["skip - delete the folder to re-grade"]
  parse --> p3["`3 · fire EVERY release whose when has passed
on every tick, forever - no released state`"]
  p3 --> dep["`deploy → cheap
nothing changed, nothing pushed`"]
  p3 --> asg["`assignment → useful
a late onboarder gets their repo next tick`"]
```

---
## Next

- [Release materials](07-release-materials-to-cohort.md) /
  [an assignment](08-release-assignment-to-cohort.md) /
  [code](10-release-code.md) by hand, when you need the fallback.
- [Grade and return assignments](09-grade-and-return-assignments.md).

---
**Demo:** `classroom-config/schedule.yml` in [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026),
run by [Scheduled release](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/scheduled-release.yml).
