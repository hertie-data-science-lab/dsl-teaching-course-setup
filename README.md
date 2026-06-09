# DSL Teaching & Course Setup

Central control plane for course delivery at the Hertie Data Science Lab. This repo's
**Actions tab is the faculty console** — every recurring task is a button you run from
the browser. No CLI.

**Access**: faculty and admin teams only (enforced via workflow team-check steps).

## The model

```
COURSE / MASTER org   Hertie-School-{Course}-{Code}   PRIVATE, persistent control room
  materials · solutions · PRIVATE assignment templates · cross-cohort index
        │
        │  this repo's Actions push master ──▶ cohort
        ▼
COHORT org            {Course}-f{YYYY}                 student-facing, per-cohort target
  welcome (Join issue) · classroom-config (roster) · materials (released) · per-student repos
```

- The **master is the source of truth**; the cohort **receives releases** of it.
- Templates stay **private** — the bot copies them, students never do — so assignment
  questions stay private and reusable across years.
- The roster is a per-cohort `students.csv` in the cohort's private `classroom-config`.

## Faculty console (this repo → Actions)

Each takes the target `master_org` / `cohort_org` as inputs and pushes into that cohort.

### `Provision assignment`
Generates one **private** `{assignment}-{handle}` repo per onboarded student from a
private master template, and adds the student as a collaborator. Idempotent; skips
students not yet onboarded.
Inputs: `master_org`, `cohort_org`, `assignment`, `template`, `dry_run`.

### `Release materials`
Drips selected sessions from the master content repo into the cohort-private
`materials` repo (private + `students` team read). Only released sessions appear.
Inputs: `master_org`, `content_repo`, `cohort_org`, `sessions`.

### `Enroll student`
Grants a handle org membership + `students`-team membership. The self-service path is
the cohort `welcome` Join issue; this is the faculty override. Leave `handle` blank to
re-materialise the whole roster.
Inputs: `cohort_org`, `handle`, `prune`.

## Student onboarding

Students never use a CLI. They open a **Join issue** in the cohort's public `welcome`
repo; the `onboard.yml` Action (templates in [`templates/welcome/`](templates/welcome/))
matches their student ID against the private roster, records their authenticated handle
+ GitHub id, and grants org + `students`-team access.

## Admin / create workflows

- **`bootstrap-org`** — one-time setup of a new course (master) org: teams, settings,
  `.github` profile, seeded workflows, token.
- **`new-semester`** — set up a cohort: repos, teams, website, Pages.
- **`post-migrate`** — retrospective classify/tag/migrate of historical repos.

> The create tier (`bootstrap-org` / `new-semester` / `post-migrate`) still reflects the
> earlier course-side model and is the next slimming target; the day-to-day faculty
> console above is the current model.

## Token

All workflows run under **`secrets.DSL_BOT_TOKEN`** (org-level secret on
`hertie-data-science-lab`). It needs cross-org repo admin + members + contents on the
course and cohort orgs. Production target: a GitHub App (fine-grained, short-lived).

## Repo layout

Self-contained — workflows and their Python implementation live here.

- `.github/workflows/` — dispatchable workflows (the console + admin entry points)
- `dsl_course/` — Python package implementing them (`assign`, `release`, `sync_roster`,
  `roster`, plus the create-tier modules)
- `templates/welcome/` — the cohort onboarding workflow + Join issue form
- `requirements.txt` — Python dependencies (installed by each workflow)

## Related reading

Design decisions, faculty guides, and the course inventory live in the
[`gh-org-strategy`](https://github.com/hertie-data-science-lab/gh-org-strategy)
coordination hub. That hub is not required at runtime — this repo stands on its own.
