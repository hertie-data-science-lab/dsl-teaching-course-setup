# example-course - a worked dummy course for demos

A complete, ready-to-deploy **dummy course** that exercises the whole engine end to end:
materials, a growing lecture package, three assignments (one group project), a roster with an
auditor, instructor/TA cards, and a full term's auto-release schedule. Use it two ways:

- **The live reference demo.** Deploy this dataset to the demo org pair below, then send people
  the links (the site + the Actions tab). They click a finished thing. Also the script for a
  live walkthrough.
- **Self-serve.** Follow the same steps to stand up *your own* course and feel the workflow.

The engine-wide input reference is
[`required-input-schema.md`](../docs/faculty-and-instructors/required-input-schema.md); this file
is the demo-specific concretisation of it.

## The demo orgs

| Tier | Org | Role |
|------|-----|------|
| Course | **`Hertie-DSL-Demo`** | persistent control room - materials, assignment templates, the console |
| Cohort | **`DSL-Demo-f2026`** | student-facing target - welcome, roster, released materials, the site |

## What's in this dataset

```
example-course/
  course-org/
    dsl-course.yml                  # course identity + course_admins (SSOT) + display-only cards
    course-materials-f2026/
      lectures/01_week-1../05_week-5/  # 5 sessions (slides.md + a code demo each)
      readings/01_week-1../05_week-5/  # 5 sessions of placeholder readings
      syllabus.md
    lecture-code-f2026/mlpkg/       # a growing package, disclosed module-by-module
    assignment-1-f2026/             # individual (.py)      main/ + solution/
    assignment-2-f2026/             # individual (notebook) main/ + solution/
    assignment-4-project-f2026/     # GROUP project         main/ + solution/
  cohort-org/
    students.csv                    # 4 students + 1 auditor (handles blank until they onboard)
    teams.csv                       # team membership for the group project
    schedule.yml                    # the full term: materials_releases + due dates + exams
    people.yml                      # this cohort's own instructors/TAs (real push access)
    grades/*.csv                    # per-assignment grade tables (auto/manual/final)
```

> **Assignment layout:** each `assignment-*/` splits into `main/` (→ the repo's `main` branch,
> what students get) and `solution/` (→ the `solution` branch: model solution, `grading.yml`, and
> the HIDDEN `tests/` that **Grade assignment** runs). Student repos never get `solution/`.

## Deploy it (≈20 min)

Prereqs: the bot is an **owner** of both demo orgs and `DSL_BOT_TOKEN` (`repo` + `admin:org` +
`workflow`) is set. See [Token](../docs/faculty-and-instructors/required-input-schema.md#token).

1. **Create** `Hertie-DSL-Demo` and `DSL-Demo-f2026` in the web UI; add the bot as owner of
   each. *(The only manual step - there is no org-creation API.)*
2. This repo → Actions → **Bootstrap Course Org**: `org=Hertie-DSL-Demo`,
   `org_name=DSL Demo Course`, `course_code=GRAD-DEMO`, `set_secret=true`.
3. Copy [`course-org/dsl-course.yml`](course-org/dsl-course.yml) into
   `Hertie-DSL-Demo/.github/dsl-course.yml`. It declares `course_admins` (real, course-wide
   access) plus **display-only** cards for the public course site. Real instructor/TA push
   access comes from the cohort's own `people.yml` (step 8).
4. **New materials repo** (`tag=f2026`), then push `course-org/course-materials-f2026/` into it.
5. **New assignment** for `number=1`, `2` and `4-project` (`tag=f2026`), then push each
   `course-org/assignment-*-f2026/main/` and `/solution/` to the matching branches.
6. **Refresh actions** (populates dropdowns + propagates the repo secret).
7. **Bootstrap cohort**: `cohort_org=DSL-Demo-f2026`.
8. Copy this dataset's `cohort-org/` files into `DSL-Demo-f2026/classroom-config/`:
   [`schedule.yml`](cohort-org/schedule.yml) (the term's release plan + real due/exam dates),
   [`students.csv`](cohort-org/students.csv), [`people.yml`](cohort-org/people.yml),
   [`teams.csv`](cohort-org/teams.csv).
9. **Send enrolment codes** for the cohort - untick `dry_run` to actually email them.
10. Nothing else. The hourly **Scheduled release** cron works through `schedule.yml`: weeks 1-5
    of lectures + readings, the `mlpkg` subpackages, assignments 1 and 2, and the three
    post-deadline autograde runs. Use **Release materials** / **Release assignment** only to
    jump ahead of the schedule for a demo.

## What this stands up

- **The site:** `https://dsl-demo-f2026.github.io` - course name, semester, instructor/TA cards
  from the cohort's `people.yml`, lecture entries linking the released files, the assignment
  briefs, and a schedule with the real dates (Assignment 1 due 13 Oct, MidTerm 3 Nov, Final
  15 Dec at 14:00).
- **The console:** `Hertie-DSL-Demo/.github` Actions tab - every button.
- **Onboarding:** open a **Join** issue in `DSL-Demo-f2026/welcome` and paste the `enrol_code`
  that step 9 wrote onto a roster row. Try Eve Evans' code to see the **auditor** path: read
  access to the released materials, no assignment repo, no gradebook.
