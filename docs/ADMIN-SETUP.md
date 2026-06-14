# Admin & technical reference

Implementation and one-time-setup detail behind the faculty buttons: the bot credential,
the token / secret model, how the dynamic dropdowns regenerate, the cohort-website
pipeline, and the repo layout. **Faculty delivering a course don't need this** - see the
[root README](../README.md) for the button workflow.

## The bot account

Every button runs under **one** credential, `DSL_BOT_TOKEN` - "the bot". **Faculty never
hold or see it**: they trigger the Actions buttons, which run server-side under the org
secret. So a single bot serves the whole DSL - faculty use it *indirectly*.

| Model | What "the bot" is | When |
| --- | --- | --- |
| **Personal PAT** | a classic PAT on a maintainer's **own** account (today: `henrycgbaker`) | demo / bootstrap only - tied to one person, avoid for production |
| **Shared service account** *(recommended)* | one GitHub account, e.g. **`hertie-dsl-bot`**, with its own email + 2FA, added as **Owner** of every course/cohort org; its PAT is `DSL_BOT_TOKEN` | the institutional "DSL-wide bot any faculty can use" - one account, one token, rotated centrally; nobody shares the password |
| **GitHub App** | a **"DSL Course Automation"** App installed on both org tiers - short-lived fine-grained tokens, no static PAT, per-org revocable | end-state (ADR 0010); workflows don't change, only the token source |

The account to **invite as Owner** of each new org (course setup step 2) is currently
**`henrycgbaker`** (production target: `hertie-dsl-bot`).

**Exact permissions the bot needs.** It must be an **Owner** of every course and cohort
org, and its token must carry:

| Classic PAT scope | Covers |
| --- | --- |
| `repo` | create + read/write repos incl. **private**; contents; generate-from-template; topics; repo settings + repo secrets |
| `admin:org` | org **membership** + **teams** (invite students, manage `students`/`instructors`/`teaching-assistants`); org **settings** (2FA); **org secrets** |
| `workflow` | write the seeded workflow files (the buttons) |

> **Fine-grained PAT / App equivalent** (per org): **Repository** → Contents, Administration,
> Workflows, Secrets = *Read & write*, Metadata = *Read*; **Organization** → Members,
> Administration = *Read & write*. A fine-grained PAT targets **one** resource-owner org, so
> cross-org automation uses a **classic PAT or the App** (which span both tiers).

### Who can run which action

Two gates, by action type - both intentional:

- **Day-to-day buttons** (Release materials/assignment, New materials/assignment, Enroll,
  Bootstrap cohort, Sync site, Refresh actions) gate on **repo permission**: the triggering
  user needs `write`/`maintain`/`admin` on the repo the action runs in
  (`seed.py` `_CHECK_TEAM`). Triggering a `workflow_dispatch` already requires write, so
  repo permission is the gate; students never have it.
- **Bootstrap Course Org** (the central, cross-org action that provisions a brand-new org)
  additionally requires **`faculty`/`admin` team membership** in `hertie-data-science-lab`
  (`bootstrap-org.yml` `check-team`) - at bootstrap time the new org has no repos to gate
  on yet. **To onboard a new faculty member, add them to the `faculty` team**; that is the
  whole grant - they never touch the token.

## Token

All workflows run under **`secrets.DSL_BOT_TOKEN`** (see [The bot account](#the-bot-account)
for which account that is and its exact permissions). On the **GitHub Free plan, org
secrets don't reach private repos** - so bootstrap propagates the token as an *org*
secret (for the public `.github`/`welcome`) **and** Refresh sets it as a *repo* secret on
each private content repo. The token needs cross-org repo admin + members + contents.
Production target: a **GitHub App** (fine-grained, short-lived) - or GitHub Team/Enterprise,
where org secrets reach private repos and this propagation is unnecessary.

## Dynamic dropdowns

`workflow_dispatch` dropdowns are static YAML and can't depend on another input, so
**Refresh actions** regenerates them from live state and re-pushes the workflows (no
cron, no app):

- **cohort_org** - from the `.github/cohort-courses-pages.yml` registry.
- **cohort_repo** - the cohort's content repos, with `materials` as the default.
- **week** - the source materials repo's `lectures/week-N/` folders (run-from-repo copy);
  the central `.github` copy uses a free-text week, since it can't depend on the chosen
  source repo.
- **source_repo** (central only) / **assignment** - the course org's content / `assignment-*` repos.

## Cohort website

Every cohort gets an **auto-deployed website** at `<cohort-org>.github.io`, generated from
`course-website-template` by `scaffold_site` during Bootstrap cohort. `site.py` then **regenerates its content from the live org structure**
on every release (and via manual dispatch of **Sync site**): the schedule lists released weeks + assignment
due dates + MidTerm/Final exams; lecture entries link the actual released files; assignment
briefs come from each template's README; instructor/TA cards come from the `instructors` /
`teaching-assistants` teams; the course name/semester come from the org metadata.

## Repo layout

Self-contained - workflows + their Python implementation live here.

- `.github/workflows/` - `bootstrap-org` (+ the legacy create-tier); the faculty
  workflows are rendered + seeded into the course/cohort orgs, not kept here.
- `dsl_course/` - the package:
  - `bootstrap_course` - configure a course or (`--cohort`) cohort org.
  - `seed` - render the workflows (central + run-from-repo), discover dropdown options, refresh.
  - `release` - publish a week's materials (+ optional syllabus/README) into a cohort repo.
  - `assign` - freeze a cohort assignment template, then fan out per-student repos.
  - `scaffold` - create structured materials / assignment repos + the cohort website.
  - `site` - regenerate a cohort website from the live org structure.
  - `sync_roster` - enrol / materialise team access from `students.csv`.
  - `roster` - read the per-cohort `students.csv`.
  - `utils` - shared `gh`/git helpers with rate-limit backoff.
  - `new_semester` / `post_migrate` / `bootstrap_org` / `list_orgs` - legacy create-tier
    (older course-side model; the next slimming target).
- `templates/welcome/` - the cohort onboarding workflow + Join issue form.
