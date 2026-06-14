# DSL Teaching & Course Setup

Central registry of workflows functionality for course delivery at the Hertie Data Science Lab. 

**UI**: Faculty trigger everything as **GitHub Actions buttons** (also exposed as CLI commands).

**Access**: every action is gated on **repo permission** - the triggering user must have
write/maintain/admin on the repo the action runs in.

## The model

Two org tiers:
1. the **course** org is the faculty-facing source of truth - the historical registry of course materials persistent across years, where faculty push up version controlled materials from,
2. the **cohort** org is the per-year student-facing target - course materials are pushed to here; student assignments are submitted here; updates, forums and other student-interfacing features  live here.

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

## Setting up a course (one-time)

> **Full input checklist:** [`docs/DEPLOY-FROM-SCRATCH.md`](docs/DEPLOY-FROM-SCRATCH.md)
> lists every input needed to go from nothing to a running course + cohort.
> [`example-course/`](example-course/README.md) is a ready-to-deploy dummy course (the
> demo dataset) you can stand up on `Hertie-DSL-Demo` / `DSL-Demo-f2026`.

_Steps 1 & 2 require manual setup - the rest is automatically configured via GitHub actions buttons._

### 1. Create the empty course org 
  - https://github.com/account/organizations/new
  - Pick the Free plan.
  - Every org (course or cohort) is  created once in GitHub's web UI
    
### 2. Add the DSL bot as an owner:
  - Open the org's **People** tab: `https://github.com/orgs/<ORG>/people` → **Invite member**
  - Select the bot's username → role **Owner** (the bot then accepts the emailed-notification invite).
  -  _Skip if you created the org as the bot account: if you created
  the org while signed in *as* the bot account, it's already the owner - nothing to do._
  - (Which account is "the DSL bot"? See [The bot account](#the-bot-account).)*

### 3. Bootstrap the new org 
  - On _this_ repo's Actions tab -> [**Bootstrap Course Org**](https://github.com/hertie-data-science-lab/dsl-teaching-course-setup/actions/workflows/bootstrap-org.yml) (`org` =  the new org).
  - This sets teams, 2FA, the `.github` profile, all the faculty buttons, and propagates `DSL_BOT_TOKEN`.

### 4. Add content repos
  - Recommend to use the boostrapped `new materials repo` & `new assignment` actions - these automatically configure the required file directory for the `release materials` and `release assignments` action workflows.
  - Requirements:
    - a `materials-f202x` repo with:
      - `lectures/week-N/` folder
      - `readings/week-N/` folder
      - optionally a syllabus + README at the root),
    - a `assignment-N-f202x` template repo per assignment
      - mark `is_template`
      - add the starter materials
      - optionally add an autograder
      - optionally add solutions
    - See (ADD LINK HERE) for full details

### 5. Refresh the course org 
- So the content repos get their run-from-repo Release buttons, the repo secret is propagated, and every dropdown populates.
- Use the [`Refresh Course Org Inventory`](https://github.com/hertie-data-science-lab/dsl-teaching-course-setup/actions/workflows/refresh-inventory.yml) action


## Adding a cohort (per year)

### 1. Create the empty cohort org
  - At https://github.com/account/organizations/new (Free plan).
   - **1b. Add the bot as an owner:** `https://github.com/orgs/<ORG>/people` → **Invite member**
     → the bot's username → role **Owner** (the bot accepts the invite). Skip if you created
     the org as the bot account.
### 2. Course org -> `Bootstrap cohort` (Course-level button)
  - Seeds the `welcome` (onboard) + `classroom-config` (roster) repos,
  - Tightens permissions,
  - **Registers** the cohort in `.github/cohort-courses-pages.yml`, and refreshes the
   dropdowns so the cohort appears everywhere.

## Faculty actions

All live in the course org's bootstrapped **`.github`** Actions tab. **Release materials** and
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

## Technical details

### Cohort website

Every cohort gets an **auto-deployed website** at `<cohort-org>.github.io`, generated from
`course-website-template` by `scaffold_site` during Bootstrap cohort. `site.py` then **regenerates its content from the live org structure**
on every release (and via manual dispatch of **Sync site**): the schedule lists released weeks + assignment
due dates + MidTerm/Final exams; lecture entries link the actual released files; assignment
briefs come from each template's README; instructor/TA cards come from the `instructors` /
`teaching-assistants` teams; the course name/semester come from the org metadata.

### The bot account

Every button runs under **one** credential, `DSL_BOT_TOKEN` - "the bot". **Faculty never
hold or see it**: they trigger the Actions buttons, which run server-side under the org
secret. So a single bot serves the whole DSL - faculty use it *indirectly*.

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


### Dynamic dropdowns

`workflow_dispatch` dropdowns are static YAML and can't depend on another input, so
**Refresh actions** regenerates them from live state and re-pushes the workflows (no
cron, no app):

- **cohort_org** - from the `.github/cohort-courses-pages.yml` registry.
- **cohort_repo** - the cohort's content repos, with `materials` as the default.
- **week** - the source materials repo's `lectures/week-N/` folders (run-from-repo copy);
  the central `.github` copy uses a free-text week, since it can't depend on the chosen
  source repo.
- **source_repo** (central only) / **assignment** - the course org's content / `assignment-*` repos.

### Token

All workflows run under **`secrets.DSL_BOT_TOKEN`** (see [The bot account](#the-bot-account)
for which account that is and its exact permissions). On the **GitHub Free plan, org
secrets don't reach private repos** - so bootstrap propagates the token as an *org*
secret (for the public `.github`/`welcome`) **and** Refresh sets it as a *repo* secret on
each private content repo. The token needs cross-org repo admin + members + contents.
Production target: a **GitHub App** (fine-grained, short-lived) - or GitHub Team/Enterprise,
where org secrets reach private repos and this propagation is unnecessary.

### Repo layout

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

