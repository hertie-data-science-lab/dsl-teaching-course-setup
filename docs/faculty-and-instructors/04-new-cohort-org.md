# New cohort org (once per year)

Stand up the per-year, student-facing org: onboarding, the roster, released materials, the
cohort website - and the schedule that runs the whole term. Do this each year; the
[course org](01-new-course-org.md) it hangs off is permanent.

## Prerequisites

- **You're in the course org's `course-admin` team** (or a prior cohort's `instructors-<tag>`
  team). The *Bootstrap cohort* button lives in the **course** org's console and runs as the
  bot, so you need no membership in the cohort org itself.

## Steps

1. **Create the cohort org** in the web UI. Naming convention **`<course-name>-f/sYYYY`**
   (e.g. `DSL-Demo-f2026`) - the `fYYYY`/`sYYYY` tag drives the semester label ("Fall 2026")
   and which year's `assignment-*` templates the site lists.

2. **Invite `hertie-dsl-bot` as Owner** (Org → People → Invite → role *Owner*).

3. **Run [Bootstrap cohort](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/bootstrap-cohort.yml)**
   from the **course** org's `.github` Actions tab, `cohort_org` = `DSL-Demo-f2026`. It seeds
   the public **`welcome`** repo (Join issue + `onboard` workflow), the private
   **`classroom-config`** repo (`README.md`, `students.csv`, `teams.csv`, `schedule.yml`,
   `people.yml`, `grades/`), the `students` + `auditors` teams, this cohort's `course-admin`
   team from the course org's current `course_admins`, and the site
   `dsl-demo-f2026.github.io`; then registers the cohort, propagates the token, and syncs the
   site.

   Course admins are declared once on the [course org](01-new-course-org.md) and mirrored down -
   nothing to hand-edit here. Instructors/TAs are the opposite: declared **here** (step 5),
   since most cohorts have different lecturers/TAs.

4. **Fill in `classroom-config/schedule.yml` for the whole term. This is the step that matters.**
   Its `materials_releases` plan is what the hourly **Scheduled release** cron runs - every
   materials release, every assignment hand-out, every autograde run - and its dates drive the
   website and the grading deadlines. Fill it now and you never click a release button. Edit
   locally or in the web UI → commit to `main`. Full schema:
   [the schedule](required-input-schema.md#the-schedule).

   ```yaml
   timezone: Europe/Berlin
   materials_releases:
     session_1:
       when: 2026-09-07T14:00       # bare date -> 00:00 that day
       deploy:
         - {source_repo: course-materials-f2026, source_path: lectures/01_intro, dest_repo: materials}
     assignment-1-handout:
       when: 2026-09-22T09:00
       assignment: assignment-1-f2026
     assignment-1-grade:
       when: 2026-10-15T00:00
       grade: {template: assignment-1-f2026}
   semester_start: 2026-09-07
   semester_end: 2026-12-18
   assignments:
     assignment-1:
       due: 2026-10-13              # due date students see; bare date -> 23:59:59
       grace_days: 0                # optional grading-only extension
   exams:
     - {name: MidTerm Exam, date: 2026-11-03}        # bare date -> shown at 09:00
     - {name: Final Exam, date: 2026-12-15T14:00}    # real start time, shown as given
   ```

5. *(optional)* **Declare this cohort's instructors/TAs** in `classroom-config/people.yml`.
   Grants push on this cohort plus a course-org `instructors-<tag>` team scoped to this year's
   content repos (reconciled by **Sync membership**), and supplies the cohort site's cards.

   ```yaml
   people:
     instructors:
       - github_handle: "janedoe"
     teaching_assistants:
       - github_handle: "anOther"
         start: "2026-09-01"
         end: "2027-01-31"
   ```

6. **Load the roster.** Replace the example row in `classroom-config/students.csv` with
   registrar data (`student_id, hertie_email, name, section`; leave `github_handle, github_id`
   blank - onboarding fills them). Add `role: auditor` for anyone who should get the released
   materials but no assignments and no grades. The repo's own `README.md` documents every
   column.

## Next

- [Enrol students](05-enrol-students-to-cohort.md).
- [Release ad hoc](06-release-materials-to-cohort.md), if you want something out before the
  schedule says so.

---
**Demo:** cohort [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026), bootstrapped from
[`DSL-Demo-Course-E1234`](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/bootstrap-cohort.yml).
