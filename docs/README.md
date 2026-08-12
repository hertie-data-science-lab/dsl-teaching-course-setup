# Faculty & instructors workflows

Step-by-step runbooks for the faculty- and instructor-facing processes, end to end. Each is a
button (GitHub Actions) plus, where noted, a `git push` of your own content.

> NB: all workflows can be automated at the start of the semester by correctly filling out the cohort org's `schedule.yml` for that semester. This will then automatically handle all release of materials / assignments / grades etc, with manual GH action buttons in the course org's `.github` repo for ad hoc runs of specific workflows. 

## The two tiers

| Tier | Lives in | Lifetime | Holds |
|------|----------|----------|-------|
| **Course org** | e.g. `<course-name>-<CODE>` | persistent (all years) | materials, assignment templates, the faculty & instructors **control panel** (`.github`) |
| **Cohort org** | e.g. `<course-name>-f/sYYYY` | one per year | released materials, student repos, roster, the cohort website |

The course org is the single source of truth (SSOT); each cohort org receives **releases** of it.
Full model: [`../docs-admin-arch/architecture.md`](../docs-admin-arch/architecture.md).

## End-to-end path

```mermaid
flowchart TD
  A["`**Admin**: add faculty & instructors to
hertie-data-science-lab / faculty team`"] --> B

  subgraph COURSE["Course org (one-time)"]
    B["`**01 New course org**
create + bootstrap`"]
    C["`**02 Add materials**
scaffold + push lectures/readings`"]
    D["`**03 Add assignment**
scaffold + push brief/solution`"]
    B --> C
    B --> D
  end

  subgraph COHORT["Cohort org (once / year)"]
    E["`**04 New cohort org**
create + bootstrap`"]
    F["`**05 Enrol students**
Send enrolment codes + Join course issue`"]
    S["`**06 Schedule releases**
