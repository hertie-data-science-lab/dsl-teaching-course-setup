# Release to a cohort

Open materials and assignments up to a cohort, week by week. Every release also triggers
**Sync site**, so the cohort website stays current automatically.

## Prerequisites

- Course [materials](add-materials.md) / [assignment](add-assignment.md) repos populated.
- A bootstrapped [cohort](new-cohort-org.md) with [students onboarded](enrol-students.md)
  (assignment release generates one repo per onboarded student).

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

## Release assignment

Course `.github` → **Actions** →
[Release assignment](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/release-assignment.yml).
Two stages:

1. **Freeze** a cohort-level template repo `<slug>` from the chosen `assignment-*-fYYYY` template.
2. **Generate** one **private** `<slug>-<handle>` repo per onboarded student (student added as
   collaborator). The autograder rides along.

`include_solution` pushes the template's `solution` branch into each student repo (default off).

## Scheduled release (optional)

A per-cohort manifest, `course-org/.github/manifests/<cohort-org>.yml` (`weeks:` → what opens
each week), joined with the cohort's `classroom-config/schedule.csv` (`week,date`), lets the
daily **Scheduled release** cron open each week's items on its date. The manual buttons above
still work for early / ad-hoc release.

## The site

Releases call **Sync site** for you. Run
[Sync site](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/sync-site.yml)
manually only if you've edited `dsl-course.yml` (people/schedule) and want the change live
immediately.

---
**Demo:** released into [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026); site at
`dsl-demo-f2026.github.io`.
