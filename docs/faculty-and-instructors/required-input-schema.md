# Required input schema

Every input needed to stand up a working course + cohort. Worked example:
[`example-course/`](../../example-course/README.md).

## Deployment checklist

Tick these off in order. `[required]` must be done to deploy; everything else is synthesised or
skipped if you leave it.

### Course setup (once)

- [ ] `[required]` Create the **course org** in the GitHub web UI, then add **`hertie-dsl-bot`** as **Owner** (the one manual step - there is no org-creation API).
- [ ] `[required]` Run [**Bootstrap Course Org**](https://github.com/hertie-data-science-lab/dsl-teaching-course-setup/actions/workflows/bootstrap-org.yml) from this repo's Actions tab (`org`, `org_name`, `course_code`; optional `admin`). It also sets `DSL_BOT_TOKEN` on the org - you never set the secret by hand. See [Token](#token).
- [ ] `[required]` **Materials**: scaffold with **New materials repo**, then fill `course-materials-fYYYY/lectures/01_.../` and `readings/01_.../`. Any top-level dir with ordinal-prefixed subdirs is a releasable section - add more freely. *(optional: a `*syllabus*` file + root `README`.)*
- [ ] `[required]` **Assignments** (≥1): scaffold with **New assignment**, then on `main` add the brief (`README.md`) + starter. *(optional: on the `solution` branch, the model solution, hidden `tests/` and a `grading.yml` to autograde. Student repos get `main` only.)*
- [ ] *(optional)* **Course admins**: the `people:` → `course_admins` block in the **course org's** `.github/dsl-course.yml`. See [People](#people).
- [ ] *(optional)* **Email**: to actually send enrolment-code + grade emails, add the `GRAPH_*` or `SMTP_*` secrets. See [Email](#email-optional). Without them every send stays a preview.
- [ ] `[required]` Run **Refresh actions** so every content repo gets its Release buttons, the secret propagates, and all dropdowns populate.

### Cohort setup (per year)

- [ ] `[required]` Create the **cohort org** in the web UI; add **`hertie-dsl-bot`** as **Owner**.
- [ ] `[required]` From the **course org's** Actions tab, run **Bootstrap cohort** with the empty cohort org's name. Seeds `welcome` + `classroom-config`, scaffolds the site, registers the cohort, propagates the token, applies the course's current `course_admins`.
- [ ] `[do this first]` **Fill in `classroom-config/schedule.yml`, for the whole term.** Its `materials_releases` plan is what the hourly **Scheduled release** cron runs: every materials release, every assignment hand-out, every autograde run. Its `assignments`/`exams` dates drive the website and the grading deadlines. See [The schedule](#the-schedule) and the [Schedule releases](06-schedule-releases.md) runbook.
- [ ] `[required]` **Roster**: put registrar data in `classroom-config/students.csv` - `student_id, hertie_email, name, section` (+ `role: auditor` for read-only auditors). Leave `github_handle, github_id` blank; onboarding fills them.
- [ ] *(optional)* **Instructors/TAs**: `classroom-config/people.yml`, per cohort. See [People](#people).
- [ ] `[required]` **Enrol**: run **Send enrolment codes** (untick `dry_run` to actually send). Students self-onboard via the **Join** issue in `welcome`.
- [ ] *(optional)* **Ad-hoc release**: **Release materials** / **Release assignment** for anything you want out earlier or differently than the schedule says.
- [ ] *(optional)* **Return marks**: **Grade assignment** → fill `classroom-config/grades/<slug>.csv` → **Sync gradebooks** → **Render grades (preview)** → **Distribute grades**. See [the grading runbook](09-grade-and-return-assignments.md).
- [ ] *(optional)* **Show status** any time: a per-cohort view of what's configured, what's missing, and an edit link for each gap.

## The input-schema contract

Where each input is edited, and what it becomes. Anything you don't supply is synthesised or
skipped, never blocks. A cohort org's own `.github/dsl-course.yml` is just a pointer back to its
course org - nothing to edit there.

| Element | Input location | Becomes |
|-------|-----------------|---------|
| **Course identity** | **course** `.github/dsl-course.yml` → `org_name`, `course_name`, `course_code` | site title + header |
| **Semester** | derived from the cohort org's `fYYYY`/`sYYYY` tag | "Fall 2026" + schedule anchor |
| **Course admins** | **course** `.github/dsl-course.yml` → `people:` → `course_admins` | admin on the course org + every cohort |
| **Instructors/TAs** | **cohort** `classroom-config/people.yml` | push on that cohort + a course-org `instructors-<tag>` team; the cohort site's cards |
| **Release plan** | **cohort** `schedule.yml` → `materials_releases` | what the hourly **Scheduled release** cron fires |
| **Dates** | **cohort** `schedule.yml` → `semester_start`/`semester_end`, `assignments`, `exams` | the site's schedule table + the grading deadlines |
| **Lectures / readings / any section** | `course-materials-fYYYY/<section>/<NN>_.../` | per-session entries linking the released files |
| **Syllabus** | `course-materials-fYYYY/` root file matching `*syllabus*` | cohort root + syllabus link |
| **Assignments** | `assignment-N-fYYYY`: brief + starter on `main`; solution, `grading.yml`, hidden `tests/` on `solution` | briefs on the site + one private `<slug>-<handle>` repo per student |
| **Roster** | cohort `classroom-config/students.csv` | enrolment + per-student provisioning |

## The two manual steps

| Input | How | Notes |
|-------|-----|-------|
| **Create each org** | GitHub web UI | GitHub has **no org-creation API**. One course org, one cohort org per year. Add the bot as **Owner** of each. |
| **`DSL_BOT_TOKEN`** | the bot's classic PAT, set once in the central repo | Scopes `repo` + `admin:org` + `workflow`. The only *required* secret. See [Token](#token). |

## The roster

`classroom-config/students.csv` (private). Columns:

| Column | Filled by | Notes |
|--------|-----------|-------|
| `student_id` | registrar | match key |
| `hertie_email` | registrar | where the enrolment code + grade notifications go; PII → private repo only |
| `name` | registrar | |
| `github_handle` | **onboarding** | blank until the student joins |
| `github_id` | **onboarding** | blank until the student joins; immutable, so a handle rename never orphans repos |
| `section` | registrar | |
| `enrol_code` | **Send enrolment codes** | generated; the token the student pastes to join |
| `role` | registrar | blank or `enrolled` (default) = full participant; `auditor` = read-only |

**Auditors.** `role: auditor` puts that student on the `auditors` team instead of `students`.
Both read every released-materials repo. Auditors get **no assignment repos, no gradebook, no
marks**, and are refused if they open a **Join team** issue. A roster written before the column
existed reads as all-enrolled.

## How students are managed

1. **Enrolment.** Run **Send enrolment codes** (default `dry_run=true` - untick it to send). It
   writes a random `enrol_code` onto every roster row that lacks one and emails it to each
   not-yet-onboarded student. The student opens a **Join** issue in the public `welcome` repo and
   pastes the code; their handle and `github_id` are written back onto that row and they are added
   to the `students` or `auditors` team. Non-matching codes are rejected. **The student must
   accept the org invite** before they can see anything.
2. **Provisioning.** **Release assignment** generates one private `<slug>-<handle>` repo per
   onboarded, enrolled student. **Submission** is a plain `git push` to `main`.

Deleting a row from `students.csv` off-boards that student on the same push - no separate step.

## Grades

Each student gets one private `grades-<handle>` repo. Fill `classroom-config/grades/<slug>.csv`
(`github_handle, team, auto, manual, team_grade, adjustment, final, comments, team_comments`);
`final` is what the student sees, `auto`/`manual` are never shown to them. **Render grades** opens
one PR whose diff is the preview; **Distribute grades** fans the merged files out. A teammate
never sees another member's `adjustment`.

**Autograding is optional.** If an assignment's `solution` branch carries hidden tests + a
`grading.yml`, **Grade assignment** runs them faculty-side after the deadline and fills `auto`
(individual) / `team_grade` (group). Student repos get no tests, no workflow and no score.

Step-by-step: [Grade and return assignments](09-grade-and-return-assignments.md).

## Teams (group assignments)

`classroom-config/teams.csv` (`assignment, team, github_handle`) is the only place to write:
students self-select via the welcome **Join team** issue, or you edit the CSV. A push materialises
a GitHub Team `<assignment>-<team>` from it. A **Release assignment** run with `group` ticked then
grants each team its shared repo.

## People

Access and website display are **separate inputs**:

- **`course_admins`** (course-wide admin) live in the **course org's** `.github/dsl-course.yml`
  `people:` block, and are mirrored into every cohort.
- **`instructors`/`teaching_assistants`** (push access, and the cohort site's cards) live in
  **each cohort's** `classroom-config/people.yml`. They get that cohort's `instructors` team plus
  a course-org `instructors-<tag>` team scoped to that year's content repos + `.github`.

`github_handle` is the only required field in either file. Optional `start`/`end` ISO dates
auto-rotate access - it lapses on the `end` date with no manual removal.

```yaml
# cohort's classroom-config/people.yml
people:
  instructors:
    - github_handle: "janedoe"           # required - grants the `instructors` team
      name: "Prof. Jane Doe"             # optional, and the site card's label
      title: "Professor of ..."
      photo: "https://.../jane.jpg"
      url: "https://.../profile/jane"
      start: "2026-09-01"                # optional - no start = active immediately
      end: "2027-01-31"                  # optional - no end = indefinite
  teaching_assistants:
    - github_handle: "anOther"
```

The course org's `people:` block takes the same shape, but its `instructors`/`teaching_assistants`
entries are **display-only** (the public course site's cards) and grant no access anywhere.

## The schedule

`classroom-config/schedule.yml` holds this cohort's **auto-release plan** and its
**website/grading dates**. Private, per-cohort, no PII.

**Times are timezone-aware.** A naive time is read in `timezone` (default `Europe/Berlin`), or
give an explicit offset. The cron is hourly, so a `when:` is honoured to the hour. A bare
**release** date means the **start** of that day (00:00); a bare **due** date means the **end**
(23:59:59); a bare **exam** date shows as 09:00.

### `materials_releases` - the auto-release plan

Each entry is a **label** you choose (`session_2`, `bonus-dataset`, `a1-grade`) mapping to a
`when:` datetime and one or more actions. Sources are read from the **course org**, destinations
written to this **cohort org**, so entries name repos, never orgs.

| Action | Does | Fields |
|--------|------|--------|
| `deploy` | Copy a source path → a cohort repo (materials, code, datasets). A list, one entry per copy - or a single mapping when there's only one. | `source_repo`, `source_path`, `dest_repo` (default `materials`), `dest_path` (default: mirror `source_path`) |
| `assignment` | Provision one private repo per enrolled student from a template | the `assignment-*-<tag>` template repo name |
| `grade` | Run the faculty-side autograder | `template`, optional `deadline` (default: the assignment's `due` below), optional `group`. Shorthand: `grade: <template-name>` for the defaults. |

```yaml
timezone: Europe/Berlin                # optional (default Europe/Berlin)

materials_releases:
  session_2:
    when: 2026-09-15T14:00             # bare date -> 00:00 that day
    deploy:
      - {source_repo: course-materials-f2026, source_path: lectures/02_intro, dest_repo: materials}
      - {source_repo: course-materials-f2026, source_path: readings/02_intro, dest_repo: materials}
  bonus-dataset:                        # a one-off that isn't a numbered session
    when: 2026-10-20T09:30              # one copy? a single mapping works, no list needed
    deploy: {source_repo: course-datasets-f2026, source_path: week7/housing.csv, dest_repo: materials, dest_path: datasets/housing.csv}
  assignment-1-handout:
    when: 2026-09-22T09:00
    assignment: assignment-1-f2026
  assignment-1-grade:
    when: 2026-10-15T00:00
    grade: {template: assignment-1-f2026, deadline: 2026-10-13T23:59}
    # shorthand: `grade: assignment-1-f2026` takes the deadline from `assignments:` below
```

Every release is idempotent, so a re-run is a no-op.

### Silent failures - the parser never errors

A malformed entry is **dropped, not reported**: the run stays green and the release simply
never happens.

| Mistake | What happens |
|---------|--------------|
| `when:` missing or unparseable | that release is silently dropped (it could never fire) |
| `due:` missing or unparseable | that whole `assignments:` entry is dropped - no grading pin, no site date |
| `grace_days:` not an integer | silently treated as `0` |
| unknown `timezone:` | silent fallback to `Europe/Berlin` |
| a `deploy` entry missing `source_repo` or `source_path` | that copy is silently skipped |

Verify with `python3 -m dsl_course.schedule --cohort-org <COHORT>`: it dumps the parsed
schedule, and anything dropped is simply absent. Workflow:
[Schedule releases](06-schedule-releases.md).

### Website & grading dates

For display and grading, not the release plan. Defaults are **synthesised** when absent:
semester start = 1 Sep (fall) / 1 Feb (spring) of the cohort's tag; lectures weekly;
assignments every 14 days; exams at weeks 8 and 15.

```yaml
semester_start: 2026-09-07            # YYYY-MM-DD
semester_end: 2026-12-18
assignments:                          # keyed by assignment slug (repo name minus -fYYYY)
  assignment-1:
    due: 2026-10-13T23:59             # a bare date -> end of that day
    grace_days: 2                     # OPTIONAL: extra days for GRADING only, not shown to
                                      # students. The grading deadline is due + grace_days.
  assignment-2:
    due: 2026-11-17
exams:
  - name: MidTerm Exam
    date: 2026-11-03                  # bare date -> shown at 09:00
  - name: Final Exam
    date: 2026-12-15T14:00            # a real start time is shown as given
```

### Deadline snapshots

Shortly after an assignment's grading deadline passes, the hourly cron records the commit each
submission repo is at into `classroom-config/snapshots/<slug>.csv` (`repo,sha,recorded_at`). The
file is **write-once** - a later push can never move it; a blank sha means nothing was submitted
by the deadline. To deliberately re-freeze (e.g. repos provisioned late), delete the CSV and the
next tick rebuilds it. This happens whether or not the cohort uses `materials_releases` at all.

## Token

One secret, `DSL_BOT_TOKEN`, runs every workflow: a classic PAT with `repo` + `admin:org` +
`workflow`. Bootstrap and Refresh put it everywhere it is needed - you never set it by hand.

## Email (optional)

Enrolment-code and grade emails go through `dsl_course.mailer`. A `dry_run` preview needs
neither transport. Set the secrets at org level or on the `.github` repo:

- **Microsoft Graph (preferred)** - `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`,
  `GRAPH_SENDER`. Needs an Entra app registration with the **Mail.Send** application
  permission, admin-consented and scoped to one shared mailbox.
- **SMTP (fallback)** - `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD` (+ optional `SMTP_PORT`,
  `SMTP_FROM`). Most M365 tenants disable SMTP AUTH (the `5.7.139` error), so Graph is usually
  required.

Deliverability still needs SPF/DKIM/DMARC on the sending domain.

## Known limits

- **Moodle** roster-in / grade-out is manual CSV until Hertie IT enables Web Services.
- **Pages are public** on the Free plan; access-controlled once on Campus/Enterprise.
