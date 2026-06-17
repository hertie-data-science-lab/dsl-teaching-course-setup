# Admin & technical reference

Operational detail behind the faculty buttons: the bot credential, its exact permissions,
the token / secret model, and who-can-run access. For **how the system is built and how the
pieces move** - diagrams, the workflow sequences, the token-propagation flow, the bot
lifecycle, and the code map - see **[ARCHITECTURE.md](ARCHITECTURE.md)**. **Faculty
delivering a course don't need either** - see the [root README](../README.md) for the
button workflow.

## The bot account

Every button runs under **one** credential, `DSL_BOT_TOKEN` - "the bot". **Faculty never
hold or see it**: they trigger the Actions buttons, which run server-side under the org
secret. So a single bot serves the whole DSL - faculty use it *indirectly*.

| Model | What "the bot" is | When |
| --- | --- | --- |
| **Personal PAT** | a classic PAT on a maintainer's **own** account (`henrycgbaker`) | **legacy** - demo / bootstrap only, tied to one person; being retired |
| **Shared service account** | one GitHub account **`hertie-dsl-bot`**, with its own email + 2FA, added as **Owner** of every course/cohort org; its PAT is `DSL_BOT_TOKEN` | **current** - the institutional DSL-wide bot; one account, one token, rotated centrally; nobody shares the password |
| **GitHub App** | a **"DSL Course Automation"** App installed on both org tiers - short-lived fine-grained tokens, no static PAT, per-org revocable | end-state (ADR 0010); workflows don't change, only the token source |

The account to **invite as Owner** of each new org (course setup step 2) is **`hertie-dsl-bot`**.
The legacy `henrycgbaker` PAT is being retired - the cutover/rotation runbook is in
[ARCHITECTURE → Bot lifecycle](ARCHITECTURE.md#bot-lifecycle--setup--rotation).

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

Two **separate** populations - keep them distinct:

- **Who may provision orgs** (run the central **Bootstrap Course Org**): members of the
  **`faculty`/`admin`** teams in **`hertie-data-science-lab`** (`bootstrap-org.yml`
  `check-team`). This is a DSL-wide authority - it gates *creating/configuring* any course
  org, and nothing else. It does **not** grant access to any course's buttons.
  The same "write to see the button" rule applies, so as a **one-time setup** the central
  `dsl-teaching-course-setup` repo grants **`faculty` → write**, **`admin` → admin**, and
  its `main` is **branch-protected** (require a PR) so that write can't push to `main`
  directly. Without the grant, only org owners would see the Bootstrap button - team
  membership alone wouldn't surface it.
- **Who may run a specific course's buttons** (Release materials/assignment, New
  materials/assignment, Enroll, Bootstrap cohort, Sync site, Refresh actions): members of
  **that course org's own** `instructors` (write) or `course-admin` (admin) team. The
  day-to-day buttons gate on **repo permission** on the repo they run in
  (`seed.py` `_CHECK_TEAM`), and bootstrap grants those two teams write/admin on `.github`
  (`grant_button_access`). GitHub only shows the "Run workflow" button to write+ users, so
  without that grant only the org owner can run anything.

**Access is per-course - deliberately.** Central `hertie-data-science-lab` faculty are
*not* mirrored into course orgs (no one is added to a course they don't teach; teams are
org-scoped, so cross-org grants aren't possible anyway). To give someone a course's
buttons:

- at bootstrap, pass the **`admin`** input (course admin handle(s)) → added to
  `course-admin`; or
- anytime, add the person to that course org's **`instructors`** team (write) via the org's
  Teams page.

Either way they accept a one-time org invite (membership shows `pending` until then), after
which the buttons appear in their Actions tab. Students never get write, so never see them.

## Token

All workflows run under **`secrets.DSL_BOT_TOKEN`** (see [The bot account](#the-bot-account)
for which account that is and its exact permissions). On the **GitHub Free plan, org
secrets don't reach private repos** - so bootstrap propagates the token as an *org*
secret (for the public `.github`/`welcome`) **and** Refresh sets it as a *repo* secret on
each private content repo. The token needs cross-org repo admin + members + contents.
Production target: a **GitHub App** (fine-grained, short-lived) - or GitHub Team/Enterprise,
where org secrets reach private repos and this propagation is unnecessary.

## How it works (dropdowns, website, code map)

The dynamic-dropdown regeneration, the cohort-website pipeline, and the repo/code map now
live in **[ARCHITECTURE.md](ARCHITECTURE.md)** alongside the system diagrams and workflow
sequences - this doc keeps the operational reference above.
