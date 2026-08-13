# Schedule releases

Write the term's plan into the cohort's `classroom-config/schedule.yml` once, and the hourly cron runs the term for you - every materials release, every assignment hand-out, every autograde run.

The schedule file can be updated throughout the semester.

## Prerequisites

- A bootstrapped [course org](01-new-course-org.md)
- A bootstrapped [cohort org](04-new-cohort-org.md) 
- Source material repos to be released (staged in course-org, released to cohort-org)

## Write your term's plan

Live example (a full term): [`example-course/cohort-org/schedule.yml`](../example-course/cohort-org/schedule.yml).


Three blocks carry the whole term, and each is defined by what it **does**:

- **`releases:`** - the entries that **deploy**: file(s) copied from course org staging -> the cohort org, where students can reach them.
- **`assignments:`** - each assignment's whole lifecycle: hand-out, due date, grading.
- **`events:`** - **display-only** calendar rows. Nothing deploys; the row simply appears on the cohort site.

Two scalars sit alongside them - `semester_start:` and `semester_end:` - which bookend the
term and render as rows of their own.

### `releases:` - what ships, and when

Each entry is a label you choose (`lecture-1`, `lab-1`, `bonus-dataset` - it is yours, and it
is what the site shows unless you give a `title:`), holding:

| Field | Required | Default | Meaning |
|---|---|---|---|
| `event_datetime` | **yes** | - | when the class happens - what the site's schedule shows, and the default fire time for this entry's deploys |
| `deploy` | no | - | the copies this entry ships (a list - see below) |
| `title` | no | prettified label | the row label, where this entry shows on the site |
| `tbc` | no | `false` | the date is provisional: fires as normal, the site marks it **(TBC)** |

Each item under `deploy:` is one copy. Paths are **relative to their repo**: `source_path`
inside `source_repo`, `dest_path` inside `dest_repo`.

| Field | Required | Default | Meaning |
|---|---|---|---|
| `source_repo` | **yes** | - | the repo in the COURSE org to copy from |
| `source_path` | **yes** | - | the folder or file to copy, relative to `source_repo` |
| `dest_repo` | no | `materials` | the cohort repo to copy into - created on first release |
| `dest_path` | no | mirrors `source_path` | where it lands, relative to `dest_repo` |
| `deploy_datetime` | no | the entry's `event_datetime` | ship this one copy earlier (or later) than the class it belongs to |

Use this for teaching materials, code, datasets, anything else. Every release is idempotent -
a re-run is a no-op.

### `assignments:` - hand-out, due date, grading

Keyed by assignment slug (the template repo name minus its `-<tag>` suffix):

