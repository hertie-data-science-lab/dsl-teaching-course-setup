# The bot & token reference

The credential every button runs under: the bot account, its exact permissions, and the
token / secret model. Who may run what is elsewhere - **[course-admin.md](course-admin.md)**
(a single course's buttons) and **[central-admin.md](central-admin.md)** (central DSL
authority, plus the bot's setup/rotation procedure). For **how the system is built and how the
pieces move** - diagrams, the workflow sequences, the token-propagation flow, and the code map -
see **[architecture.md](architecture.md)**. **Faculty & instructors delivering a course don't
need any of these** - see the [root README](../../README.md) for the button workflow.

## The bot account

Every button runs under **one** credential, `DSL_BOT_TOKEN`. **Faculty & instructors never hold
or see it**: they trigger the Actions buttons, which run server-side under the org secret.

The bot is the shared service account **`hertie-dsl-bot`**: one GitHub account with its own email
+ 2FA, added as **Owner** of every course/cohort org; its classic PAT is `DSL_BOT_TOKEN`. One
account, one token, rotated centrally; nobody shares the password. This is the account to
**invite as Owner** of each new org. Standing it up and rotating it:
[CENTRAL ADMIN → Bot lifecycle](central-admin.md#bot-lifecycle---setup--rotation).

**Exact permissions.** It must be an **Owner** of every course and cohort org, and its token
must carry:

| Classic PAT scope | Covers |
| --- | --- |
| `repo` | create + read/write repos incl. **private**; contents; generate-from-template; topics; repo settings + repo secrets |
| `admin:org` | org **membership** + **teams** (invite students, manage `students`/`auditors`/`instructors`/`course-admin`); org **settings** (2FA); **org secrets** |
| `workflow` | write the seeded workflow files (the buttons) |

A classic PAT spans both org tiers, which is what cross-org automation needs.

## Who can run which action

Two **separate** populations, each with its own page - keep them distinct:

- **Who may provision orgs** (the central **Bootstrap Course Org** button): the `faculty`/`admin`
  teams in `hertie-data-science-lab` → **[central-admin.md](central-admin.md)**.
- **Who may run a specific course's buttons**: that course org's own `course-admin` team, or a
  cohort's `instructors-<tag>` team → **[course-admin.md](course-admin.md)**.

Both gate on **repo permission** on the repo the workflow runs in
(`workflows_render._CHECK_TEAM`, `bootstrap-org.yml`'s `check-team`), which is also why GitHub
only shows "Run workflow" to write+ users.

## Token

Every workflow runs under **`secrets.DSL_BOT_TOKEN`**. On the **GitHub Free plan, org secrets
don't reach private repos** - so bootstrap propagates it as an *org* secret (for the public
`.github`/`welcome`) **and** Refresh sets it as a *repo* secret on each private content repo. On
Team/Enterprise that propagation is unnecessary. Full flow:
[ARCHITECTURE → Token & secret propagation](architecture.md#token--secret-propagation).
