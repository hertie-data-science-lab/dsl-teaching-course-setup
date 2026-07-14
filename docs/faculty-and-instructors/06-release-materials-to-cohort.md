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
- a pair of fields per section discovered in the materials repo (up to 3 - see
  "Section limit" below): `release_<section>` (checkbox, default **on** - whether to
  release it at all this run) and `<section>_path` (free text, optional - where it
  lands). Leave the path blank to create/use a repo named after the section, at its
  root; type `repo/subpath` (e.g. `materials/lectures`) to nest it under a folder there
  instead, so two sections can share one repo, or each can get its own. Repos are
  created automatically if they don't exist yet.
- `sessions` = a comma and/or range list, e.g. `1,3,5-7` (GitHub's Actions UI has no
  multi-select widget, so this is free text rather than checkboxes - the field's
  description lists the sessions discovered in the repo for reference)
- `include_root_files` toggle (default **off**) - also releases the syllabus file(s) and
  source README together

**Section naming**: sections are just top-level directories with ordinal-prefixed
subfolders - name them however you like. `lectures/`, `labs/`, `materials/` is the
suggested convention (and what the checkbox/path fields above assume by default), but
nothing enforces it.

**Section limit**: GitHub's Actions UI caps a workflow at 10 inputs total, and each
section costs 2 (checkbox + path) - so only the first 3 sections (alphabetically) get
buttons. A 4th+ section isn't silently dropped: "Refresh actions" logs which ones got
left out, and you release those directly via
`python3 -m dsl_course.release --destinations "section=repo/subpath,..."`.

The central `.github` button works the same way, using the union of sections seen
across every content repo in the org (also capped at 3) - a section checked there that
the source repo you picked doesn't actually have simply finds nothing to release.

Copies every routed `<section>/<NN>_.../` folder matching each chosen session into its
target cohort repo (**private**, with `students`-team read) - nested under its destination
subpath, or at the repo root if none was given. Only released sessions appear; idempotent
(re-running a released session is a no-op).

## Scheduled release (optional)

The cohort's `classroom-config/schedule.yml` `materials_releases:` plan lets the hourly
**Scheduled release** cron fire each labelled release once its `when` datetime has arrived -
`deploy` (copy a source path → a cohort repo), `assignment` (provision student repos), and
`grade` (autograde). The manual buttons still work for early / ad-hoc release. See
[the schedule](required-input-schema.md#the-schedule) for the full schema.

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
