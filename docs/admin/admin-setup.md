# Admin & technical reference

Operational detail behind the faculty & instructors buttons: the bot credential, its exact permissions,
the token / secret model, and who-can-run access. For **how the system is built and how the
pieces move** - diagrams, the workflow sequences, the token-propagation flow, the bot
lifecycle, and the code map - see **[architecture.md](architecture.md)**. **Faculty & instructors
delivering a course don't need either** - see the [root README](../../README.md) for the
button workflow.

## The bot account

Every button runs under **one** credential, `DSL_BOT_TOKEN` - "the bot". **Faculty & instructors never
hold or see it**: they trigger the Actions buttons, which run server-side under the org
secret. So a single bot serves the whole DSL - faculty & instructors use it *indirectly*.

The bot is the shared service account **`hertie-dsl-bot`**: one GitHub account with its own
email + 2FA, added as **Owner** of every course/cohort org; its classic PAT is
`DSL_BOT_TOKEN`. One account, one token, rotated centrally; nobody shares the password. The
account to **invite as Owner** of each new org (course setup step 2) is `hertie-dsl-bot` -
standing it up and rotating it is the
[ARCHITECTURE → Bot lifecycle](architecture.md#bot-lifecycle--setup--rotation).

**Exact permissions.** It must be an **Owner** of every course and cohort org, and its token
must carry:

| Classic PAT scope | Covers |
| --- | --- |
| `repo` | create + read/write repos incl. **private**; contents; generate-from-template; topics; repo settings + repo secrets |
| `admin:org` | org **membership** + **teams** (invite students, manage `students`/`instructors`/`teaching-assistants`); org **settings** (2FA); **org secrets** |
| `workflow` | write the seeded workflow files (the buttons) |

A classic PAT spans both org tiers, which is what cross-org automation needs.

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
  materials/assignment, Sync membership, Bootstrap cohort, Sync site, Publish course website,
  Refresh actions): members of **that course org's own** `course-admin` (admin) team, or any
  cohort's own **`instructors-<tag>`** team (write, scoped to that tag's own content repos +
  `.github`). (**Publish course website** carries an editorial responsibility:
  `actual-readings` mode hosts the reading files publicly, so only publish materials you hold
  the rights to share - use `reading-list` for copyrighted readings.) The day-to-day buttons
  gate on **repo permission** on the repo they run in (`seed.py` `_CHECK_TEAM`); bootstrap
  grants `course-admin` admin on `.github`, and `sync_faculty` grants each `instructors-<tag>`
  team push on `.github` + that tag's repos as soon as a cohort declares any instructor for
  that tag. GitHub only shows the "Run workflow" button to write+ users, so without one of
  these grants only the org owner can run anything.

**Access is split by role, not per-course-generically.** Central `hertie-data-science-lab`
faculty & instructors are *not* mirrored into course orgs (no one is added to a course they don't teach;
teams are org-scoped, so cross-org grants aren't possible anyway). To give someone a course's
buttons:

- **Admin rights** (course-wide, every cohort): declare them in the course org's
  `.github/dsl-course.yml` `people:` → `course_admins`, or at bootstrap pass the **`admin`**
  input (course admin handle(s)). Either way it's reconciled (add + remove) by **Sync
  membership** - a deleted entry revokes access on the next sync.
- **Push rights** (a specific cohort's content only): declare them in that cohort's own
  `classroom-config/people.yml` → `instructors`/`teaching_assistants`. Also reconciled -
  removing them from that file revokes both their cohort-team and `instructors-<tag>` access.
- **A permanent, undeclared exception** (rare - e.g. a guest with standing access nobody
  wants to type into a config file): add the person directly to the course org's generic
  **`instructors`** team via the org's Teams page. Unlike the two paths above, nothing
  reconciles this team any more (it predates the per-cohort/tag split), so a manual add here
  sticks until manually removed - a genuine escape hatch, not a bug, but also not visible to
  **Show status** or any config file, so use it sparingly and document who's on it elsewhere.

Either way they accept a one-time org invite (membership shows `pending` until then), after
which the buttons appear in their Actions tab. Students never get write, so never see them.

## Token

All workflows run under **`secrets.DSL_BOT_TOKEN`** (see [The bot account](#the-bot-account)
for which account that is and its exact permissions). On the **GitHub Free plan, org
secrets don't reach private repos** - so bootstrap propagates the token as an *org*
secret (for the public `.github`/`welcome`) **and** Refresh sets it as a *repo* secret on
each private content repo. The token needs cross-org repo admin + members + contents. On
GitHub Team/Enterprise, org secrets reach private repos and this propagation is unnecessary.

## How it works (dropdowns, website, code map)

The dynamic-dropdown regeneration, the cohort-website and public course-website pipelines,
and the repo/code map now live in **[architecture.md](architecture.md)** alongside the
system diagrams and workflow sequences - this doc keeps the operational reference above.
