# Release materials to a cohort

Open sessions up to a cohort, from any releasable section (lectures, readings, or anything
else your materials repo has). Every release also triggers **Sync site**, so the cohort
website stays current automatically.

## Prerequisites

- A course [materials repo](02-add-materials-to-course.md) with the sessions you want to release.
- A bootstrapped [cohort](04-new-cohort-org.md).

## The schedule does the work

**Fill in the cohort's `classroom-config/schedule.yml` `materials_releases:` plan up front,
once, and the hourly **Scheduled release** cron runs the whole term for you** - each labelled
entry fires when its `when` datetime arrives:

| Action | Does |
|--------|------|
| `deploy` | copy a source path from a course repo → a cohort repo (materials, code, datasets) |
| `assignment` | provision one private repo per enrolled student from a template |
| `grade` | run the faculty-side autograder |

```yaml
timezone: Europe/Berlin
materials_releases:
  session_2:
    when: 2026-09-15T14:00
    deploy:
      - {source_repo: course-materials-f2026, source_path: lectures/02_intro, dest_repo: materials}
  assignment-1-handout:
    when: 2026-09-22T09:00
    assignment: assignment-1-f2026
```

Full schema: [the schedule](required-input-schema.md#the-schedule).

**Fill the schedule early and you never click a release button.** Everything below is the
manual override, for releasing something early or ad hoc.

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

- [Add an assignment](03-add-assignment-to-course.md), then [release it](07-release-assignment-to-cohort.md).

---
**Demo:** released into [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026); site at
`dsl-demo-f2026.github.io`.
