# Architecture & workflows

Admin / developer reference - **how the system is built and how the pieces move**. For the
faculty-facing overview see the [root README](../README.md); for operational specifics (exact
PAT scopes, how to grant access) see [ADMIN-SETUP.md](ADMIN-SETUP.md).

- [System overview](#system-overview)
- [The bot identity](#the-bot-identity)
- [Token & secret propagation](#token--secret-propagation)
- [Access model — two populations](#access-model--two-populations)
- [Core workflows](#core-workflows)
- [Dynamic dropdowns](#dynamic-dropdowns)
- [Cohort website](#cohort-website)
- [Course website (open courseware)](#course-website-open-courseware)
- [Bot lifecycle — setup & rotation](#bot-lifecycle--setup--rotation)
- [Code map](#code-map)

## System overview

Two org tiers plus one central control repo, all operated by a single **bot** identity.
GitHub has **no org-creation API**, so each org is created by hand and the bot is invited as
Owner; everything after that is a button.

```mermaid
flowchart TB
  subgraph central["hertie-data-science-lab (central)"]
    repo["dsl-teaching-course-setup<br/>code + Bootstrap action"]
    sec["DSL_BOT_TOKEN secret"]
  end
  bot(["hertie-dsl-bot<br/>service account · Owner of every org"])
  subgraph course["COURSE org — persistent"]
    cg[".github<br/>profile + faculty buttons + cohort registry"]
    mat["course-materials-fYYYY<br/>lectures/ + readings/"]
    asg["assignment-N-fYYYY<br/>is_template: main + solution branch"]
  end
  subgraph cohort["COHORT org — per year"]
    wel["welcome<br/>Join issue → onboard"]
    ros["classroom-config<br/>students.csv roster"]
    cmat["materials<br/>released lectures/readings"]
    stu["slug-handle<br/>one private repo per student"]
    site["org.github.io<br/>auto-deployed website"]
  end
  repo -->|"Bootstrap Course Org"| course
  repo -->|"Bootstrap (cohort=true)"| cohort
  course -->|"Release materials / assignment"| cohort
  bot -.->|"operates via DSL_BOT_TOKEN"| course
  bot -.->|"operates via DSL_BOT_TOKEN"| cohort
```

## The bot identity

Every button runs server-side under **one** credential, `DSL_BOT_TOKEN` - "the bot".
**Faculty never hold or see it**; they trigger the Actions buttons, which run as the bot.

The bot is the shared service account **`hertie-dsl-bot`** - its own email + 2FA, **Owner of
every course and cohort org**, and its classic PAT is `DSL_BOT_TOKEN`. One account, one token,
rotated centrally; nobody shares the password. Exact PAT scopes are in
[ADMIN-SETUP](ADMIN-SETUP.md#the-bot-account); standing it up and rotating it is the
[Bot lifecycle](#bot-lifecycle--setup--rotation).

## Token & secret propagation

The token is set **once**, in the central repo, and the actions **fan it out** - admins never
hand-edit per-org secrets.

```mermaid
flowchart TD
  src["central repo secret<br/>DSL_BOT_TOKEN = bot PAT<br/>(set once, by hand)"]
  src -->|"Bootstrap Course Org<br/>--propagate-secret"| orgsec["each org's DSL_BOT_TOKEN<br/>ORG secret<br/>visibility = selected → .github (+ welcome)"]
  src -->|"Refresh actions"| reposec["REPO secret on each<br/>private content repo<br/>materials-* · assignment-*"]
  orgsec --> pub["public .github / welcome<br/>workflows authenticate"]
  reposec --> priv["run-from-repo buttons in<br/>private content repos"]
```

Why two paths, and why `selected` visibility:

- On the **GitHub Free plan, org secrets don't reach private repos** - so the private content
  repos get a **repo** secret, set by **Refresh actions**.
- An org secret with the gh-default `private` visibility doesn't reach **public** repos either
  - and `.github` / `welcome` are public. So the **org** secret is scoped
  **`visibility=selected → .github`** (plus `welcome` on cohort orgs), which reaches the
  public infra repos while keeping the org-admin token **out of** student/content repos
  (`set_org_secret`). `visibility=all` would expose it to every workflow in the org.
- On GitHub Team/Enterprise, org secrets reach private repos and this propagation is unnecessary.

## Access model — two populations

Two **separate** gates - do not conflate them.

```mermaid
flowchart TD
  subgraph prov["1 · Provision orgs (DSL-wide)"]
    ct["hertie-data-science-lab<br/>faculty / admin teams"] -->|"write/admin on"| cr["central repo"] --> ba["run Bootstrap Course Org"]
  end
  subgraph run["2 · Run a course's buttons (per-course)"]
    it["course org's own<br/>instructors (write) / course-admin (admin)"] -->|"granted on"| gh["that org's .github"] --> rb["run Release / Refresh / Enroll / ..."]
  end
  prov ~~~ run
```

- **Provisioning** is a DSL-wide authority: the central `faculty`/`admin` teams, granted
  write/admin on the central repo, may run **Bootstrap Course Org**. Nothing else.
- **Running a course's buttons** is **per-course**: only that course org's own
  `instructors`/`course-admin` teams, which bootstrap grants on `.github`.
- GitHub shows "Run workflow" only to **write+** users; the seeded `check-team` re-checks repo
  permission at run time. Nobody is added to a course they don't teach (teams are org-scoped,
  so cross-org grants aren't possible anyway). Full detail + how to add people:
  [ADMIN-SETUP "Who can run which action"](ADMIN-SETUP.md#who-can-run-which-action).

## Core workflows

### Bootstrap a course org

```mermaid
sequenceDiagram
  actor F as Faculty / admin
  participant A as Bootstrap action, central
  participant Bot as bot, DSL_BOT_TOKEN
  participant Org as new course org
  Note over F,Org: org created by hand + bot invited as Owner first
  F->>A: workflow_dispatch (org, org_name, admin?)
  A->>A: check-team — faculty/admin in central org
  A->>Bot: bootstrap_course --propagate-secret
  Bot->>Org: org settings (2FA) + role teams
  Bot->>Org: .github profile + seed faculty buttons
  Bot->>Org: grant instructors/course-admin on .github
  Bot->>Org: add --admins handles to course-admin
  Bot->>Org: set DSL_BOT_TOKEN org secret (selected → .github)
  Bot->>Org: build profile README
```

A **cohort** is the same action with `cohort=true` (+ parent `course`): it additionally seeds
`welcome` + `classroom-config`, tightens permissions, scaffolds the website, and registers the
cohort in the course's `cohort-courses-pages.yml`.

### Release materials

```mermaid
sequenceDiagram
  actor F as Faculty, instructors
  participant A as Release materials
  participant Src as course-materials-fYYYY, course
  participant Coh as cohort materials repo
  F->>A: dispatch (cohort, week)
  A->>A: check-team — repo permission
  A->>Src: read lectures/week-N + readings/week-N
  A->>Coh: copy whole folders under week-N/ (private, students read)
  Note over A,Coh: only released weeks appear, syllabus/README optional
```

### Release assignment

```mermaid
sequenceDiagram
  actor F as Faculty
  participant A as Release assignment
  participant T as assignment template, main
  participant CT as cohort template
  participant S as per-student repos
  F->>A: dispatch (cohort, assignment, include_solution?)
  A->>CT: freeze cohort template from T (main only)
  A->>S: generate slug-handle per student + add collaborator
  opt include_solution ticked
    A->>S: push template's solution branch (solution/ folder) into each
  end
  Note over T,S: solutions live on the solution branch — never shipped by default
```

### Student onboarding

```mermaid
sequenceDiagram
  actor St as Student
  participant W as welcome, Join issue
  participant O as onboard.yml
  participant R as classroom-config roster
  St->>W: open Join issue (student id + email + GitHub handle)
  O->>R: match + verify against the private roster
  O->>St: grant org membership + students-team read
  Note over O,St: "Enroll student" is the faculty override (type a handle)
```

## Dynamic dropdowns

`workflow_dispatch` dropdowns are static YAML and can't depend on another input, so **Refresh
actions** regenerates them from live state and re-pushes the workflows (no cron, no app):

```mermaid
flowchart LR
  R["Refresh actions"] --> D["regenerate dropdowns"]
  R --> E["re-seed run-from-repo buttons into content repos"]
  R --> S["propagate repo secret to private content repos"]
  R --> P["rebuild profile READMEs"]
```

- **cohort_org** - from the `.github/cohort-courses-pages.yml` registry.
- **cohort_repo** - the cohort's content repos, with `materials` as the default.
- **week** - the source materials repo's `lectures/week-N/` folders (run-from-repo copy); the
  central `.github` copy uses a free-text week, since it can't depend on the chosen source repo.
- **source_repo** (central only) / **assignment** - the course org's content / `assignment-*` repos.

## Cohort website

Every cohort gets an **auto-deployed website** at `<cohort-org>.github.io`, generated from
`course-website-template` by `scaffold_site` during Bootstrap cohort. `site.py` then
**regenerates its content from the live org structure** on every release (and via manual
**Sync site**): the schedule lists released weeks + assignment due dates + MidTerm/Final exams;
lecture entries link the actual released files; assignment briefs come from each template's
README; instructor/TA cards come from the `instructors` / `teaching-assistants` teams; the
course name/semester come from the org metadata.

## Course website (open courseware)

A course can **optionally** publish a **public** site at `<course-org>.github.io` via the
manual **Publish course website** action (`site.sync_public_site`). It reuses the same
`course-website-template` + `scaffold_site`, but differs from the cohort site in one
decisive way: the cohort site *links* to files in private repos (404 for non-members, by
design), whereas the course `course-materials-*` repos are private too, so the public site
**hosts the shared files itself** under `public-materials/<source-repo>/week-N/...` (Jekyll
serves any path not starting with `_`) and links to those site-relative URLs.

- **Lectures** are always hosted; **readings** are either a text-only reading list
  (`reading-list` - citations shown, no files, copyright-safe) or hosted + linked
  (`actual-readings`). `none` skips readings.
- **Lectures + readings only** - no assignments or exam rows.
- **Opt-in + manual**: the first run scaffolds the site, later runs re-sync the chosen
  materials repo; served files are namespaced per source repo so several years coexist.
  Releases and refresh **never** touch it, so a public site only exists, and only updates,
  when faculty run the action.

## Bot lifecycle — setup & rotation

Standing up the bot, and rotating its token.

```mermaid
flowchart TD
  A["1 · Create hertie-dsl-bot<br/>own email + 2FA"] --> B["2 · Mint classic PAT<br/>repo + admin:org + workflow"]
  B --> C["3 · Invite bot as Owner of each course/cohort org<br/>+ MEMBER of hertie-data-science-lab (bot accepts)"]
  C --> D["4 · Set DSL_BOT_TOKEN = bot PAT<br/>in the CENTRAL repo (UI)"]
  D --> E["5 · Run Bootstrap (+ Refresh) per org<br/>→ propagates the token"]
  E --> F["6 · Verify green + bot-attributed"]
```

**Rotation:** mint a fresh PAT (step 2), set it in the central repo (step 4), re-run
Bootstrap + Refresh (step 5), verify (step 6), then **revoke the previous PAT last**. Set a
PAT expiry so rotation is forced.

**Hard rules** (ordering is not optional):

- **Owner before token.** The bot must be Owner of an org *before* its PAT has admin there -
  invite + accept (step 3) before propagating (step 5). GitHub has no API to force-add a
  member, so the bot's invite must be accepted once.
- **Bot must be a member of the central org.** The central Bootstrap action's `check-team`
  gate reads `hertie-data-science-lab`'s `faculty`/`admin` teams **under `DSL_BOT_TOKEN`**, so
  the bot's own account has to be a **member** of `hertie-data-science-lab` to see those
  (closed) teams - otherwise the gate 404s on the lookup and **denies everyone**. Add the bot
  as a member of the central org once (it doesn't need to be an owner there).
- **Swap central only after a one-org test.** Setting the central secret (step 4) doesn't
  touch existing org secrets - they stay until re-propagated - so it's safe; but prove it on
  one org first.
- **Never paste a token into chat, PRs, or issues.** Set it *only* via the GitHub Secrets UI.
  A token that is exposed anywhere must be **revoked and reissued** immediately.
- **When rotating, revoke the previous PAT last** - only after *every* org verifies green
  under the new one, or automation breaks mid-rotation.

## Code map

Self-contained - workflows + their Python implementation live in this repo.

- `.github/workflows/` - `bootstrap-org` (+ the legacy create-tier); the faculty workflows are
  rendered + seeded into the course/cohort orgs, not kept here.
- `dsl_course/` - the package:
  - `bootstrap_course` - configure a course or (`--cohort`) cohort org; grant button access; propagate the secret.
  - `seed` - render the workflows (central + run-from-repo), discover dropdown options, refresh.
  - `release` - publish a week's materials (+ optional syllabus/README) into a cohort repo.
  - `assign` - freeze a cohort assignment template, then fan out per-student repos.
  - `scaffold` - create structured materials / assignment repos + the website (cohort or course).
  - `site` - regenerate the cohort website (`sync_site`) and the public course website (`sync_public_site`) from the live org structure.
  - `sync_roster` - enrol / materialise team access from `students.csv`.
  - `roster` - read the per-cohort `students.csv`.
  - `utils` - shared `gh`/git helpers with rate-limit backoff.
  - `new_semester` / `post_migrate` / `bootstrap_org` / `list_orgs` - legacy create-tier
    (older course-side model; the next slimming target).
- `templates/welcome/` - the cohort onboarding workflow + Join issue form.