fill schedule.yml, the whole term, up front
(or manual release from course org's .github repo)`"]
    G["`**Releases fire**
materials · assignments · autograde runs`"]
    I["Sync site (automatic)"]
    J["`**09 Grade + return**
autograde → marks → preview → distribute`"]
    E --> F
    E --> S
    F --> G
    S ==>|"hourly cron - the primary path"| G
    G --> I
    G --> J
  end

  B --> E
  C --> G
  D --> G
```

## The workflows

Numbered in reading order - **course-level** (01-03) before **cohort-level** (04-10):

| # | Workflow | Tier | When |
|---|----------|------|------|
| 01 | [New course org](01-new-course-org.md) | course | once, when a course first goes on the platform |
| 02 | [Add materials to course](02-add-materials-to-course.md) | course | per materials repo (usually once/year) |
| 03 | [Add assignment to course](03-add-assignment-to-course.md) | course | per assignment |
| 04 | [New cohort org](04-new-cohort-org.md) | cohort | once per year |
| 05 | [Enrol students to cohort](05-enrol-students-to-cohort.md) | cohort | start of each cohort |
| 06 | [**Schedule releases**](06-schedule-releases.md) | cohort | once per cohort, up front - **the primary release path** |
| 07 | [Release materials to cohort](07-release-materials-to-cohort.md) | cohort | fallback: ad-hoc release |
| 08 | [Release assignment to cohort](08-release-assignment-to-cohort.md) | cohort | fallback: ad-hoc hand-out |
| 09 | [Grade and return assignments](09-grade-and-return-assignments.md) | cohort | per assignment, after the deadline |
| 10 | [Release code](10-release-code.md) | cohort | when the course ships a growing package to students |

The schedule (`materials_releases` in `schedule.yml`) is the primary release mechanism; the manual
release buttons are the fallback - for demos, one-offs, and recovery. Fill in
[06](06-schedule-releases.md)'s `schedule.yml` for the whole term and the hourly cron does 07, 08
and the autograde half of 09 for you.

For a one-page summary of **every button**, see [`actions-reference.md`](actions-reference.md).

## Who can run what (access)

Two separate populations - neither ever holds the bot token:

| Button | Gated by | Where it lives |
|--------|----------|----------------|
| **Bootstrap Course Org** | `faculty` / `admin` team in **`hertie-data-science-lab`** | [central repo Actions](https://github.com/hertie-data-science-lab/dsl-teaching-course-setup/actions) |
| Every **course button** | write on the course org's `.github` - i.e. its **`course-admin`** team (`course_admins`) or an **`instructors-<tag>`** team, where `<tag>` is the cohort's `fYYYY`/`sYYYY` suffix and membership comes from that cohort's own `people.yml` | the course org's `.github` Actions tab |

## Example org artefacts

Every file these runbooks ask you to write exists, filled in, in
[`../example-course/`](../example-course/) - a complete worked dummy course you can copy
from or deploy wholesale ([how](../example-course/README.md#deploy-it-20-min)):

| Runbook | Worked example |
|---------|----------------|
| [01](01-new-course-org.md) course identity, `course_admins`, staff cards | [`course-org/dsl-course.yml`](../example-course/course-org/dsl-course.yml) |
| [02](02-add-materials-to-course.md) materials tree | [`course-materials-f2026/`](../example-course/course-org/course-materials-f2026/) - `lectures/`, `readings/`, `labs/`, `syllabus.md` |
| [03](03-add-assignment-to-course.md) assignment `main/` + `solution/` | [`assignment-1`](../example-course/course-org/assignment-1-f2026/) (`.py`), [`assignment-2`](../example-course/course-org/assignment-2-f2026/) (notebook), [`assignment-4-project`](../example-course/course-org/assignment-4-project-f2026/) (**group**) - each with `grading.yml` + hidden `tests/` |
| [05](05-enrol-students-to-cohort.md) roster, teams, staff | [`students.csv`](../example-course/cohort-org/students.csv) (incl. an auditor), [`teams.csv`](../example-course/cohort-org/teams.csv), [`people.yml`](../example-course/cohort-org/people.yml) |
| [06](06-schedule-releases.md) the whole term's plan | [`schedule.yml`](../example-course/cohort-org/schedule.yml) - `event_datetime`s + `deploy_datetime`s, a display-only clinic, `assignments` + `grading_datetime`, `exams` |
| [09](09-grade-and-return-assignments.md) grade tables | [`grades/assignment-1.csv`](../example-course/cohort-org/grades/assignment-1.csv), [`grades/assignment-4-project.csv`](../example-course/cohort-org/grades/assignment-4-project.csv) (team grades) |
| [10](10-release-code.md) a growing package | [`lecture-code-f2026/mlpkg/`](../example-course/course-org/lecture-code-f2026/) - disclosed module by module |

Field-by-field rules for all of these: [`DEPLOYMENT-CHECKLIST.md`](DEPLOYMENT-CHECKLIST.md).

## Demo orgs (live reference)

A standing demo you can point at while reading - one course org, two cohorts, running the
current engine:

- Course org: **[`DSL-Demo-Course-E1234`](https://github.com/DSL-Demo-Course-E1234)** · control panel: [`.github` Actions](https://github.com/DSL-Demo-Course-E1234/.github/actions) · [public course site](https://dsl-demo-course-e1234.github.io)
- Cohort org (current): **[`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026)** · [`classroom-config`](https://github.com/DSL-Demo-f2026/classroom-config) (the filled-in [`schedule.yml`](https://github.com/DSL-Demo-f2026/classroom-config/blob/main/schedule.yml): 10 sessions, labs, three assignments, `grading_datetime`s) · [cohort site](https://dsl-demo-f2026.github.io) · [`welcome`](https://github.com/DSL-Demo-f2026/welcome)
- Cohort org (last year): **[`DSL-Demo-f2025`](https://github.com/DSL-Demo-f2025)** - what a persistent course org looks like with more than one cohort hanging off it

To stand up your own throwaway copy instead, deploy
[`example-course/`](../example-course/README.md#deploy-it-20-min) into orgs you create.
