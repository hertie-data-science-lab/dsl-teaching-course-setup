# Required input schema

Every input needed to stand up a working course + cohort: each step's workflow, inputs and
output, then [every input file with a copyable example](#inputs-by-file). Worked example:
[`example-course/`](../../example-course/README.md).

## Course setup (once)

| | Step | Level | Where | Input | Output |
|---|------|-------|-------|-------|--------|
| `[required]` | 1. Create the course org | course | GitHub [web UI](https://github.com/account/organizations/new) | name `<course-name>-<CODE>` (no year); invite **`hertie-dsl-bot`** as **Owner** (must accept) | an empty org the bot can bootstrap |
| `[required]` | 2. Bootstrap | course | [central repo → Actions → **Bootstrap Course Org**](https://github.com/hertie-data-science-lab/dsl-teaching-course-setup/actions/workflows/bootstrap-org.yml) | `org`, `org_name`, `course_code`; optional `admin` (your handle) | the `.github` control panel with every button, the `course-admin` team, [`dsl-course.yml`](#dsl-courseyml), `DSL_BOT_TOKEN` set for you |
| `[required]` | 3. Materials | course | course `.github` → **New materials repo**, then `git push` | `tag` (e.g. `f2026`); then your content ([layout](#materials-repo)) | `course-materials-<tag>` with run-from-repo Release buttons |
| `[required]` | 4. Assignment(s) | course | course `.github` → **New assignment**, then `git push` | `number` + `tag`; brief + starter on `main`, optional autograding on `solution` ([layout](#assignment-template)) | one `assignment-N-<tag>` template each |
| *(optional)* | 5. Course admins | course | edit [`dsl-course.yml`](#dsl-courseyml), commit to `main` | GitHub handles | admin on the course org + every cohort, reconciled |
| `[required]` | 6. Refresh | course | course `.github` → **Refresh actions** | none | dropdowns populated, secrets on content repos |

Email needs nothing from you: enrolment-code + grade emails send through a centrally
configured mailbox ([details](../admin/central-admin.md#email)). Where it isn't live yet,
sends stay previews and enrolment codes still land in `students.csv`.

## Cohort setup (per year)

| | Step | Level | Where | Input | Output |
|---|------|-------|-------|-------|--------|
| `[required]` | 1. Create the cohort org | cohort | GitHub [web UI](https://github.com/account/organizations/new) | name `<course-name>-f/sYYYY`; invite **`hertie-dsl-bot`** as **Owner** (must accept) | an empty org the bot can bootstrap |
| `[required]` | 2. Bootstrap | course → cohort | course `.github` → **Bootstrap cohort** | `cohort_org` | `welcome` (Join issues) + `classroom-config` (all the files below), `students`/`auditors` teams, the cohort site, cohort registered with the cron |
| `[do this first]` | 3. The term plan | cohort | edit [`classroom-config/schedule.yml`](#scheduleyml) | releases, due dates, exams | the hourly cron runs the whole term; site dates; grading deadlines |
| `[required]` | 4. Roster | cohort | edit [`classroom-config/students.csv`](#studentscsv) | registrar rows | the enrolment + provisioning source of truth |
| *(optional)* | 5. Teaching team | cohort | edit [`classroom-config/people.yml`](#peopleyml) | handles (+ card fields) | push access for this cohort's instructors/TAs + site cards |
| `[required]` | 6. Enrol | course button, per cohort | course `.github` → **Send enrolment codes** (untick `dry_run`) | `cohort_org` | codes written to the roster + emailed; students join via the `welcome` **Join** issue |
| *(optional)* | 7. Ad-hoc release | course button, per cohort | **Release materials** / **Release assignment** | see [07](07-release-materials-to-cohort.md)/[08](08-release-assignment-to-cohort.md) | anything out earlier/differently than the schedule says |
| *(optional)* | 8. Return marks | course buttons + [`grades/<slug>.csv`](#gradesslugcsv) | the [grading runbook](09-grade-and-return-assignments.md) | your marks | private per-student gradebooks |
| *(optional)* | 9. Show status | course button, per cohort | course `.github` → **Show status** | `cohort_org` | what's configured, what's missing, an edit link per gap |

## Inputs by file

Anything you don't supply is synthesised or skipped, never blocks. All `classroom-config`
files are private (PII stays there); a cohort's own `.github/dsl-course.yml` is just a pointer
back to its course org - never edit it.

### `dsl-course.yml`

Live example: [`example-course/course-org/dsl-course.yml`](../../example-course/course-org/dsl-course.yml).

Course org's `.github` repo - the course's identity card. Bootstrap writes it; you only ever
touch `course_admins` (and optional display-only cards for the public course site).

```yaml
org: DSL-Demo-Course-E1234
org_name: DSL Demo Course        # site title
course_code: E1234
people:
  course_admins:
    - github_handle: "janedoe"   # admin on the course org + every cohort
```

### `students.csv`

Live example: [`example-course/cohort-org/students.csv`](../../example-course/cohort-org/students.csv).

`classroom-config/students.csv` - one row per student, straight from the registrar. Leave the
onboarding-owned columns blank. Deleting a row off-boards that student on the push.

```csv
student_id,hertie_email,name,github_handle,github_id,section,enrol_code,role
245001,j.doe@students.hertie-school.org,Jane Doe,,,A,,
245002,e.evans@students.hertie-school.org,Eve Evans,,,A,,auditor
```

| Column | Filled by | Notes |
|--------|-----------|-------|
| `student_id`, `hertie_email`, `name`, `section` | registrar | `hertie_email` receives the enrolment code + grade notices |
| `github_handle`, `github_id` | **onboarding** | blank until the student joins; the immutable `github_id` survives handle renames |
| `enrol_code` | **Send enrolment codes** | the token the student pastes into the Join issue |
| `role` | registrar | blank/`enrolled` = full participant; `auditor` = reads released materials, gets no assignments/grades, refused from teams |

### `people.yml`

Live example: [`example-course/cohort-org/people.yml`](../../example-course/cohort-org/people.yml).

`classroom-config/people.yml` - this cohort's teaching team. Grants the cohort's `instructors`
team **and** course-org push on that year's content repos (`instructors-<tag>`), and supplies
the cohort site's cards. `github_handle` is the only required field.

```yaml
people:
  instructors:
    - github_handle: "janedoe"     # required - everything else is optional
      name: "Prof. Jane Doe"       # site card fields
      title: "Professor of ..."
      photo: "https://.../jane.jpg"
      url: "https://.../jane"
      start: "2026-09-01"          # access auto-starts/lapses on these dates
      end: "2027-01-31"
  teaching_assistants:
    - github_handle: "anOther"
```

The **course** org's `dsl-course.yml` accepts the same `instructors`/`teaching_assistants`
shape, but there it is **display-only** (public-site cards, no access).

### `teams.csv`

Live example: [`example-course/cohort-org/teams.csv`](../../example-course/cohort-org/teams.csv).

`classroom-config/teams.csv` - group membership, per assignment. Students self-select via the
`welcome` **Join team** issue, or you edit it directly; either way a push materialises a GitHub
team per group, and a **Release assignment** run with `group` ticked grants each team one
shared repo.

```csv
assignment,team,github_handle
assignment-4-project,team-x,anna-adams
assignment-4-project,team-x,ben-baker
```

### `grades/<slug>.csv`

Live example: [`example-course/cohort-org/grades/assignment-1.csv`](../../example-course/cohort-org/grades/assignment-1.csv).

`classroom-config/grades/<slug>.csv` - one per assignment. **Grade assignment** creates it and
fills the machine columns (write-once); for hand-marked work create it yourself. `final` +
`comments` are what the student sees; full column-by-column reference:
[the grading runbook](09-grade-and-return-assignments.md#2-add-your-marks-on-top-of--instead-of-autograde).

```csv
github_handle,team,auto,manual,team_grade,adjustment,final,comments,team_comments
anna-adams,,38/40,9/10,,,A-,Great work,
```

### Materials repo

Live example: [`example-course/course-org/course-materials-f2026`](../../example-course/course-org/course-materials-f2026).

`course-materials-<tag>` - private; students only ever see what you release. Any top-level
directory holding ordinal-prefixed subdirectories is a releasable section.

```
course-materials-f2026/
  lectures/01_intro/     any files - slides, notebooks, code
  readings/01_intro/
  labs/01_setup/         add your own sections freely
  SYLLABUS.md            optional - any root file matching *syllabus*
```

### Assignment template

Live example: [`example-course/course-org/assignment-1-f2026`](../../example-course/course-org/assignment-1-f2026).

`assignment-N-<tag>` - a template repo with two branches. Student repos are generated from
`main` only.

```
main branch      README.md (the brief) + starter.*      -> what students get
solution branch  solution/ + grading.yml + tests/       -> faculty-only; hidden tests
                                                            power the (optional) autograder
```

### `schedule.yml`

Live example: [`example-course/cohort-org/schedule.yml`](../../example-course/cohort-org/schedule.yml).

`classroom-config/schedule.yml` - the term plan: the **auto-release plan** the hourly cron
runs, and the **dates** that drive the website and grading. Times are read in `timezone`
(default `Europe/Berlin`) unless given an offset; a bare **release** date = 00:00, a bare
**due**/`grading_deadline` date = 23:59:59, a bare **exam** date shows as 09:00. `when:` is
honoured to the hour.

**`materials_releases`** - each entry: a label you choose, a `when:`, and one or more actions.
Sources are read from the course org, destinations written to this cohort, so entries name
repos, never orgs. Every release is idempotent - re-runs are no-ops.

| Action | Does | Fields |
|--------|------|--------|
| `deploy` | copy a source path → a cohort repo | `source_repo`, `source_path`, `dest_repo` (default `materials`), `dest_path` (default: mirror). A list, or a single mapping for one copy |
| `assignment` | one private repo per onboarded student | the template repo name |
| `grade` | *legacy* - autograding now fires automatically at each assignment's grading deadline | `template`; optional `deadline`, `group` |

```yaml
timezone: Europe/Berlin
materials_releases:
  session_2:
    when: 2026-09-15T14:00
    deploy:
      - {source_repo: course-materials-f2026, source_path: lectures/02_intro, dest_repo: materials}
      - {source_repo: course-materials-f2026, source_path: readings/02_intro, dest_repo: materials}
  bonus-dataset:
    when: 2026-10-20T09:30            # single copy - no list needed
    deploy: {source_repo: course-datasets-f2026, source_path: week7/housing.csv, dest_repo: materials, dest_path: datasets/housing.csv}
  assignment-1-handout:
    when: 2026-09-22T09:00
    assignment: assignment-1-f2026
```

**Dates** - the website schedule and the grading deadlines. Absent values are synthesised
(semester from the tag, lectures weekly, assignments fortnightly, exams weeks 8 + 15).

```yaml
semester_start: 2026-09-07
semester_end: 2026-12-18
assignments:                          # keyed by slug (template name minus -fYYYY)
  assignment-1:
    due: 2026-10-13                   # what students see
    grading_deadline: 2026-10-15      # optional: the grading pin - snapshot freezes and the
                                      # autograder fires (once). Default = due.
    grace_days: 2                     # legacy alternative: due + N days. grading_deadline wins.
exams:
  - {name: MidTerm Exam, date: 2026-11-03}
  - {name: Final Exam, date: 2026-12-15T14:00}
```

**Silent failures - the parser never errors.** A malformed entry is dropped, not reported:

| Mistake | What happens |
|---------|--------------|
| `when:` missing/unparseable | that release is silently dropped |
| `due:` missing/unparseable | the whole `assignments:` entry is dropped - no grading pin, no site date |
| `grading_deadline:` unparseable | silently ignored - falls back to `due + grace_days` |
| `grace_days:` not an integer | silently treated as `0` |
| unknown `timezone:` | silent fallback to `Europe/Berlin` |
| `deploy` missing `source_repo`/`source_path` | that copy is silently skipped |

Verify with `python3 -m dsl_course.schedule --cohort-org <COHORT>` - anything dropped is
simply absent from the dump. Workflow: [Schedule releases](06-schedule-releases.md).

**What happens at the grading deadline.** The hourly cron freezes each submission repo's
commit into `classroom-config/snapshots/<slug>.csv` (write-once - delete it to re-freeze),
then autogrades **once** against the `<slug>-<tag>` template (`classroom-config/autograde/<slug>/`
is the fired marker - delete it to re-grade). Machine grade columns are write-once too. All of
this happens whether or not the cohort uses `materials_releases`.

## Token

One secret, `DSL_BOT_TOKEN`, runs every workflow: the bot's classic PAT (`repo` + `admin:org` +
`workflow`), set once centrally. Bootstrap and Refresh put it everywhere it is needed - you
never set it by hand.

## Known limits

- **Moodle** roster-in / grade-out is manual CSV until Hertie IT enables Web Services.
- **Pages are public** on the Free plan; access-controlled once on Campus/Enterprise.
