# DSL Teaching & Course Setup

Central control plane for course delivery at the Hertie Data Science Lab. This repo's
**Actions tab is the faculty console** - every recurring task is a button you run from
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
- Templates stay **private** - the bot copies them, students never do - so assignment
  questions stay private and reusable across years.
- The roster is a per-cohort `students.csv` in the cohort's private `classroom-config`.

## Faculty actions

Faculty trigger actions **from inside the repo they're working in**, in the course org.

### Content-repo actions (run from a content / assignment-template repo)
The repo the action runs in is the **source**.

- **Release materials** - publishes one week's lecture/reading files (`lectures/Session<n>_*`,
  `readings/required/session-NN/`) into a chosen cohort repo (private + `students` read).
  Inputs: `cohort_org` (dropdown), `cohort_repo` (dropdown), `week`, ☑`include_lectures` ☑`include_readings`.
- **Provision assignment** - run from an assignment-template repo; generates one private
  `{assignment}-{handle}` repo per onboarded student in the chosen cohort.
  Inputs: `cohort_org` (dropdown), `assignment`, `dry_run`.

These ship in **`content-template`** (use *"Use this template"* for new repos) and are
added to existing repos with the **Equip repo** action.

### Org-level actions (in the course org's `.github` Actions tab)
- **Enroll student** - grant a handle org + `students`-team access (faculty override for the Join issue).
- **Equip repo** - add the Release/Provision actions to an existing repo.
- **Refresh actions** - repopulate the `cohort_org`/`cohort_repo` dropdowns from the live
  cohorts (`{course-org}-*`) + their repos. Re-run it after creating a new cohort.

## Student onboarding

Students never use a CLI. They open a **Join issue** in the cohort's public `welcome`
repo; the `onboard.yml` Action (templates in [`templates/welcome/`](templates/welcome/))
matches their student ID against the private roster, records their authenticated handle
+ GitHub id, and grants org + `students`-team access.

## Admin / create workflows

- **`bootstrap-org`** - one-time setup of a new course (master) org: teams, settings,
  `.github` profile, seeded workflows, token.
- **`new-semester`** - set up a cohort: repos, teams, website, Pages.
- **`post-migrate`** - retrospective classify/tag/migrate of historical repos.

> The create tier (`bootstrap-org` / `new-semester` / `post-migrate`) still reflects the
> earlier course-side model and is the next slimming target; the day-to-day faculty
> console above is the current model.

## Token

All workflows run under **`secrets.DSL_BOT_TOKEN`** (org-level secret on
`hertie-data-science-lab`). It needs cross-org repo admin + members + contents on the
course and cohort orgs. Production target: a GitHub App (fine-grained, short-lived).

## Repo layout

Self-contained - workflows and their Python implementation live here.

- `.github/workflows/` - dispatchable workflows (the console + admin entry points)
- `dsl_course/` - Python package implementing them (`assign`, `release`, `sync_roster`,
  `roster`, `seed` (renders/places the content-repo wrappers), plus the create-tier modules)
- `templates/welcome/` - the cohort onboarding workflow + Join issue form
- `requirements.txt` - Python dependencies (installed by each workflow)

## Related reading

Design decisions, faculty guides, and the course inventory live in the
[`gh-org-strategy`](https://github.com/hertie-data-science-lab/gh-org-strategy)
coordination hub. That hub is not required at runtime - this repo stands on its own.
