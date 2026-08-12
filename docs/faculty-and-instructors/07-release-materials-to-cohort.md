# Release materials to a cohort

> Releases materials from the course org (private, historical registry of course materials) -> cohort org (a single instance, available to students)

Open sessions up to a cohort, from any section of your materials repo (lectures, readings, labs…).

## Prerequisites

- A course [materials repo](02-add-materials-to-course.md) with the sessions you want to release.
- A bootstrapped [cohort](04-new-cohort-org.md).

## The schedule normally does this (recommended)

A `deploy` entry in the cohort's `schedule.yml` releases exactly what the button below does, at the datetime you give it: [Schedule releases](06-schedule-releases.md). 
This is the recommended method for releasing materials, as it also creates an entry in the deployed `<course>.github.io` site, so students can clearly understand the course plan in advance.

## Release materials via manual dispatch

In the course org, use either (1) the **materials repo's own** `Release materials` button (it knows that repo's sections and
sessions), or (2) the **course org's`.github` repo's** `release materials` button 

e.g. → [Release materials](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/release-materials.yml):

- `cohort_org` = `DSL-Demo-f2026`
- per section, `release_<section>` (checkbox, default **on**) and `<section>_path` (free text).
  Leave the path blank to use a cohort repo named after the section; type `repo/subpath`
  (e.g. `materials/lectures`) to nest it, so two sections can share one repo. Repos are created
  as needed, private, with `students` + `auditors` given read.
- `sessions` = comma and/or range list, e.g. `1,3,5-7` (the field description lists the sessions
  found in the repo)
- `include_root_files` (default **off**) - also release the syllabus file(s) + source README

Re-releasing is safe to re-run.

## Live updates to the deployed `<course>.github.io` site
- Any released materials will automatically show up in the deployed site (i.e. their release triggers a redeploy).
  - Releases trigger **Sync site** for you, as does a push to `classroom-config/schedule.yml`
  - Plus there's a daily cron)
- You can also run [Sync site](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/sync-site.yml)
by hand only when you don't want to wait for the cron to fire - e.g. after editing `classroom-config/people.yml` or a file inside an already-released repo.

## Next

- [Add an assignment](03-add-assignment-to-course.md), then [release it](08-release-assignment-to-cohort.md).
- [Release code](10-release-code.md) - a growing package, disclosed in phases (not session folders).

---
**Demo:** released into [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026); site at
`dsl-demo-f2026.github.io`.
