# Release materials to a cohort

Open sessions up to a cohort, one at a time, from any releasable section (lectures, readings,
or anything else your materials repo has). Every release also triggers **Sync site**, so the
cohort website stays current automatically.

## Prerequisites

- A course [materials repo](02-add-materials-to-course.md) with the sessions you want to release.
- A bootstrapped [cohort](04-new-cohort-org.md).

## Release materials

Course `.github` → **Actions** →
[Release materials](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/release-materials.yml)
(or the materials repo's own Release button, where `session` is a dropdown and each
discovered section gets its own include checkbox):

- `cohort_org` = `DSL-Demo-f2026`, `cohort_repo` = `materials`, `session` = N
- toggles: one `include_<section>` per section discovered in the materials repo (default
  **on**), plus `include_syllabus` / `include_readme` (default **off**). The central `.github`
  button doesn't know which repo you'll pick until you run it, so it offers a free-text
  `exclude` field instead of per-section checkboxes.

Copies every `<section>/<NN>_.../` folder matching that session into the cohort's **private**
`materials` repo (with `students`-team read), nested under that same folder name. Only
released sessions appear; idempotent (re-running a released session is a no-op).

## Scheduled release (optional)

A per-cohort manifest, `course-org/.github/manifests/<cohort-org>.yml` (`sessions:` → what
opens each session), joined with the cohort's `classroom-config/schedule.csv`
(`session,date`), lets the daily **Scheduled release** cron open each session's items on its
date - materials, lecture code, **and** assignments. The manual buttons still work for early /
ad-hoc release.

## The site

Releases call **Sync site** for you. Run
[Sync site](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/sync-site.yml)
manually only if you've edited the cohort's `dsl-course.yml` (schedule) and want it live
immediately - people (instructors/TAs) live on the course org's `dsl-course.yml` instead, kept
in sync automatically by **Sync membership**.

## Next

- [Add an assignment](03-add-assignment-to-course.md), then [release it](07-release-assignment-to-cohort.md).

---
**Demo:** released into [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026); site at
`dsl-demo-f2026.github.io`.
