# Course admin - running an existing course

You've been made an admin of a course org that's already running. This page is what that
membership means, how access is declared (and revoked), and where the teams are. For the
button-by-button walkthroughs see the
**[runbooks](../faculty-and-instructors/README.md)**; if you're new to the platform start at
**[START-HERE](../START-HERE.md)**. Every input file and its exact schema is in
**[required-input-schema.md](../faculty-and-instructors/required-input-schema.md)**.

**Start by running [Show status](../faculty-and-instructors/actions-reference.md) on each cohort** (the
course org's `.github` Actions tab → **Show status**). It's read-only and prints a per-cohort
checklist - identity, people, schedule + release plan, roster, teams, grades - with edit links
for anything missing. That is the fastest read of what state you've inherited.

## What course-admin membership grants

Membership of **that course org's own `course-admin` team** grants admin on the course org's
`.github` repo, which is what makes **every** button in that org's Actions tab visible and
runnable - across all its cohorts. GitHub only shows "Run workflow" to write+ users, so without
this (or an `instructors-<tag>` grant, below) you'd see nothing.

It is scoped to **one course**. Central `hertie-data-science-lab` membership is a separate
authority that gates only org *provisioning* (see [central-admin.md](central-admin.md)); it
grants nothing here. Teams are org-scoped, so cross-org grants aren't possible anyway.

The cron-driven workflows (**Scheduled release**, and the automatic paths of **Sync site** /
**Sync membership** / **Publish course website**) skip the access gate - a scheduled run has no
actor.

> **Publish course website** carries an editorial responsibility: `actual-readings` mode hosts
> the reading files publicly, so only publish what you hold the rights to share - use
> `reading-list` for copyrighted readings.

## How access is declared

Access is **declared in config files and reconciled**, not clicked. **Sync membership** runs on
push to those files and on a daily cron, adding *and removing* to match:

- **Admin rights** (course-wide, every cohort): the course org's `.github/dsl-course.yml`
  `people:` → `course_admins`, or the **`admin`** input at bootstrap. Deleting an entry revokes
  access on the next sync.
- **Push rights** (one cohort's content only): that cohort's own
  `classroom-config/people.yml` → `instructors` / `teaching_assistants`. Removing someone there
  revokes both their cohort-team and their `instructors-<tag>` access.

**Hand-added members get reverted.** Adding someone to `course-admin`, a cohort's `instructors`
team, or `instructors-<tag>` through the GitHub Teams UI survives only until the next Sync
membership run, which removes anyone the config doesn't name. Edit the file instead.

Everyone added this way accepts a one-time org invite (membership shows `pending` until they
do), after which the buttons appear in their Actions tab. Students never get write, so never
see them.

## The three `instructors` teams

Three different teams share the word "instructors" - they are not interchangeable:

| Team | Lives in | Declared by | Grants |
| --- | --- | --- | --- |
| `instructors` | a **cohort** org | that cohort's `classroom-config/people.yml` | cohort-org membership for that year's instructors/TAs; reconciled |
| `instructors-<tag>` | the **course** org | the same `people.yml` (tag = e.g. `f2026`) | push on `.github` + that tag's content repos, i.e. the buttons for that cohort; reconciled |
| `instructors` | the **course** org (generic) | nothing - manual | a rare, permanent escape hatch |

The generic course-org `instructors` team is the exception: nothing reconciles it, so a manual
add sticks until manually removed - useful for a guest nobody wants to type into a config file.
But it is **invisible to every config file and to Show status**, so use it sparingly and record
who's on it elsewhere. FA (faculty assistant) and TA access should go through `people.yml`.

## Related

- [central-admin.md](central-admin.md) - central DSL-org authority: who can create orgs, the bot
  and its rotation, the org inventory.
- [admin-setup.md](admin-setup.md) - the bot account, its PAT scopes, and the token model.
- [architecture.md](architecture.md) - how the pieces move.
