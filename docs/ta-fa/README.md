# TAs & faculty assistants - day one

You've been added to a cohort's `classroom-config/people.yml`, so you are on its teaching team.
(**FA** = faculty assistant.) Terms are defined in [`../START-HERE.md`](../START-HERE.md).

## Run this first

Course org → `.github` → **Actions** → **Show status**, pick your cohort. It lists what's
configured and what's missing, with an edit link for each gap.

## Your buttons are in the course org, not the cohort org

The cohort org has no Actions of its own - its front page is student-facing. Everything you run
lives in the **course** org's `.github` repo and acts on a cohort you pick from a dropdown.
Bookmark that Actions tab.

## What you now have

Once **Sync membership** has run and you've accepted the org invites:

| Access | Via | Lets you |
|--------|-----|----------|
| Cohort org's `classroom-config` + `welcome` | the cohort's `instructors` team | edit the roster, schedule, teams and grades |
| Course org's content repos for this year | the course org's `instructors-<tag>` team (`<tag>` = `f2026`, `s2027`, ...) | push lectures, readings, assignment briefs and solutions |
| Course org's `.github` **Actions** tab | the same `instructors-<tag>` team | run every button, for this cohort |

## Runbooks you actually need

Skip 01-04 - course and cohort *setup*, done before you arrived.

| # | Runbook | Your part |
|---|---------|-----------|
| [05](../faculty-and-instructors/05-enrol-students-to-cohort.md) | Enrol students | send codes, chase non-joiners, keep `students.csv` true |
| [06](../faculty-and-instructors/06-schedule-releases.md) | **Schedule releases** | the main event - fill `schedule.yml` for the whole term |
| [07](../faculty-and-instructors/07-release-materials-to-cohort.md) | Release materials | fallback: ad-hoc pushes the schedule didn't cover |
| [08](../faculty-and-instructors/08-release-assignment-to-cohort.md) | Release an assignment | fallback: ad-hoc hand-outs |
| [09](../faculty-and-instructors/09-grade-and-return-assignments.md) | Grade and return | autograde → marks → preview PR → distribute |

## Files you'll edit

All in the cohort org's private `classroom-config` repo. Pushing to any of the first three
re-syncs automatically - no button to press.

| File | For |
|------|-----|
| `students.csv` | the roster - one row per student; `role: auditor` for read-only auditors |
| `teams.csv` | group membership for group assignments |
| `schedule.yml` | releases, due dates, exams - the term plan |
| `grades/<assignment>.csv` | marks; `auto` is filled by the autograder, you fill the rest |

Per-file reference: [`templates/classroom-config/README.md`](../../templates/classroom-config/README.md).
Full column-by-column schemas: [`required-input-schema.md`](../faculty-and-instructors/required-input-schema.md).
Every button in one line: [`actions-reference.md`](../faculty-and-instructors/actions-reference.md).
