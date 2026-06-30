# Add materials to the course org

Create the year's materials repo and fill it with lectures + readings. **Release materials**
later copies week folders from here into a cohort. One repo per year: `course-materials-{f/s}YYYY`.

## Prerequisites

- A bootstrapped [course org](01-new-course-org.md), and you're in its `instructors` /
  `course-admin` team.

## Steps

1. **Scaffold the repo.** Course org → `.github` → **Actions** →
   [New materials repo](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/new-materials.yml),
   input `tag` = `f2026` → creates **`course-materials-f2026`** (private) with the schema the
   downstream actions expect:
   - empty `lectures/week-1/` + `readings/week-1/` 
   - a `README.md`, 
   - a placeholder `syllabus.md`,
   - and the three run-from-repo Release buttons (`release-materials`, `release-assignment`, `release-code`)

   Your `instructors` team is granted **write** on the new repo automatically, so you can
   push straight away.

2. **Push your content** to `main` (git push or the web uploader), following the schema:

   ```
   lectures/week-N/   any files - slides, demo code, notebooks …
   readings/week-N/   any files
   syllabus.md        optional
   ```

   *NB: You can add the full course content here as a 'staging' repo - it remains private and non-viewable by students; while only the weeks you you choose to 'release to cohort' get dispatched to the student-facing cohort org.*

3. **Refresh actions** (course `.github`) so the `week` dropdowns pick up the new weeks you just added.

## Next

- [Add an assignment](03-add-assignment-to-course.md).
- [Release to a cohort](06-release-materials-to-cohort.md) - open weeks up to students.

---
**Demo:** [`DSL-Demo-Course-E1234`](https://github.com/DSL-Demo-Course-E1234) → New materials repo.
