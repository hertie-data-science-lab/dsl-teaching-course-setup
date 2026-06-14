# DSL Teaching & Course Setup

Central registry of workflows functionality for course delivery at the Hertie Data Science Lab. 

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

Faculty trigger everything as **GitHub Actions**.

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
  - Invite the bot account - currently **`henrycgbaker`** (production target `hertie-dsl-bot`) - → role **Owner** (the bot then accepts the emailed-notification invite).
  -  _Skip if you created the org as the bot account: if you created
  the org while signed in *as* the bot account, it's already the owner - nothing to do._
  - (Which account is "the DSL bot"? See [The bot account](docs/ADMIN-SETUP.md#the-bot-account).)*

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
- In the newly created & bootstrapped course org, run the `Refresh actions` action.
- So the content repos get their run-from-repo Release buttons, the repo secret is propagated, and every dropdown populates.
- _Alternatively, you can use this repo's [`Refresh Course Org Inventory`](https://github.com/hertie-data-science-lab/dsl-teaching-course-setup/actions/workflows/refresh-inventory.yml) action; this refreshes actions across all DSL-managed repos._


## Adding a cohort (per year)

A cohort is bootstrapped by the **same** mechanism as a course - it's `Bootstrap Course Org`
with the **`cohort`** checkbox ticked (plus the parent `course` org). So:

### 1-2. Create the empty cohort org + add the bot as Owner
  - Identical to course steps 1-2 above (create at https://github.com/account/organizations/new,
    Free plan; invite the bot as **Owner**).

### 3. Bootstrap it as a cohort
  - Run `Bootstrap Course Org` with **`cohort` ✓** and `course` = the parent course org
    (exposed in the course org as the **`Bootstrap cohort`** button, which is that same
    action pre-set for cohorts).
  - On top of the course bootstrap, the `cohort` flag additionally: seeds the `welcome`
    (onboard) + `classroom-config` (roster) repos, tightens permissions, scaffolds the
    website, and **registers** the cohort in `.github/cohort-courses-pages.yml` (refreshing
    every dropdown so it appears everywhere).

## Faculty actions

All live in the course org's bootstrapped **`.github`** Actions tab. **Release materials** and
**Release assignment** *also* live inside each content / assignment-template repo
("run-from-repo"), where the source is that repo and `week` is a dropdown of that repo's
weeks.

### One-time setup actions:

| Action | Where | Effect |
| --- | --- | --- |
| **Bootstrap cohort** | `.github` | Configure a pre-created cohort org (welcome + roster + tighten + website), register it, refresh. |
| **Enroll student** | `.github` | Grant a handle org + `students`-team access (faculty override for the Join issue). Blank handle = reconcile the whole roster. |
| **New materials repo** | `.github` | Scaffold a structured `course-materials-<year>` repo (week folders + Release buttons). |
| **New assignment** | `.github` | Scaffold an `assignment-N-<year>` template (starter + autograder on `main`, an empty `solution` branch). |
| **Refresh actions** | `.github` | Re-seed the run-from-repo buttons into every content repo, propagate the repo secret, repopulate all dropdowns, rebuild the profile READMEs. |

### Weekly cadence actions:

| Action | Where | Effect |
| --- | --- | --- |
| **Release materials** | `.github` (pick source repo, type week) **or** the materials repo (week dropdown) | Copies the *whole* `lectures/week-N/` + `readings/week-N/` folders - every file - into the cohort `materials` repo (private + `students` read), nested under `week-N/`. Only released weeks appear. Optional `syllabus` / `README` toggles (default off). |
| **Release assignment** | `.github` or the materials repo | Two stages: freeze a cohort-level template repo `<slug>` from the chosen `assignment-*` template, then generate one private `<slug>-<handle>` repo per onboarded student *from that cohort template* (+ collaborator). `include_solution` pushes the template's `solution` branch into each student repo. |
| **Sync site** | `.github` | Regenerate a cohort's website from the org structure - releases do this automatically; the standard workflow has no need for manual sync. |

**Student onboarding** (cohort-side): students open a **Join** issue in the public
`welcome` repo; `onboard.yml` matches their student ID against the private roster,
records their authenticated handle + GitHub id, and grants org + `students`-team access.
No CLI.

_**Access**: the day-to-day buttons are gated on **repo permission** - the triggering user
must have write/maintain/admin on the repo the action runs in. The one exception is the
central **Bootstrap Course Org** action, which additionally needs **`faculty`/`admin` team
membership** in `hertie-data-science-lab` (a brand-new org has no repos to gate on yet).
To let a new faculty member stand up courses, add them to the `faculty` team - that is the
whole grant; they never hold the token. See
[`docs/ADMIN-SETUP.md`](docs/ADMIN-SETUP.md#who-can-run-which-action)._

## Technical & admin reference

The bot credential, the token / secret-propagation model, the dynamic-dropdown mechanics,
the cohort-website pipeline, and the repo layout now live in
**[`docs/ADMIN-SETUP.md`](docs/ADMIN-SETUP.md)** - faculty delivering a course don't need them.
