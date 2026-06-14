# DSL Teaching & Course Setup

Central control plane for course delivery at the Hertie Data Science Lab. It's the
single home of the faculty automation: faculty trigger everything as **GitHub Actions
buttons** (no CLI), and the Python in `dsl_course/` is the one implementation behind
them.

**Access**: every action is gated on **repo permission** - the triggering user must have
write/maintain/admin on the repo the action runs in. Faculty do; students never do.

## The model

Two org tiers; the course org is the persistent source of truth, the cohort org is the
per-year student-facing target.

```
COURSE org   e.g. Hertie-School-Deep-Learning-E1394   (persistent, private)
  materials-f2026         lectures/week-N/ + readings/week-N/ (+ syllabus, README at root)
  assignment-1-f2026 ...  template repos (is_template) + autograder
  .github                 profile (auto) + ALL faculty buttons + cohort registry
        |
        |  release / generate  (bot token, cross-org)
        v
COHORT org   e.g. Deep-Learning-f2026                  (per-year, private)
  welcome           Join issue -> onboard.yml (enrol)
  classroom-config  students.csv roster (PRIVATE)
  materials         released lectures/readings (students-team read)
  <assignment>-<handle>   one private repo per student (generated; autograder rides along)
  students team
```

## Hard constraint: orgs are created by hand

**GitHub has no API to create an organisation.** So every org (course or cohort) is
created once in the web UI, the bot is added as an owner, and then **automation
configures it**. That's the only manual step; everything after is a button.

