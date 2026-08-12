# Add materials to the course org

Create the year's materials repo and fill it with lectures + readings. **Release materials**
later copies session folders from here into a cohort. One repo per year: `course-materials-{f/s}YYYY`.

## Prerequisites

- A bootstrapped [course org](01-new-course-org.md).
- Push access on its content repos: `course-admin` membership, or being declared an
  instructor/TA in a cohort's `classroom-config/people.yml`
  ([step 5](04-new-cohort-org.md)), which puts you in that year's `instructors-<tag>` team.

## Steps

Live example: [`example-course/course-org/course-materials-f2026/`](../example-course/course-org/course-materials-f2026).

1. **Scaffold the repo.** Course org → `.github` → **Actions** →
   [New materials repo](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/new-materials.yml),
   input `tag` = `f2026` → creates **`course-materials-f2026`** (private), pre-seeded with
   `lectures/01_session-1/`, `readings/01_session-1/`, `labs/01_session-1/` (delete `labs/`
   if your course has none), a `README.md` + `MAINTAINING.md`, a placeholder `SYLLABUS.md`,
   and the three Release buttons. You have push on it immediately.

2. **Push your content** to `main` (git push or the web uploader):

   ```
   lectures/01_session-1/   any files - slides, demo code, notebooks …
   readings/01_session-1/   any files
   labs/01_session-1/       any files (or delete labs/ entirely)
   SYLLABUS.md              optional (any root file matching *syllabus*)
   ```

   Any top-level directory holding ordinal-prefixed subdirectories is releasable, so add your
   own sections freely (e.g. `datasets/`). Only the leading ordinal (`01_`, `02_`, …) matters -
   name the rest however is clearest (`01_intro`, `02_regression`, …).

   *NB: this repo stays private - students never see it. Only the sessions you release reach
   the cohort org, so you can stage the whole course here.*

3. **Run Refresh actions** (course `.github`) so the `session` dropdown and each section's
   checkbox pick up what you just pushed.

## Next

- [Add an assignment](03-add-assignment-to-course.md).
- [Schedule releases](06-schedule-releases.md) - plan the term, and never click a release button.
- [Release to a cohort](07-release-materials-to-cohort.md) - open sessions up to students by hand.

---
**Demo:** [`DSL-Demo-Course-E1234`](https://github.com/DSL-Demo-Course-E1234) → New materials repo.
