# Schedule releases

Write the term's plan into the cohort's `classroom-config/schedule.yml` once, and the hourly cron runs the term for you - every materials release, every assignment hand-out, every autograde run. 

The schedule file can be updated throughout the semester.

## Prerequisites

- A bootstrapped [course org](01-new-course-org.md)
- A bootstrapped [cohort org](04-new-cohort-org.md) 
- Source material repos to be released (staged in course-org, released to cohort-org)

# Write your term's plan

> For a fully worked example schedule.yml (a full term) see [here](../example-course/cohort-org/schedule.yml).

> An example of the automatically generated schedule on the deployed `.github.io` site can also be seen live [here](https://hertie-demo-f2026.github.io/schedule/). 

Three blocks carry the whole term, and each is defined by what it **does**:

- **`releases:`** - the entries that **deploy**: file(s) copied from course org staging -> the cohort org, where students can access them.
- **`assignments:`** - each assignment's whole lifecycle: hand-out, due date, grading.
- **`events:`** - **display-only** calendar rows. Nothing deploys; the row simply appears on the cohort site.

Two scalars sit alongside them - `semester_start:` and `semester_end:` - which bookend the term and render as rows of their own.

## `releases:` 

Use this for releasing teaching materials, code, datasets, anything else.

Each entry is a label you choose (`lecture-1`, `lab-1`, `bonus-dataset` - it is yours to declare here, and it is what the site shows unless you give a `title:`). Each entry holds:

| Field | Required | Default | Meaning |
|---|---|---|---|
| `event_datetime` | **yes** | - | when the class happens - what the site's schedule shows, and the default fire time for this entry's deploys |
| `deploy` (nested entry) | no | - | the copies this entry ships (a nested list - see below) |
| `title` | no | prettified label | the row label, where this entry shows on the site |
| `tbc` | no | `false` | signals the date is provisional: it fires as normal just the deployed site marks it **(TBC)** |


NB: **the calendar event is not the release.** 
  - A release entry's `event_datetime:` is when the session *happens* - that is what the cohort's `.github.io` site's deployed schedule shows, and it is the default fire time for the entry's deploys. 
  - However, a deploy can also carry its own separate `deploy_datetime:` to ship its files earlier (or later) than the class they belong to. 
  - If nothing needs to ship at all, the row belongs under `events:`, not here.

Nested under `deploy:` we havee the following:

| Field | Required | Default | Meaning |
|---|---|---|---|
| `course_source_repo` | **yes** | - | the repo in the COURSE org to copy from |
| `course_source_path` | **yes** | - | the folder or file to copy, relative to `course_source_repo` |
| `cohort_dest_repo` | no | `materials` | the cohort repo to copy into - created on first release |
| `cohort_dest_path` | no | mirrors `course_source_path` | where it lands, relative to `cohort_dest_repo` |
| `deploy_datetime` | no | the entry's `event_datetime` | ship this one copy earlier (or later) than the class it belongs to |

NB: `cohort_dest_repo` is yours to choose - one shared `materials` repo, or one repo for lectures, another for labs etc; any non-existent repo and/or directory structure specified between `cohort_dest_repo` and `cohort_dest_path` is created on release if non-exist.

At a minimum only `course_source_repo` + `course_source_path` are required, everything else defaults:

```yaml
releases:
  lecture_02:
    event_datetime: 2026-09-15T10:00
    deploy:
      - course_source_repo: course-materials-f2026
        course_source_path: lectures/02_intro
# -> lands at materials/lectures/02_intro when the class starts (the event_datetime)

  lab_02:
    event_datetime: 2026-09-17T14:00
    deploy:
      - course_source_repo: course-materials-f2026
        course_source_path: labs/02_intro
```
Each item under `deploy:` is one file to be deployed. Paths are **relative to their repo**: 
- `course_source_path` inside `course_source_repo`
- `cohort_dest_path` inside `cohort_dest_repo`. 

Spell fields out only where a default doesn't fit - a different
destination repo/path, or an early ship time:

```yaml
releases:
  lecture_02:
    event_datetime: 2026-09-15T10:00   # class time - what the deployed site schedule will announce
    deploy:
      - course_source_repo: course-materials-f2026 # item 1
        course_source_path: lectures/02_intro
        cohort_dest_repo: lecture_materials
        deploy_datetime: 2026-09-15T09:00   # is released 1h early
      - course_source_repo: course-materials-f2026 # item 2
        course_source_path: readings/02_intro
        cohort_dest_repo: lecture_materials   

  lab_02:
    event_datetime: 2026-09-17T14:00   # the lab session, which the undefined deploy_datetime will default to
    deploy:
      - course_source_repo: course-materials-f2026
        course_source_path: labs/02_intro
        cohort_dest_repo: lab_materials

```

## `assignments:` 

For the full assignment lifecyle: hand-out, due date, grading

Keyed by a slug you choose. As with a `deploy:`, `course_source_repo` names where it comes from and `cohort_dest_repo` what it is called in the cohort (default: the slug). 

> `teams.csv` rows and the grades/snapshot files key on the cohort name too - `cohort_dest_repo` if set, else the slug.

| Field | Required | Default | Meaning |
|---|---|---|---|
| `handout_datetime` | no* | - | when repos are provisioned, automatically. |
| `due_datetime` | **yes** | - | the deadline students see; a bare date closes at **23:59:59** |
| `grading_datetime` | no | `due_datetime` | when the snapshot freezes and it is [autograded](#deadline-snapshots-and-autograding) |
| `type` | no | `individual` | `individual` or `group`  |
| `max_team_size` | no | `5` | group assignments only: the welcome repo's Join-team cap |
| `course_source_repo` | **yes** | - | the course-org repo this hands out from - one repo per student (or team) is generated from it |
| `cohort_dest_repo` | no | the slug | what the cohort-side repos are called: `<name>-<handle>` per student (or `<name>-<team>`), and the frozen cohort template `<name>` |

```yaml
assignments:
  assignment-1:
    course_source_repo: assignment-1-f2026  # required: the course-org repo it hands out from
    cohort_dest_repo: assignment-1-basics # optional: the cohort-side name. Default if undefined: the slug (i.e. assignment-1).
    handout_datetime: 2026-09-22T09:00  
    due_datetime: 2026-10-13            # what students see
    grading_datetime: 2026-10-15        # snapshot freezes + autograded (default when undefined: mirrors due_datetime)
    type: group                         # default: individual 
    max_team_size: 3

  regression: # the slug is a label; the repo is named outright
    course_source_repo: wk3-regression-f2026
    due_datetime: 2026-11-10
```

A `course_source_repo:` naming a repo that does not exist is reported loudly and the assignment is skipped - it can only be a typo, and its one other symptom is an assignment that never hands out and never grades. An entry missing the field altogether is dropped, like one missing `due_datetime:`.

## `events:` 

Could be an exam, a drop-in clinic, a guest lecture, a revision session: anything students should see on the calendar that releases no files.

| Field | Required | Default | Meaning |
|---|---|---|---|
| `event_datetime` | **yes** | - | when it happens; as displayed on the deployed site schedule |
| `type` | no | `special_event` | e.g. `exam` or `special_event` - affects which colour the row takes |
| `title` | no | prettified label | the row label on the site |
| `tbc` | no | `false` | the date is provisional: the site marks it **(TBC)** |

```yaml
events:
  mid-term:
    type: exam
    title: MidTerm Exam
    event_datetime: 2026-11-03

  project-clinic:                     
    title: Project clinic
    event_datetime: 2026-11-17T10:00
    tbc: true  # provisional' - site shows "(TBC)" next to the given date time.

  guest-lecture:  
    title: Guest lecture  
    event_datetime: tbc # site will show just TBC, no proposed datetime
                       # sorted end-of-term until a real date replaces
```

---
Full schema, field by field, see [here](DEPLOYMENT-CHECKLIST.md#scheduleyml).

 For a fully worked example schedule.yml (a full term) see [here](../example-course/cohort-org/schedule.yml).

---


## Changing dates mid-term

Just commit the edit to `classroom-config/schedule.yml` on `main` - the **GitHub web UI is the recommended way** (or edit a local clone → commit → push). The hourly cron readswhatever is on `main` at each tick, so the change takes effect within the hour; there is nothing to re-arm or re-deploy. 

The one caveat: already-fired **one-shot** actions don't rewind - a release already shipped stays shipped, and a snapshot/autograde that already ran re-runs only if you delete its marker (`snapshots/<slug>.csv` / `autograde/<slug>/`).

## Verifying your schedule

**It checks itself.** Every commit touching `schedule.yml` runs **Validate schedule** in `classroom-config`. A commit that parses clean gets a green tick; one the scheduler cannot fully read gets a **red X**, and an issue naming the bad entry is opened and assigned to you, closing itself when a later commit parses clean.

The run summary shows what the parser *understood*, not just what it rejected - counts one short of what you wrote is how you catch a mistake that is valid YAML:

```
Parsed schedule.yml
  term 2026-09-07 -> 2026-12-18  (Europe/Berlin)
  11 release(s), 19 deploy(s) | 3 assignment(s) | 4 event(s)
```

Three other ways to check, none of them required:

1. **Read the counts.** **Check cohort setup** reports the release plan and term dates, and flags `N entry/ies DROPPED`.
2. **Validate by hand.** `python3 -m dsl_course.schedule --cohort-org hertie-demo-f2026 --validate`, or `--file schedule.yml --validate` against a local copy. Without `--validate` it prints the schedule *as parsed*, as JSON.
3. **Dry-run the cron.** Run **Scheduled release** by hand; `dry_run` defaults to **`true`**, so it lists what *would* open and releases nothing.

## Dropped entries

An entry that is valid YAML but not a valid *schedule* entry is **dropped**: it cannot be run, so the rest of the term parses without it. This is the one fault a green run hides, so every drop is named in the run log, counted on **Check cohort setup**, and turned into a non-zero exit by `--validate`.

| Fault | What the cohort loses |
|---|---|
| no valid `event_datetime` on a `releases:` or `events:` entry | nothing deploys, and no row appears on the site |
| no valid `due_datetime` on an `assignments:` entry | no deadline, no submission snapshot, no autograding |
| a `deploy` item missing `course_source_repo` or `course_source_path` | that one copy never ships |

Tolerated rather than dropped: a malformed `deploy_datetime` (the copy ships at the `event_datetime`), a malformed `grading_datetime` (falls back to `due_datetime`), and an unknown `timezone:` (falls back to `Europe/Berlin`, and is reported alongside the drops).

## Timezones and bare dates

- Everything naive is read in the cohort's `timezone:` (default `Europe/Berlin`).
- An explicit offset (`2026-09-15T14:00+02:00`) is honoured as written.
- A **bare date** with no time means **00:00** on a release's `event_datetime`/`deploy_datetime` (the day opens), **23:59:59** on an assignment `due_datetime` (the day closes), and a whole day on an `events:` entry's `event_datetime` (the site shows a 09:00 placeholder).

## Deadline snapshots and autograding

Full details of this are in [10-grade-and-return-assignments.md](10-grade-and-return-assignments.md); below is as it pertains to the `schedule.yml`.

> **Autograded ≠ released to students.** The scores land only in the private `classroom-config` - faculty review them (and the whole-class `cohort-gradebook.csv`) and nothing reaches a student until the separate **Distribute grades** button: [three gates](10-grade-and-return-assignments.md).

Each assignment's **grading deadline** is `grading_datetime` if you set it, else `due_datetime`. Shortly after it passes, the hourly run does two things, once each:

1. **Freezes** each submission repo's HEAD into `classroom-config/snapshots/<slug>.csv`, using the **server's** clock.
2. **Autogrades** it (optional).

---

## Next

- [Manually Release materials](08-release-materials-to-cohort.md) 
- [Manually release an assignment](09-release-assignment-to-cohort.md)
- [Grade and return assignments](10-grade-and-return-assignments.md)

---

**Demo:** `classroom-config/schedule.yml` in [`hertie-demo-f2026`](https://github.com/hertie-demo-f2026),
run by [Scheduled release](https://github.com/hertie-demo-e1234/.github/actions/workflows/scheduled-release.yml).