- **Create the org:** https://github.com/account/organizations/new (pick the Free plan).
- **Add the bot as an owner:** the org's **People** tab,
  `https://github.com/orgs/<ORG>/people` → **Invite member** → **the bot account's username
  (currently `henrycgbaker`; production target `hertie-dsl-bot`)** → role **Owner** (the bot
  then accepts the emailed/▸-notification invite). If you created the org while signed in *as*
  the bot account, it's already the owner - nothing to do.
  *(Which account is "the bot"? See [The bot account](#the-bot-account).)*

## The bot account

Every button runs under **one** credential, `DSL_BOT_TOKEN` - "the bot". **Faculty never
hold or see it**: they trigger the Actions buttons, which run server-side under the org
secret (ADR 0008). So a single bot serves the whole DSL - faculty use it *indirectly*.

| Model | What "the bot" is | When |
| --- | --- | --- |
| **Personal PAT** | a classic PAT on a maintainer's **own** account (today: `henrycgbaker`) | demo / bootstrap only - tied to one person, avoid for production |
| **Shared service account** *(recommended)* | one GitHub account, e.g. **`hertie-dsl-bot`**, with its own email + 2FA, added as **Owner** of every course/cohort org; its PAT is `DSL_BOT_TOKEN` | the institutional "DSL-wide bot any faculty can use" - one account, one token, rotated centrally; nobody shares the password |
| **GitHub App** | a **"DSL Course Automation"** App installed on both org tiers - short-lived fine-grained tokens, no static PAT, per-org revocable | end-state (ADR 0010); workflows don't change, only the token source |

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

### Who can run the buttons (onboarding faculty)

Faculty don't get the token - they get **team membership**. Every action is dispatched from
this central repo's Actions tab and gated by a `check-team` step: the triggering user must be
in the **`faculty`** or **`admin`** team of
[`hertie-data-science-lab`](https://github.com/orgs/hertie-data-science-lab/teams), else access
is denied. The workflow then runs as the bot.

**To let a new faculty member stand up and deliver courses:** add them to the **`faculty`**
team. That is the entire grant - no token, no per-person setup. They then:

1. Create the org in the web UI and **invite the bot (`henrycgbaker`) as Owner** - the one
   manual step (GitHub has no org-creation API).
2. Run **Bootstrap Course Org** from this repo's Actions tab; everything after is buttons.

> **Production note:** the bot is currently a personal PAT on `henrycgbaker`, so the whole DSL
> depends on one person's account/2FA. Migrate to a shared **`hertie-dsl-bot`** service account
> (its own email + 2FA, Owner of every org, its PAT as `DSL_BOT_TOKEN`) when going beyond demo -
> workflows and the team gate are unchanged; only the invited username and token source move.

## Setting up a course (one-time)

> **Full input checklist:** [`docs/DEPLOY-FROM-SCRATCH.md`](docs/DEPLOY-FROM-SCRATCH.md)
> lists every input needed to go from nothing to a running course + cohort.
> [`example-course/`](example-course/README.md) is a ready-to-deploy dummy course (the
> demo dataset) you can stand up on `Hertie-DSL-Demo` / `DSL-Demo-f2026`.


1. **Create the empty course org** at https://github.com/account/organizations/new (Free plan).
   - **1b. Add the bot as an owner:** `https://github.com/orgs/<ORG>/people` → **Invite member**
     → the bot's username → role **Owner** (the bot accepts the invite). Skip if you created
     the org as the bot account.
2. **Bootstrap** it - this repo's Actions tab -> **Bootstrap Course Org** (`org` =
   the new org). It sets teams, 2FA, the `.github` profile, all the faculty buttons,
   and propagates `DSL_BOT_TOKEN`.
3. **Add content** in the course org: a `materials-f2026` repo with `lectures/week-N/`
   and `readings/week-N/` folders (and optionally a syllabus + README at the root), and
   one `assignment-N-f2026` template repo per assignment (mark `is_template`; put the
   starter + an autograder in it).
4. **Refresh actions** (org button) so the content repos get their run-from-repo Release
   buttons, the repo secret is propagated, and every dropdown populates.

## Adding a cohort (per year)

1. **Create the empty cohort org** at https://github.com/account/organizations/new (Free plan).
   - **1b. Add the bot as an owner:** `https://github.com/orgs/<ORG>/people` → **Invite member**
     → the bot's username → role **Owner** (the bot accepts the invite). Skip if you created
     the org as the bot account.
2. Course org -> **Bootstrap cohort** (org button) with the cohort's name. It seeds the
   `welcome` (onboard) + `classroom-config` (roster) repos, tightens permissions,
   **registers** the cohort in `.github/cohort-courses-pages.yml`, and refreshes the
   dropdowns so the cohort appears everywhere.

## Faculty actions

All live in the course org's **`.github`** Actions tab. **Release materials** and
**Release assignment** *also* live inside each content / assignment-template repo
("run-from-repo"), where the source is that repo and `week` is a dropdown of that repo's
weeks.

| Action | Where | Effect |
| --- | --- | --- |
| **Release materials** | `.github` (pick source repo, type week) **or** the materials repo (week dropdown) | Copies the *whole* `lectures/week-N/` + `readings/week-N/` folders - every file - into the cohort `materials` repo (private + `students` read), nested under `week-N/`. Only released weeks appear. Optional `syllabus` / `README` toggles (default off). |
| **Release assignment** | `.github` or the materials repo | Two stages: freeze a cohort-level template repo `<slug>` from the chosen `assignment-*` template, then generate one private `<slug>-<handle>` repo per onboarded student *from that cohort template* (+ collaborator). `include_solution` pushes the template's `solution` branch into each student repo. |
| **New materials repo** | `.github` | Scaffold a structured `course-materials-<year>` repo (week folders + Release buttons). |
| **New assignment** | `.github` | Scaffold an `assignment-N-<year>` template (starter + autograder on `main`, an empty `solution` branch). |
| **Enroll student** | `.github` | Grant a handle org + `students`-team access (faculty override for the Join issue). Blank handle = reconcile the whole roster. |
| **Bootstrap cohort** | `.github` | Configure a pre-created cohort org (welcome + roster + tighten + website), register it, refresh. |
| **Sync site** | `.github` | Regenerate a cohort's website from the org structure (releases do this automatically). |
| **Refresh actions** | `.github` | Re-seed the run-from-repo buttons into every content repo, propagate the repo secret, repopulate all dropdowns, rebuild the profile READMEs. |

**Student onboarding** (cohort-side): students open a **Join** issue in the public
`welcome` repo; `onboard.yml` matches their student ID against the private roster,
records their authenticated handle + GitHub id, and grants org + `students`-team access.
No CLI.

## Cohort website

Every cohort gets an **auto-deployed website** at `<cohort-org>.github.io`, generated from
`course-website-template` (a theme-only Jekyll skeleton) by `scaffold_site` during
Bootstrap cohort. `site.py` then **regenerates its content from the live org structure**
on every release (and via **Sync site**): the schedule lists released weeks + assignment
due dates + MidTerm/Final exams; lecture entries link the actual released files; assignment
briefs come from each template's README; instructor/TA cards come from the `instructors` /
`teaching-assistants` teams; the course name/semester come from the org metadata. Public on
the Free plan (Pages requires it); private with Pages access control on Campus/Enterprise.

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

## Token

All workflows run under **`secrets.DSL_BOT_TOKEN`** (see [The bot account](#the-bot-account)
for which account that is and its exact permissions). On the **GitHub Free plan, org
secrets don't reach private repos** - so bootstrap propagates the token as an *org*
secret (for the public `.github`/`welcome`) **and** Refresh sets it as a *repo* secret on
each private content repo. The token needs cross-org repo admin + members + contents.
Production target: a **GitHub App** (fine-grained, short-lived) - or GitHub Team/Enterprise,
where org secrets reach private repos and this propagation is unnecessary.

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

## Related reading

Decisions, inventory, and session notes live in the
[`gh-org-strategy`](https://github.com/hertie-data-science-lab/gh-org-strategy)
coordination hub. That hub is not required at runtime; this repo stands on its own.
