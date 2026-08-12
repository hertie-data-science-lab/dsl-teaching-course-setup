# Manage the teaching team

Give an instructor, TA, faculty assistant or guest lecturer access to a course - permanently or
**for a fixed window** - and take it away again.

Access is **declared in a config file and reconciled**: you edit a file, commit & push, then the
**Sync membership** action in the cohort's `.github` materialises the GitHub teams. Revisit this page whenever the teaching team
changes; it is not a one-off step.

> NB: membership of the central `hertie-data-science-lab` org grants **nothing** here. It gates only
> [**Bootstrap Course Org**](01-new-course-org.md). All those involved in a course's delivery must
> still be declared in one of the two files below before they can push to a course or release
> anything from it.

## Two levels - pick the right one

| You want them to… | Declare them in | Level | They get |
|---|---|---|---|
| administer the **whole course**, every cohort, indefinitely | course org `.github/dsl-course.yml` → `people:` `course_admins` | **course** - once, for all years | `course-admin` (admin) on the course org **and** every cohort org |
| push materials/assignments for **one year** and run the release buttons | that cohort's `classroom-config/people.yml` → `instructors` / `teaching_assistants` | **cohort** - per year | cohort org `instructors` team + course org `instructors-<tag>`: push on `.github` and on every course-org repo named `*-<tag>` |

`course_admins` is deliberately **course-level**: a course director and their FA isn't to be re-declared every
year, and their rights need to span every cohort. One-off instructors and TAs are deliberately
**cohort-level**: they change most years, so each cohort's list stands alone.

**Prefer the cohort file** for anyone who isn't running the course across multiple years. It is per-year, self-retiring,
and it also supplies the deployed site's staff cards with rich display and information.

> While the **course** org's `dsl-course.yml` *does* accepts `instructors:` / `teaching_assistants:`,
> these they are **display-only** cards for the optional public course site and grant no
> access at all. In general TAs go in the **cohort org's** `classroom-config/people.yml`.

Full model - every team and what it reaches: [`access-reference.md`](access-reference.md).

## Prerequisites

- A bootstrapped [course org](01-new-course-org.md), and for the cohort route a bootstrapped
  [cohort](04-new-cohort-org.md).
- Push on the file you're editing: `course-admin` membership (either file), or an existing
  `instructors-<tag>` seat (that cohort's `people.yml`).
- Their **GitHub handle**. That is the only required field; everything else is display.

## Add someone

1. **Edit the file.**

   Cohort org → `classroom-config` → `people.yml` (this year's teaching team):

   ```yaml
   people:
     instructors:
       - github_handle: "janedoe"        # required - this is what grants access
         name: "Prof. Jane Doe"          # optional, from here down: cohort site card
         title: "Professor of ..."
         photo: "https://.../jane.jpg"
         url: "https://.../jane"
     teaching_assistants:
       - github_handle: "anOther"
   ```

   Or course org → `.github` → `dsl-course.yml` (course-wide admin):

   ```yaml
   people:
     course_admins:
       - github_handle: "janedoe"
   ```

2. **Commit to `main`.** The push dispatches **Sync membership** automatically - no button to
   click. It reconciles fully (adds *and* removes) to match the file.

3. **They accept the org invite.** Membership shows `pending` in the Teams UI until they do; the
   buttons appear in their Actions tab afterwards. Students never have write, so they never see
   them.

## Time-box it (`start` / `end`)

Every person entry, in **either** file, takes two optional ISO dates. This is how you give a guest
lecturer, a visiting faculty member or a fixed-term TA access **for a limited time** with nothing
to remember later:

```yaml
people:
  teaching_assistants:
    - github_handle: "anOther"
      start: "2026-09-01"      # optional - omit for "active immediately"
      end: "2027-01-31"        # optional - omit for "indefinite"
```

Access is granted from `start` and revoked after `end`, both inclusive. 

>Because every sync is a full reconcile, a lapsed `end` prunes them exactly as a deleted entry would - **no manual removal step needed, and no way to forget**. Leave the entry in the file afterwards: it doubles as the record of who taught what, and re-granting next year is a date edit.

Worked example: [`example-course/cohort-org/people.yml`](../example-course/cohort-org/people.yml)
declares two TAs for the September-to-January window.

## Remove someone / end access early

- **Time-boxed:** do nothing, or bring the `end` date forward.
- **Immediately:** delete their entry (or set `end` to yesterday) and push. The dispatch on that
  push revokes within a minute or two.
- **Do not use the GitHub Teams UI.** A hand-add to `course-admin`, `instructors` or
  `instructors-<tag>` is reverted by the next sync, and a hand-*removal* of someone still named in
  the config is re-added. The file is the truth.

## When changes take effect

| Trigger | Latency |
|---|---|
| You edit and push `people.yml` / `dsl-course.yml` | **immediate** - the push dispatches Sync membership |
| A `start` / `end` date rolls over with no edit | up to **~24h** - nothing pushes on a date change, so the daily cron applies it |
| You run **Sync membership** by hand (course `.github` → Actions) | immediate - use this if you don't want to wait for the cron |

> Cohorts bootstrapped before `people.yml` joined `dispatch-sync.yml`'s watched paths wait for the
> cron even on an edit. Re-run **Bootstrap cohort** once to fix it: it refreshes the dispatchers
> on every run and never overwrites your `classroom-config` files.

## What the access actually reaches

`instructors-<tag>` gets:
1. **push** on the course org's **`.github`** - which is what makes the central buttons (Release materials, Release assignment, Refresh actions, Show status…) visible and runnable for them
2. every course-org repo whose **name ends their associated `-<tag>`** (`course-materials-f2026`, `assignment-1-f2026`, `lecture-code-f2026`).

So a TA on f2026 can `git push` labs into the course org level `course-materials-f2026`
([02](02-add-materials-to-course.md)) and then release them to the cohort org
([08](08-release-materials-to-cohort.md)) themselves.
>The release runs server-side as the bot, so they need no cohort-org rights for it.

The suffix match is the whole rule: a course-org repo **without** the year tag in its name is not
covered. Name per-year content repos `<thing>-<tag>`. A repo scaffolded today is picked up by the
next sync - run **Sync membership** if you want it now.

Cohort-side they also get write on `classroom-config` and `welcome`, so they can edit the roster,
schedule and team lists.

## Check it worked

- **Show status** (course `.github` → Actions, pick the cohort) lists the declared people and
  flags gaps. Note the generic course-org `instructors` team is a manual escape hatch and is
  **invisible** to it - route TAs through `people.yml` so they show up.
- Course org → **Teams** → `instructors-<tag>` / `course-admin` shows live membership, `pending`
  until the invite is accepted.
- The **Sync membership** run log lists every add and removal it made.

Access here is a rotation mechanism, not a hard security boundary: `instructors-<tag>` can push to
`.github`, so it can edit `dsl-course.yml` and hence its own grants. Fine for trusted staff -
details and the mitigation in [`access-reference.md`](access-reference.md#rules-that-catch-people-out).

## Next

- [Enrol students](06-enrol-students-to-cohort.md) - the other half of populating a cohort.
- [Add materials to the course](02-add-materials-to-course.md) - what a new TA usually does first.
- Field-by-field schemas: [DEPLOYMENT-CHECKLIST](DEPLOYMENT-CHECKLIST.md#peopleyml).

---
**Demo:** [`DSL-Demo-f2026/classroom-config/people.yml`](https://github.com/DSL-Demo-f2026/classroom-config/blob/main/people.yml)
→ [`DSL-Demo-Course-E1234` teams](https://github.com/orgs/DSL-Demo-Course-E1234/teams).
