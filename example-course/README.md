# example-course - a worked dummy course for demos

A complete, ready-to-deploy **dummy course** that exercises the whole engine end to end:
materials, two assignments, a roster, instructor/TA cards, and an auto-generated cohort
website with a **real schedule**. Use it two ways:

- **Artifact A - the live reference demo.** Deploy this dataset to the demo org pair below,
  then send faculty the links (the site + the Actions tab). They click a finished thing - no
  setup on their end. This is also the script for a live walkthrough.
- **Artifact B - self-serve.** A faculty member follows the same steps to stand up *their
  own* course and feel the workflow. Same dataset, same runbook.

The canonical, engine-wide input reference is [`docs/required-input-schema.md`](../docs/faculty-and-instructors/required-input-schema.md).
This file is the demo-specific concretisation of it.

## The demo orgs

| Tier | Org | Role |
|------|-----|------|
| Course | **`Hertie-DSL-Demo`** | persistent control room - materials, assignment templates, the console |
| Cohort | **`DSL-Demo-f2026`** | student-facing target - welcome, roster, released materials, the site |

## What's in this dataset

```
example-course/
  course-org/
    dsl-course.yml                  # course identity + course_admins (the SSOT) + display-only instructor/TA cards
    course-materials-f2026/
      lectures/00_week-1../04_week-5/  # 5 sessions (ordinal-prefixed dirs; slides.md + a code demo each)
      readings/00_week-1../04_week-5/  # 5 sessions of placeholder readings
      syllabus.md
    lecture-code-f2026/mlpkg/       # a growing package, disclosed module-by-module (release_code)
    assignment-1-f2026/             # individual (.py)
      main/                         #   -> main branch: README brief + starter.py
      solution/                     #   -> solution branch: solution/ + grading.yml + hidden tests/
    assignment-2-f2026/             # individual (notebook): main/ + solution/
    assignment-4-project-f2026/     # GROUP project: main/ + solution/ (grading.yml type: group)
    manifests/DSL-Demo-f2026.yml    # what auto-releases each session (materials/code/assignment/grade)
  cohort-org/
    students.csv                    # 4 dummy students (handles blank - filled on onboard)
    teams.csv                       # team membership for the group project
    schedule.yml                    # release calendar (Scheduled-release cron) + due dates + exams
    people.yml                      # this cohort's own instructors/TAs (real push access)
    grades/*.csv                    # per-assignment faculty grade tables (auto/manual/final)
```

> **Assignment layout:** each `assignment-*/` splits into `main/` (-> the repo's `main` branch,
> what students get) and `solution/` (-> the `solution` branch: the model solution, `grading.yml`,
> and the HIDDEN `tests/` the faculty-side **Grade assignment** runs). Student repos never get `solution/`.

## Deploy it (≈20 min)

Prereqs: the bot account is an **owner** of both demo orgs, and `DSL_BOT_TOKEN`
(`repo` + `admin:org` + `workflow`) is available. See [the token section](../docs/faculty-and-instructors/required-input-schema.md#token).

1. **Create** `Hertie-DSL-Demo` and `DSL-Demo-f2026` in the GitHub web UI; add the bot as
   owner of each. *(The only manual step - there is no org-creation API.)*
2. This repo → Actions → **Bootstrap Course Org**: `org=Hertie-DSL-Demo`,
   `org_name=DSL Demo Course`, `course_name=Deep Learning (Demo)`, `course_code=GRAD-DEMO`,
   `set_secret=true`.
3. Copy this dataset's [`course-org/dsl-course.yml`](course-org/dsl-course.yml) into
   `Hertie-DSL-Demo/.github/dsl-course.yml` (web editor is fine). It declares
   `course_admins` (real, course-wide access) plus **display-only** instructor/TA cards
   (headshots + bio links) - so the site shows intended cards, not GitHub avatars. Real
   instructor/TA push access comes from the cohort's own `people.yml` instead (step 8).
4. **New materials repo** (`tag=f2026`), then push the contents of `course-org/course-materials-f2026/`
   into it (lectures/readings/syllabus).
5. **New assignment** twice (`number=1` then `2`, `tag=f2026`), then push each
   `course-org/assignment-N-f2026/` (README brief + `starter.py`) into the matching template.
6. **Refresh actions** (populates dropdowns + propagates the repo secret).
7. **Bootstrap cohort**: `cohort_org=DSL-Demo-f2026`.
8. Replace the starter row in `DSL-Demo-f2026/classroom-config/students.csv` with
   `cohort-org/students.csv`, and copy this dataset's
   [`cohort-org/schedule.yml`](cohort-org/schedule.yml) into
   `DSL-Demo-f2026/classroom-config/schedule.yml` - the release calendar (Scheduled release
   cron) and the **schedule** (real due/exam dates), so the site shows intended dates, not
   synthesised ones. Also copy [`cohort-org/people.yml`](cohort-org/people.yml) into
   `DSL-Demo-f2026/classroom-config/people.yml` - this cohort's real instructor/TA push
   access (a `instructors-f2026` team on the course org, scoped to this year's repos).
9. **Release materials** for sessions 0-4 (the `00_week-1` ... `04_week-5` directories). **Release assignment** for `assignment-1`.
10. **Sync site** (releases also trigger it).

## What this stands up

- **The site:** `https://dsl-demo-f2026.github.io` - course name, semester, instructor/TA
  cards, sessions 0-2 lectures linking the released files, two assignment briefs, and a schedule
  with the **real dates** from step 8 (Assignment 1 due 13 Oct, MidTerm 3 Nov, Final 15 Dec).
- **The console:** `Hertie-DSL-Demo/.github` Actions tab - every faculty button.
- **Onboarding:** open a **Join** issue in `DSL-Demo-f2026/welcome`, type a student ID from
  the roster (e.g. `220001`), and watch the onboard action enrol you. *(Only IDs whose row
  you can claim with a real GitHub account run fully end-to-end - the dummy rows have blank
  handles until someone joins.)*
