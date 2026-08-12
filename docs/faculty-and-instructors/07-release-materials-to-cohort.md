# Release materials to a cohort

Open sessions up to a cohort, from any section of your materials repo (lectures, readings, …).

## Prerequisites

- A course [materials repo](02-add-materials-to-course.md) with the sessions you want to release.
- A bootstrapped [cohort](04-new-cohort-org.md).

## The schedule normally does this

A `deploy` entry in the cohort's `schedule.yml` releases exactly what the button below does, at
the datetime you give it: [Schedule releases](06-schedule-releases.md). Use the button for a
demo, an ad-hoc release, or recovery while you fix the YAML.

## Release materials (manual)

Use the materials repo's own **Release materials** button (it knows that repo's sections and
sessions), or the course `.github` →
[Release materials](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/release-materials.yml):

- `cohort_org` = `DSL-Demo-f2026`
- per section, `release_<section>` (checkbox, default **on**) and `<section>_path` (free text).
  Leave the path blank to use a cohort repo named after the section; type `repo/subpath`
  (e.g. `materials/lectures`) to nest it, so two sections can share one repo. Repos are created
  as needed, private, with `students` + `auditors` given read.
- `sessions` = comma and/or range list, e.g. `1,3,5-7` (the field description lists the sessions
  found in the repo)
- `include_root_files` (default **off**) - also release the syllabus file(s) + source README

Re-releasing is a no-op, so it's safe to re-run.

> **Only the first 3 sections (alphabetically) get buttons.** For a 4th or later section -
> **Refresh actions** logs which were left out - release it with
> `python3 -m dsl_course.release --destinations "section=repo/subpath,..."`.

## The site

Releases trigger **Sync site** for you, as does a push to `classroom-config/schedule.yml`, plus
a daily cron. Run
[Sync site](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/sync-site.yml)
by hand only when you don't want to wait - e.g. after editing `classroom-config/people.yml` or a
file inside an already-released repo.

## Next

- [Add an assignment](03-add-assignment-to-course.md), then [release it](08-release-assignment-to-cohort.md).
- [Release code](10-release-code.md) - a growing package, disclosed in phases (not session folders).

---
**Demo:** released into [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026); site at
`dsl-demo-f2026.github.io`.
