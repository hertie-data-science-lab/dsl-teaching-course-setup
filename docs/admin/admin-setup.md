# Admin & technical reference

Operational detail behind the faculty & instructors buttons: the bot credential, its exact permissions,
the token / secret model, and who-can-run access. For **how the system is built and how the
pieces move** - diagrams, the workflow sequences, the token-propagation flow, the bot
lifecycle, and the code map - see **[architecture.md](architecture.md)**. **Faculty & instructors
delivering a course don't need either** - see the [root README](../../README.md) for the
button workflow.

## The bot account

Every button runs under **one** credential, `DSL_BOT_TOKEN`. **Faculty & instructors never hold
or see it**: they trigger the Actions buttons, which run server-side under the org secret.

The bot is the shared service account **`hertie-dsl-bot`**: one GitHub account with its own email
+ 2FA, added as **Owner** of every course/cohort org; its classic PAT is `DSL_BOT_TOKEN`. One
account, one token, rotated centrally; nobody shares the password. This is the account to
**invite as Owner** of each new org. Standing it up and rotating it:
[ARCHITECTURE → Bot lifecycle](architecture.md#bot-lifecycle--setup--rotation).

**Exact permissions.** It must be an **Owner** of every course and cohort org, and its token
must carry:

| Classic PAT scope | Covers |
| --- | --- |
| `repo` | create + read/write repos incl. **private**; contents; generate-from-template; topics; repo settings + repo secrets |
| `admin:org` | org **membership** + **teams** (invite students, manage `students`/`auditors`/`instructors`/`course-admin`); org **settings** (2FA); **org secrets** |
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
- **Who may run a specific course's buttons** (all of them): members of **that course org's own**
  `course-admin` (admin) team, or any cohort's own **`instructors-<tag>`** team (write, scoped to
  that tag's content repos + `.github`). These gate on **repo permission** on the repo they run
  in (`workflows_render._CHECK_TEAM`); bootstrap grants `course-admin` admin on `.github`, and
  `sync_faculty` grants each `instructors-<tag>` team push on `.github` + that tag's repos as
  soon as a cohort declares an instructor for that tag. GitHub only shows "Run workflow" to
  write+ users, so without one of these grants only the org owner can run anything. The
  cron-driven workflows (**Scheduled release**, and the automatic paths of **Sync site** /
  **Sync membership** / **Publish course website**) skip the gate - a scheduled run has no actor.

  > **Publish course website** carries an editorial responsibility: `actual-readings` mode hosts
  > the reading files publicly, so only publish what you hold the rights to share - use
  > `reading-list` for copyrighted readings.

**Access is split by role.** Central `hertie-data-science-lab` members are *not* mirrored into
course orgs - nobody is added to a course they don't teach, and teams are org-scoped so cross-org
grants aren't possible anyway. To give someone a course's buttons:

- **Admin rights** (course-wide, every cohort): declare them in the course org's
  `.github/dsl-course.yml` `people:` → `course_admins`, or at bootstrap pass the **`admin`**
  input (course admin handle(s)). Either way it's reconciled (add + remove) by **Sync
  membership** - a deleted entry revokes access on the next sync.
- **Push rights** (a specific cohort's content only): declare them in that cohort's own
  `classroom-config/people.yml` → `instructors`/`teaching_assistants`. Also reconciled -
  removing them from that file revokes both their cohort-team and `instructors-<tag>` access.
- **A permanent, undeclared exception** (rare - e.g. a guest nobody wants to type into a config
  file): add them directly to the course org's generic **`instructors`** team via the Teams page.
  Nothing reconciles that team, so the add sticks until manually removed - but it's invisible to
  **Show status** and every config file, so use it sparingly and record who's on it elsewhere.

They then accept a one-time org invite (membership shows `pending` until they do), after which
the buttons appear in their Actions tab. Students never get write, so never see them.

## Token

Every workflow runs under **`secrets.DSL_BOT_TOKEN`**. On the **GitHub Free plan, org secrets
don't reach private repos** - so bootstrap propagates it as an *org* secret (for the public
`.github`/`welcome`) **and** Refresh sets it as a *repo* secret on each private content repo. On
Team/Enterprise that propagation is unnecessary. Full flow:
[ARCHITECTURE → Token & secret propagation](architecture.md#token--secret-propagation).
