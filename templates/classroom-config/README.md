# classroom-config - this cohort's private config

**PRIVATE.** This is the entire per-cohort data hub - roster, teams, grades,
schedule, and this cohort's own instructors/TAs. No PII (emails, ids, names) leaves
this repo. Course admins are managed at the **course org** level instead - see that
org's `.github/dsl-course.yml`; that access is kept current automatically. Faculty & instructors/FAs
edit these files; the buttons in the **course org's** Actions tab read them.
Canonical, engine-wide schema:
<https://github.com/hertie-data-science-lab/dsl-teaching-course-setup/blob/main/docs/faculty-and-instructors/required-input-schema.md>.

## students.csv - the roster (required)

One row per student. Leave `github_handle`/`github_id`/`enrol_code` blank - onboarding and
the **Send enrolment codes** button fill them in.

| column | filled by | notes |
|--------|-----------|-------|
| student_id | registrar | institutional id |
| hertie_email | registrar | **match key** - enrolment reconciles on this |
| name | registrar | display name |
| github_handle | onboarding | blank until they join via the welcome "Join" issue |
| github_id | onboarding | numeric id captured on join - **immutable; never hand-edit** |
| section | registrar | optional grouping (e.g. A/B) |
| enrol_code | **Send enrolment codes** | random non-PII token, emailed to the student; they paste it into the "Join" issue. Leave blank - the button fills blanks only, never rewrites an issued code |
| role | registrar | `enrolled` (blank means enrolled) or `auditor` - auditors are read-only: released materials only, no assignment repos, no gradebook, no project teams |

A push to this file triggers **Sync membership** automatically, reconciling the
`students` and `auditors` teams to match (a deleted row revokes access on that same push -
there is no separate off-boarding step).

## grades/<assignment>.csv - marks (optional, when returning grades)

One file per assignment, e.g. `grades/assignment-1.csv`:
`github_handle, team, auto, manual, team_grade, adjustment, final, comments, team_comments`.
The autograder pre-fills `auto`/`team_grade` from hidden tests; faculty & instructors fill the
rest, then **Sync gradebooks** -> **Render grades** -> **Distribute grades**. It runs itself
**once** per assignment, at that assignment's grading deadline in `schedule.yml`
(`assignments.<slug>.grading_deadline`, else `due`) - there is no
separate deadline input, and no hourly re-run. `auto`/`team`/`team_grade` are **write-once**:
once filled, no run overwrites them, so your corrections stand. To recompute, clear those
cells and delete `autograde/<slug>/`. A generated,
read-only `cohort-gradebook.csv` (one row per student, one column-group per
assignment) appears alongside the per-student gradebooks on every **Render grades** -
never hand-edit it, it's a glance view, not a source.

## teams.csv - group membership (optional, for group assignments)

`assignment, team, github_handle`. Students self-select via the welcome "Join team" issue,
or edit directly - a push here also triggers **Sync membership**. Auditors (`role: auditor`
above) are refused by that issue: no assignment repos means no project teams. See
`teams.csv.sample` - **the engine only acts on a real `teams.csv`.**

## schedule.yml - the release plan + due dates + exams (optional)

This cohort's whole schedule in one file. `materials_releases:` is the **auto-release
plan** - labelled entries (`session_2`, `lab_1`, `bonus-dataset`, ...), each with a
`when:` datetime and one or more actions (`deploy` a source path -> a cohort repo,
`assignment` provision student repos, `grade` run the autograder). The hourly **Scheduled
release** cron fires each entry once its `when` has arrived (honoured to the hour). Also
holds `semester_start`/`semester_end`, `assignments` (due dates for the website, plus each
assignment's `grading_deadline` - the moment its snapshot freezes and it is autograded,
once), and `exams`. Seeded mostly-commented - uncomment and
fill what you want; anything left out is synthesised or simply not scheduled.

## people.yml - this cohort's instructors/TAs (optional)

Most cohorts have different lecturers/TAs, so - unlike course admins (course-org level,
see above) - instructors/TAs are declared here, per cohort. **Sync membership**
reconciles them into this cohort's own `instructors` team AND a course-org
`instructors-<tag>` team (push access scoped to just this year's content repos, plus
the central `.github` repo so they can use the central dispatch buttons too), so they
can push materials without a course-level declaration. Seeded mostly-commented -
uncomment and fill what you want to pin.
