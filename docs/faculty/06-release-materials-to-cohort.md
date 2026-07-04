# Release materials to a cohort

Open sessions up to a cohort, one at a time, from any releasable section (lectures, readings,
or anything else your materials repo has). Every release also triggers **Sync site**, so the
cohort website stays current automatically.

## Prerequisites

- A course [materials repo](02-add-materials-to-course.md) with the sessions you want to release.
- A bootstrapped [cohort](04-new-cohort-org.md).

## Release materials

Course `.github` → **Actions** →
[Release materials](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/release-materials.yml),
or - better - the materials repo's own Release button, which knows the repo's actual
sections and sessions:

- `cohort_org` = `DSL-Demo-f2026`
- one `dest_<section>` free-text field per section discovered in the materials repo
  (default: the section's own name). This single field both selects the section (leave it
  **blank to skip** that section) and routes it: a bare repo name (e.g. `lectures`)
  releases at that repo's root; `repo/subpath` (e.g. `materials/lectures`) nests it under a
  folder there, so two sections can share one repo, or each can get its own. Repos are
  created automatically if they don't exist yet.
- `sessions` = a comma and/or range list, e.g. `1,3,5-7` (GitHub's Actions UI has no
  multi-select widget, so this is free text rather than checkboxes - the field's
  description lists the sessions discovered in the repo for reference)
- `include_syllabus` / `include_readme` toggles (default **off**)

The central `.github` button doesn't know the source repo's sections until you pick one, so
it offers a single `cohort_repo` field (every released section nests under its own
subfolder there) plus a free-text `exclude` field, instead of per-section destination
routing.

Copies every routed `<section>/<NN>_.../` folder matching each chosen session into its
target cohort repo (**private**, with `students`-team read) - nested under its destination
subpath, or at the repo root if none was given. Only released sessions appear; idempotent
(re-running a released session is a no-op).

## Scheduled release (optional)

A per-cohort manifest, `course-org/.github/manifests/<cohort-org>.yml` (`sessions:` → what
opens each session), joined with the cohort's `classroom-config/schedule.yml`
(`sessions`/`labs`), lets the daily **Scheduled release** cron open each session's items on its
date - materials, lecture code, **and** assignments. The manual buttons still work for early /
ad-hoc release.

## The site

Releases call **Sync site** for you. Run
[Sync site](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/sync-site.yml)
manually only if you've edited the cohort's `classroom-config/schedule.yml` and want it live
immediately - people (instructors/TAs) live on the course org's `dsl-course.yml` instead, kept
in sync automatically by **Sync membership**.

## Next

- [Add an assignment](03-add-assignment-to-course.md), then [release it](07-release-assignment-to-cohort.md).

---
**Demo:** released into [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026); site at
`dsl-demo-f2026.github.io`.
