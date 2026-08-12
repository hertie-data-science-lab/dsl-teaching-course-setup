# Release code to a cohort

Publish a **growing package** to students one piece at a time: a subpackage folder
(`mlpkg/simulation`) or a single module (`mlpkg/train/warmup.py`) copied out of a course code
repo into a cohort repo, additively. Phased disclosure - reveal a topic when you teach it.

Distinct from [Release materials](07-release-materials-to-cohort.md), which copies whole
ordinal-prefixed **session folders**. Code releases follow your package's own tree instead.

## Prerequisites

- A course-org repo holding the package (e.g. `lecture-code-f2026`), scaffolded by
  [New materials repo](02-add-materials-to-course.md) so it carries the run-from-repo buttons.
- A bootstrapped [cohort](04-new-cohort-org.md).
- **The package must tolerate not-yet-released submodules** - release its base early so a
  partial tree still imports.

## The schedule normally does this

There is no separate "code" action: a code release **is** a `deploy` entry, with `source_repo`
pointing at the code repo instead of the materials repo. Same action, same hourly cron - see
[Schedule releases](06-schedule-releases.md).

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

`dest_path` is optional and defaults to mirroring `source_path`, so the package keeps its shape
inside the cohort repo. Copies are additive and idempotent: a re-run that changes nothing pushes
nothing, and an earlier release is never removed by a later one.

## Release code (manual)

The **Release code** button lives **only in the content repo itself** (that repo is the source);
it is not on the course org's `.github` Actions tab. Go to the code repo → **Actions** →
**Release code**:

- `cohort_org` - the target cohort
- `cohort_repo` - a **dropdown of that cohort's existing content repos** (**Refresh actions**
  repopulates it). The destination is private, with `students` + `auditors` granted read.
- `path` - the folder or file to release, e.g. `mlpkg/simulation`

Use it for a demo, a mid-lecture reveal, or recovery - the schedule is still the primary
mechanism.

> **A destination that doesn't exist yet won't be in the dropdown.** A scheduled `deploy`
> creates its `dest_repo` on the fly; the button can only pick from what's already there. Run
> the first release into a new repo from the schedule (or release into `materials`).

## Next

- [Release materials](07-release-materials-to-cohort.md) for session folders.
- [Schedule releases](06-schedule-releases.md) to plan the whole term's disclosure up front.

---
**Demo:** `lecture-code-f2026/mlpkg` in [`DSL-Demo-Course-E1234`](https://github.com/DSL-Demo-Course-E1234),
released into [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026). The worked plan is
`example-course/cohort-org/schedule.yml`.
