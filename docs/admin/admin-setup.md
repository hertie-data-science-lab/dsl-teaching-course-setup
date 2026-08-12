# The bot & token reference

The credential every button runs under: the bot account, its permissions, and the token/secret
model. Who may run what is elsewhere - **[course-admin.md](course-admin.md)** (a course's
buttons) and **[central-admin.md](central-admin.md)** (central DSL authority, plus bot
setup/rotation). How the system is built: **[architecture.md](architecture.md)**. **Faculty &
instructors delivering a course don't need this page** - see the
[root README](../../README.md).

## The bot account

Every button runs under **one** credential, `DSL_BOT_TOKEN`. **Faculty & instructors never hold
or see it**: they trigger the Actions buttons, which run server-side under the org secret.

The bot is the shared service account **`hertie-dsl-bot`**: one GitHub account with its own email
+ 2FA, added as **Owner** of every course/cohort org; its classic PAT is `DSL_BOT_TOKEN`. Invite
this account as Owner of each new org. Standing it up and rotating it:
[CENTRAL ADMIN → Bot lifecycle](central-admin.md#bot-lifecycle---setup--rotation).

**Required permissions.** The bot must be an **Owner** of every course and cohort org, and its
token must carry:

| Classic PAT scope | Covers |
| --- | --- |
| `repo` | create + read/write repos incl. **private**; contents; generate-from-template; topics; repo settings + repo secrets |
| `admin:org` | org **membership** + **teams** (invite students, manage `students`/`auditors`/`instructors`/`course-admin`); org **settings** (2FA); **org secrets** |
| `workflow` | write the seeded workflow files (the buttons) |

## Who can run which action

Two **separate** populations - keep them distinct:

- **Who may provision orgs** (the central **Bootstrap Course Org** button): the `faculty`/`admin`
  teams in `hertie-data-science-lab` → **[central-admin.md](central-admin.md)**.
- **Who may run a specific course's buttons**: that course org's own `course-admin` team, or a
  cohort's `instructors-<tag>` team → **[course-admin.md](course-admin.md)**.

Both gate on repo permission, which is also why GitHub only shows "Run workflow" to write+ users.

## Token

Every workflow runs under **`secrets.DSL_BOT_TOKEN`**. On the **GitHub Free plan, org secrets
don't reach private repos** - so bootstrap propagates it as an *org* secret (for the public
`.github`/`welcome`) **and** Refresh sets it as a *repo* secret on each private content repo. On
Team/Enterprise that propagation is unnecessary. Full flow:
[ARCHITECTURE → Token & secret propagation](architecture.md#token--secret-propagation).
