# Release materials to a cohort

Open lecture + reading weeks up to a cohort, one week at a time. Every release also triggers
**Sync site**, so the cohort website stays current automatically.

## Prerequisites

- A course [materials repo](04-add-materials.md) with the weeks you want to release.
- A bootstrapped [cohort](02-new-cohort-org.md).

## Release materials

Course `.github` → **Actions** →
[Release materials](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/release-materials.yml)
(or the materials repo's own Release button, where `week` is a dropdown):

- `cohort_org` = `DSL-Demo-f2026`, `cohort_repo` = `materials`, `week` = N
- toggles: `include_lectures` / `include_readings` (default **on**), `include_syllabus` /
  `include_readme` (default **off**)

Copies `lectures/week-N/` + `readings/week-N/` into the cohort's **private** `materials` repo
(with `students`-team read), nested under `week-N/`. Only released weeks appear; idempotent
(re-running a released week is a no-op).

## Scheduled release (optional)

A per-cohort manifest, `course-org/.github/manifests/<cohort-org>.yml` (`weeks:` → what opens
each week), joined with the cohort's `classroom-config/schedule.csv` (`week,date`), lets the
daily **Scheduled release** cron open each week's items on its date - materials, lecture code,
**and** assignments. The manual buttons still work for early / ad-hoc release.

## The site

Releases call **Sync site** for you. Run
[Sync site](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/sync-site.yml)
manually only if you've edited `dsl-course.yml` (people/schedule) and want it live immediately.

## Next

- [Add an assignment](06-add-assignment.md), then [release it](07-release-assignment.md).

---
**Demo:** released into [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026); site at
`dsl-demo-f2026.github.io`.
