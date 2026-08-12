# Release materials to a cohort

Open sessions up to a cohort, from any releasable section (lectures, readings, or anything
else your materials repo has). Every release also triggers **Sync site**, so the cohort
website stays current automatically.

## Prerequisites

- A course [materials repo](02-add-materials-to-course.md) with the sessions you want to release.
- A bootstrapped [cohort](04-new-cohort-org.md).

## The schedule normally does this

A `deploy` entry in the cohort's `schedule.yml` `materials_releases:` plan copies exactly what
the button below copies, at the datetime you gave it - and the hourly cron runs the whole term
that way. Write the plan once: [Schedule releases](06-schedule-releases.md).

**Everything below is the manual override** - for a demo, an early or ad-hoc release, or
recovery while you fix the YAML.

## Release materials (manual)

Course `.github` → **Actions** →
[Release materials](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/release-materials.yml),
or - better - the materials repo's own Release button, which knows the repo's actual sections
and sessions:

- `cohort_org` = `DSL-Demo-f2026`
- a pair of fields per section discovered in the repo (up to 3 - see "Section limit"):
  `release_<section>` (checkbox, default **on**) and `<section>_path` (free text). Leave the
  path blank to create/use a repo named after the section, at its root; type `repo/subpath`
  (e.g. `materials/lectures`) to nest it under a folder there instead, so two sections can
  share one repo. Repos are created automatically.
- `sessions` = a comma and/or range list, e.g. `1,3,5-7` (Actions has no multi-select widget;
  the field description lists the sessions discovered in the repo)
- `include_root_files` (default **off**) - also release the syllabus file(s) + source README

It copies every routed `<section>/<NN>_.../` folder matching each chosen session into its
target cohort repo (**private**, `students` + `auditors` read), nested under its destination
subpath. Only released sessions appear; idempotent, so re-releasing is a no-op.

**Section naming**: sections are just top-level directories with ordinal-prefixed subfolders -
name them however you like. `lectures/`, `readings/`, `labs/` is convention, not a rule.

**Section limit**: only the first 3 sections (alphabetically) get buttons - Actions caps a
workflow at 10 inputs. A 4th+ isn't silently dropped: **Refresh actions** logs which got left
out, and you release those with `python3 -m dsl_course.release --destinations
"section=repo/subpath,..."`. Why 3, and what the central button does differently:
[ARCHITECTURE → Dynamic dropdowns](../admin/architecture.md#dynamic-dropdowns).

## The site

Releases call **Sync site** for you, and a push to `classroom-config/schedule.yml` triggers it
too. A daily cron re-syncs every cohort as a catch-all. Run
[Sync site](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/sync-site.yml)
by hand only when you don't want to wait for that - e.g. after editing
`classroom-config/people.yml` (instructor/TA cards) or a file inside an already-released repo.

## Next

- [Add an assignment](03-add-assignment-to-course.md), then [release it](08-release-assignment-to-cohort.md).
- [Release code](10-release-code.md) - a growing package, disclosed in phases (not session folders).

---
**Demo:** released into [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026); site at
`dsl-demo-f2026.github.io`.
