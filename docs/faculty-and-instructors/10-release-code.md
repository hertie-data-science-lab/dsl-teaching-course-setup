# Release code to a cohort

Publish a **growing package** to students one piece at a time - a subpackage folder
(`mlpkg/simulation`) or a single module (`mlpkg/train/warmup.py`) - copied out of a course code
repo into a cohort repo. Use [Release materials](07-release-materials-to-cohort.md) instead for
ordinal-prefixed session folders.

## Prerequisites

- A course-org repo holding the package (e.g. `lecture-code-f2026`), scaffolded by
  [New materials repo](02-add-materials-to-course.md) so it carries the Release buttons.
- A bootstrapped [cohort](04-new-cohort-org.md).
- **The package must tolerate not-yet-released submodules** - release its base early so a
  partial tree still imports.

## The schedule normally does this (recommended)

A code release is a `deploy` entry with `source_repo` pointing at the code repo - see
[Schedule releases](06-schedule-releases.md):

```yaml
materials_releases:
  week-1:
    when: 2026-09-01T09:00
    deploy:
      # the package base, early - so later partial releases still import
      - {source_repo: lecture-code-f2026, source_path: mlpkg/core, dest_repo: materials}
  week-3:
    when: 2026-09-15T09:00
    deploy:
      - {source_repo: lecture-code-f2026, source_path: mlpkg/simulation, dest_repo: materials}
```

`dest_path` is optional and defaults to mirroring `source_path`. Copies are additive: an
earlier release is never removed by a later one, and re-runs push nothing.

## Release code via manual dispatch

For a demo, a mid-lecture reveal, or recovery. The **Release code** button lives **only in the
code repo itself** - go to that repo → **Actions** → **Release code**:

- `cohort_org` - the target cohort
- `cohort_repo` - a dropdown of that cohort's existing content repos (**Refresh actions**
  repopulates it). The destination is private, with `students` + `auditors` given read.
- `path` - the folder or file to release, e.g. `mlpkg/simulation`

> **A destination repo that doesn't exist yet won't be in the dropdown.** Run the first release
> into a new repo from the schedule (or release into `materials`).

## Next

- [Release materials](07-release-materials-to-cohort.md) for session folders.
- [Schedule releases](06-schedule-releases.md) to plan the whole term's disclosure up front.

---
**Demo:** `lecture-code-f2026/mlpkg` in [`DSL-Demo-Course-E1234`](https://github.com/DSL-Demo-Course-E1234),
released into [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026). The worked plan is
[`example-course/cohort-org/schedule.yml`](../../example-course/cohort-org/schedule.yml),
and the package itself is [`example-course/course-org/lecture-code-f2026/mlpkg/`](../../example-course/course-org/lecture-code-f2026/mlpkg).
