# Configure the cohort website

> Every cohort has an auto-deployed site at `<cohort-org>.github.io`, regenerated from the org's
> config files.

You never edit what the site shows - you edit the file it reads, and it re-syncs itself.

## What you set, and where

| To change | Edit | Field |
|---|---|---|
| The blurb under the title | course org `.github/dsl-course.yml` | `course_description` |
| Course title + code | course org `.github/dsl-course.yml` | `course_name`, `course_code` - **not** `org_name`, which the site never reads |
| Semester + year | *nothing to set* | inferred from the cohort org's `fYYYY`/`sYYYY` tag (`DSL-Demo-f2026` → "Fall 2026") |
| Instructor / TA cards | cohort `classroom-config/people.yml` ([05](05-manage-teaching-team.md)) | every field you declare displays, bar `github_handle`, `start`, `end` (access only); a card needs a `name` to appear at all |
| Staff photos | site repo `<cohort-org>.github.io` | commit the image under `_images/pp/`, then `photo: /_images/pp/jane.jpg` |
| Schedule rows, exams, assignment due dates | cohort `classroom-config/schedule.yml` ([07](07-schedule-releases.md)) | `materials_releases`, `exams`, `assignments` |
| Materials links | *nothing to set* | they appear as you [release](08-release-materials-to-cohort.md) |

## What never to touch

These are rewritten on every sync. A hand edit is lost **silently** - no error, no warning.

| In the site repo | What happens |
|---|---|
| `_lectures/`, `_assignments/`, `_events/` | each directory is **deleted and rebuilt** every sync - a file you drop in here vanishes |
| `_data/people.yml` | overwritten from `classroom-config/people.yml` |
| `_config.yml` keys `course_name`, `course_code`, `course_semester`, `course_description`, `github_org` | overwritten from the sources in the table above |

**Everything else in the site repo is yours and survives forever** - a custom `index.md` or any
other page, CSS/SCSS, `_layouts/`, further `_data/*.yml`, assets, `_images/`. Only the surfaces
listed above are ever written.

## When it redeploys

| Trigger | Latency |
|---|---|
| Push to `classroom-config/schedule.yml` or `people.yml` | immediate |
| **Release materials** / **Release assignment** button | immediate, in the same run |
| A scheduled release firing | within that hourly tick |
| Push to course org `.github/dsl-course.yml` | immediate - and re-syncs **every** cohort site |
| **Sync site** button, course org `.github` | on demand |
| Anything else (e.g. editing a file inside an already-released repo) | the daily cron, **06:00 UTC** |

## Next

- [Manage the teaching team](05-manage-teaching-team.md) - where the staff cards come from.
- [Schedule releases](07-schedule-releases.md) - where the dates come from.
- Field-by-field schemas: [DEPLOYMENT-CHECKLIST](DEPLOYMENT-CHECKLIST.md#dsl-courseyml).

---
**Demo:** [`dsl-demo-f2026.github.io`](https://dsl-demo-f2026.github.io/), fed by
[`DSL-Demo-Course-E1234/.github/dsl-course.yml`](https://github.com/DSL-Demo-Course-E1234/.github/blob/main/dsl-course.yml)
and [`DSL-Demo-f2026/classroom-config`](https://github.com/DSL-Demo-f2026/classroom-config).
