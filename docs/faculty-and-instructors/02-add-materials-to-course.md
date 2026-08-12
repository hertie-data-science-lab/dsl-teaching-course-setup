# Add materials to the course org

Create the year's materials repo and fill it with lectures + readings. **Release materials**
later copies session folders from here into a cohort. One repo per year: `course-materials-{f/s}YYYY`.

## Prerequisites

- A bootstrapped [course org](01-new-course-org.md), and **push access on its content repos**.
  Normally that comes from the tag-scoped **`instructors-<tag>`** team, which **Sync membership**
  reconciles from the cohort's `classroom-config/people.yml` - so declaring yourself there
  ([step 5](04-new-cohort-org.md)) is what grants it. Course admins (`course-admin`) have it
  course-wide. The course org's generic `instructors` team also carries push, but nothing
  reconciles its membership - it's a rare manual escape hatch, not the normal path.

## Steps

1. **Scaffold the repo.** Course org → `.github` → **Actions** →
   [New materials repo](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/new-materials.yml),
   input `tag` = `f2026` → creates **`course-materials-f2026`** (private) with the schema the
   downstream actions expect: empty `lectures/01_session-1/` + `readings/01_session-1/`, a
   `README.md` + `MAINTAINING.md`, a placeholder `SYLLABUS.md`, and the three run-from-repo
   Release buttons (Release materials / assignment / code).

   That tag's `instructors-<tag>` team (plus `course-admin`) is granted **push** on the new repo
   automatically, so you can push straight away.

2. **Push your content** to `main` (git push or the web uploader), following the schema. Any
   top-level directory containing at least one ordinal-prefixed subdirectory is a releasable
   section - no config to declare it, so you can add more freely (e.g. `labs/`):

   ```
   lectures/01_session-1/   any files - slides, demo code, notebooks …
   readings/01_session-1/   any files
   SYLLABUS.md              optional (any root file matching *syllabus*)
   ```

   Only the leading ordinal (`01_`, `02_`, `03_`, ...) is meaningful - name the rest of the
   directory whatever's clearest to you (`01_intro`, `02_regression`, ...).

   *NB: You can add the full course content here as a 'staging' repo - it remains private and
   non-viewable by students; while only the sessions you choose to 'release to cohort' get
   dispatched to the student-facing cohort org.*

3. **Refresh actions** (course `.github`) so the `session` dropdown and each section's include
   checkbox pick up what you just added.

## Next

- [Add an assignment](03-add-assignment-to-course.md).
- [Schedule releases](06-schedule-releases.md) - plan the term, and never click a release button.
- [Release to a cohort](07-release-materials-to-cohort.md) - open sessions up to students by hand.

---
**Demo:** [`DSL-Demo-Course-E1234`](https://github.com/DSL-Demo-Course-E1234) → New materials repo.