| Field | Required | Default | Meaning |
|---|---|---|---|
| `due_datetime` | **yes** | - (entry dropped without it) | the deadline students see; a bare date closes at **23:59:59** |
| `handout_datetime` | no* | - | when repos are provisioned, automatically. *Required for the schedule to hand out - without it, use the **Release assignment** button, which records the moment here for you |
| `grading_datetime` | no | `due_datetime` | when the snapshot freezes and it is [autograded](#deadline-snapshots-and-autograding), once |
| `type` | no | `individual` | `individual` or `group` - how hand-out and grading fan out. Also settable in the template's `grading.yml` |
| `max_team_size` | no | `5` | group assignments only: the welcome repo's Join-team cap |

Nothing assignment-related needs a `releases:` entry (an `assignment:` action there
is still supported, for handing out by hand from a release entry).

### `events:` - rows with nothing behind them

An exam, a drop-in clinic, a guest lecture, a revision session: anything students should see
on the calendar that releases no files.

| Field | Required | Default | Meaning |
|---|---|---|---|
| `event_datetime` | **yes** | - | when it happens; a bare date is a whole day (the site shows a 09:00 placeholder) |
| `type` | no | `special_event` | `exam` or `special_event` - which colour the row takes |
| `title` | no | prettified label | the row label on the site |
| `tbc` | no | `false` | the date is provisional: the site marks it **(TBC)** |

```yaml
events:
  mid-term:
    type: exam
    title: MidTerm Exam
    event_datetime: 2026-11-03
  project-clinic:            # no `type:` -> a special event row
    title: Project clinic
    event_datetime: 2026-10-14T10:00
```

**The calendar event is not the release.** A release entry's `event_datetime:` is when the
thing *happens* - that is what the cohort's `.github.io` site's deployed schedule shows, and
it is the default fire time for the entry's deploys. However, a deploy can also carry its own
separate `deploy_datetime:` to ship its files earlier (or later) than the class they belong
to. If nothing needs to ship at all, the row belongs under `events:`, not here.

Start **minimal** - only `source_repo` + `source_path` are required, everything else
defaults (into the cohort's `materials` repo, at the same path, at the event time):

```yaml
releases:
  lecture_02:
    event_datetime: 2026-09-15T10:00
    deploy:
      - source_repo: course-materials-f2026
        source_path: lectures/02_intro
      # -> lands at materials/lectures/02_intro when the class starts

  lab_02:
    event_datetime: 2026-09-17T14:00
    deploy:
      - source_repo: course-materials-f2026
        source_path: labs/02_intro
```

Paths are **relative to their repo**: `source_path` inside `source_repo`, `dest_path`
inside `dest_repo`. Spell fields out only where a default doesn't fit - a different
destination repo/path, or an early ship time:

```yaml
releases:
  lecture_02:
    event_datetime: 2026-09-15T10:00   # the class - what the site announces
    deploy:
      - source_repo: course-materials-f2026
        source_path: lectures/02_intro
        dest_repo: lecture_materials
        deploy_datetime: 2026-09-15T09:00   # slides out 1h early
      - source_repo: course-materials-f2026
        source_path: readings/02_intro
        dest_repo: lecture_materials   # out at class time

  lab_02:
    event_datetime: 2026-09-17T14:00   # the lab session
    deploy:
      - source_repo: course-materials-f2026
        source_path: labs/02_intro
        dest_repo: lab_materials

events:
  project-clinic:                      # nothing deploys -> a display-only site row
    title: Project clinic
    event_datetime: 2026-11-17T10:00
    tbc: true                          # provisional date - the site shows "(TBC)"

  guest-lecture:                       # not even a sketch yet: the site shows a TBC row
    title: Guest lecture               # (sorted end-of-term) until a real date replaces
    event_datetime: tbc                # `tbc`
```

**Uncertain dates.** `tbc: true` next to any date - in `releases:` or in `events:` - sketches
a provisional slot: the site marks it **(TBC)** so students know it may move, and a release
still fires at that date as normal. `event_datetime: tbc` is for no
date at all: the row appears as **TBC**, and a release with no date cannot fire until you
commit a real one - which, like any change, is just an edit to `schedule.yml` on `main`.

(`dest_repo` is yours to choose - one shared `materials` repo, or one per section as here;
the repo is created on first release.)

```yaml
timezone: Europe/Berlin
semester_start: 2026-09-07
semester_end: 2026-12-18

releases:
  lecture_02:
    event_datetime: 2026-09-15T10:00
    deploy:
      - source_repo: course-materials-f2026
        source_path: lectures/02_week-2
      - source_repo: lecture-code-f2026
        source_path: mlpkg/simulation
  lab_02:
    event_datetime: 2026-09-17T14:00
    deploy:
      - source_repo: course-materials-f2026
        source_path: labs/02_week-2

assignments:
  assignment-1:
    handout_datetime: 2026-09-22T09:00  # optional - one repo per student from assignment-1-<tag>
    due_datetime: 2026-10-13            # REQUIRED - what students see
    grading_datetime: 2026-10-15        # optional - snapshot freezes + autograded (default: due_datetime)
    type: group                         # or individual - the default if field empty

events:
  final-exam:
    type: exam                          # or special_event - the default if field empty
    title: Final Exam
    event_datetime: 2026-12-15T14:00
```

Full schema, field by field: [the schedule](DEPLOYMENT-CHECKLIST.md#scheduleyml).

## How the schedule renders on the site

The cohort site renders **one** merged, date-sorted schedule table, and colours each row by
its type. You never set the row type directly - it follows from where the row came from:

| Row type | Comes from |
|---|---|
| lecture | a released session folder under `lectures/` |
| lab | a released session folder under `labs/` |
| assignment | an `assignments:` entry - shown on **both** its hand-out date and its due date |
| exam | an `events:` entry with `type: exam` |
| special_event | an `events:` entry with no `type:` (a clinic, a guest lecture, a revision session) |
| term_date | the `semester_start:` / `semester_end:` scalars |

Two consequences worth knowing:

- **Lecture vs lab is not a field you set.** It derives from the section folder the materials
  were deployed from - `lectures/...` against `labs/...`. Lectures and labs render as
  separate rows, so a week with both shows two rows.
- **Assignments appear twice**: once on the day the repos go out, once on the day they are due.

## Changing dates mid-term

Just commit the edit to `classroom-config/schedule.yml` on `main` - the **GitHub web UI is
the recommended way** (or edit a local clone → commit → push). The hourly cron reads
whatever is on `main` at each tick, so the change takes effect within the hour; there is
nothing to re-arm or re-deploy. The one caveat: already-fired **one-shot** actions don't
rewind - a release already shipped stays shipped, and a snapshot/autograde that already ran
re-runs only if you delete its marker (`snapshots/<slug>.csv` / `autograde/<slug>/`).

## If you want to verify your schedule before trusting it

1. **Dry-run the cron.** Run **Scheduled release** by hand - `dry_run` defaults to **`true`**,
   so it lists what *would* open and releases nothing. The best preflight there is.
2. **Dump the parsed schedule.**
   `python3 -m dsl_course.schedule --cohort-org DSL-Demo-f2026` prints the schedule *as parsed*,
   as JSON. A mistyped entry simply isn't there - which is how you catch a silent drop.
3. **Read the counts.** **Show status** reports the release plan as
   *"N scheduled release(s), M action(s)"*, then the term dates as a start date plus counts
   of due dates and calendar events. Counts lower than what you wrote means something
   didn't parse.

## Silent failures

> **The schedule never errors - it drops.** Nothing below fails a run:
> - a malformed or missing **`event_datetime`** → that whole entry is dropped, in
>   `releases:` and in `events:` alike;
> - a malformed **`deploy_datetime`** → ignored, and that copy ships at the `event_datetime`;
> - a malformed or missing **`due_datetime`** → the whole `assignments:` entry is dropped, and the
>   grading deadline then falls back to *today* at grading time;
> - a malformed **`grading_datetime`** → ignored, and the deadline falls back to `due_datetime`;
> - an unknown or misspelt **`timezone:`** → silently falls back to `Europe/Berlin`;
> - a `deploy` entry missing **`source_repo`** or **`source_path`** → silently skipped.
>
> Which is exactly why you run the three checks above rather than assuming the file is right.

## Timezones and bare dates

- Everything naive is read in the cohort's `timezone:` (default `Europe/Berlin`).
- An explicit offset (`2026-09-15T14:00+02:00`) is honoured as written.
- A **bare date** with no time means **00:00** on a release's `event_datetime`/`deploy_datetime` (the day opens), **23:59:59** on an assignment `due_datetime` (the day closes), and a whole day on an `events:` entry's `event_datetime` (the site shows a 09:00 placeholder).

## Deadline snapshots and autograding

> **Autograded ≠ released to students.** The scores land only in the private
> `classroom-config` - faculty review them (and the whole-class `cohort-gradebook.csv`)
> and nothing reaches a student until the separate **Distribute grades** button:
> [three gates](10-grade-and-return-assignments.md).

Each assignment's **grading deadline** is `grading_datetime` if you set it, else `due_datetime`.
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
[Grade and return assignments](10-grade-and-return-assignments.md).

---
## Next

- [Release materials](08-release-materials-to-cohort.md) /
  [an assignment](09-release-assignment-to-cohort.md) by hand, when you need the fallback.
- [Grade and return assignments](10-grade-and-return-assignments.md).

---
**Demo:** `classroom-config/schedule.yml` in [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026),
run by [Scheduled release](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/scheduled-release.yml).
