# Faculty & instructors actions reference

Every button, one line each. They all live in the **course org's `.github` Actions tab**
(seeded at bootstrap); **Release materials**, **Release assignment** and **Release code**
*also* live inside each content repo ("run-from-repo"), where the inputs know that repo's own
sections and sessions.

For the **step-by-step flows** see the [workflow runbooks](README.md); for the **data
contract** (file layouts, CSV columns) see [`required-input-schema.md`](required-input-schema.md).

## Setup

| Action | Effect |
| --- | --- |
| **Bootstrap cohort** | Configure a pre-created cohort org: `welcome` + `classroom-config`, tighten permissions, scaffold the site, apply `course_admins`, register + refresh. Safe to re-run on a live cohort - your `classroom-config` files (`students.csv`, `schedule.yml`, `people.yml`, `teams.csv`, `grades/`) are never overwritten, only the seeded workflows refresh. |
| **New materials repo** | Scaffold a `course-materials-<tag>` repo (session folders, `SYLLABUS.md`, the run-from-repo Release buttons). |
| **New assignment** | Scaffold an `assignment-N-<tag>` template: brief + starter on `main`; a stub model solution, `grading.yml` and a hidden test on the `solution` branch. |
| **Refresh actions** | Re-seed the run-from-repo buttons, propagate the repo secret, repopulate every dropdown, rebuild the profile READMEs. No inputs. _(All DSL orgs at once: [Refresh Course Orgs Inventory](https://github.com/hertie-data-science-lab/dsl-teaching-course-setup/actions/workflows/refresh-inventory.yml) in the central repo.)_ |
| **Show status** | Read-only per-cohort checklist of what's configured and what's missing, with an edit link for each gap. |
| **Sync membership** | Reconcile `students`/`auditors` teams (`students.csv`), project teams (`teams.csv`), and instructor/course-admin access (`people.yml` + the course `people:` block). Automatic on push to those files, plus a daily cron; the button is an escape hatch. |

## Release

| Action | Effect |
| --- | --- |
| **Scheduled release** | The hourly cron that fires the cohort's `schedule.yml` `materials_releases` plan and freezes passed deadlines. Manual runs default to `dry_run=true`. |
| **Release materials** | Copy whole `<section>/<NN>_.../` folders for the chosen `sessions` into the cohort (private, `students` + `auditors` read). Per-section checkbox + path; `include_root_files` (default off) adds syllabus + README. |
| **Release assignment** | Freeze a cohort template from the chosen `assignment-*`, then generate one private `<slug>-<handle>` repo per onboarded student. `include_solution` / `group` / `dry_run`, all default off. |
| **Release code** | Run from the repo holding your package: copy one path (subpackage folder or module file) into a cohort repo, additively - phased disclosure of a growing package. |
| **Send enrolment codes** | Generate an `enrol_code` per roster row, write it back to `students.csv`, email each not-yet-onboarded student theirs. **`dry_run` defaults to `true` - nothing is written or sent until you untick it.** |
| **Sync site** | Regenerate a cohort's website from the live org structure. Releases, a push to `schedule.yml`, and a daily cron all do this for you. |

## Grades

Full flow: [Grade and return assignments](08-grade-and-return-assignments.md).

| Action | Effect |
| --- | --- |
| **Grade assignment** | Faculty-side autograder: pins each submission to the frozen deadline snapshot, runs the template's hidden tests, writes `auto`/`team_grade` into `classroom-config/grades/<slug>.csv`. No deadline input; nothing written to student repos. |
| **Sync gradebooks** | Ensure every onboarded, enrolled student has a private `grades-<handle>` repo (student = read). Idempotent. |
| **Render grades (preview)** | Pivot the grade CSVs into `gradebook/<handle>.yml` + a wide `cohort-gradebook.csv`, and open **one** PR in `classroom-config` - that diff is the preview. |
| **Distribute grades** | After merging that PR: push each gradebook to the student's private repo and email them. **`dry_run` defaults to `true`**; `silent` pushes without emailing. |

## Optional: public course website

| Action | Effect |
| --- | --- |
| **Publish course website** | Build/refresh a **public** `<course-org>.github.io` sharing this course's lectures + readings. Pick a `source_repo`; `readings_mode` = `reading-list` (citations only, default), `actual-readings` (host the files) or `none`. Because the materials repos are private the site hosts the files itself. The first run opts in and records its settings in `_publish-config.yml`; a daily cron re-syncs from them - delete that file to stop. Releases and Refresh never touch it. |
