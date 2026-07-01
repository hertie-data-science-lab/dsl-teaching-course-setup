# New cohort org (once per year)

Stand up the per-year, student-facing org: onboarding, the roster, released materials, and the cohort website. Do this each year; the [course org](01-new-course-org.md) it hangs off is permanent.

## Prerequisites

- **You're in the course org's `course-admin` team** (or a prior cohort's `instructors-<tag>`
  team, if this course already has one) - *the *Bootstrap cohort* button lives in the
  **course** org's console and runs with the bot token, so you do **not** need any membership
  in the cohort org itself.*

## Steps

1. **Create the cohort org** in the web UI. Naming convention: **`<course-name>-f/sYYYY`**
   (e.g. `DSL-Demo-f2026`). 
    - The `fYYYY` / `sYYYY` tag drives the semester label ("Fall 2026")
   and which year's `assignment-*` templates the site lists.

2. **Invite `hertie-dsl-bot` as Owner** of the cohort org you're about to bootstrap: (Org → People → Invite → role *Owner*). 


3. **Run [Bootstrap cohort](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/bootstrap-cohort.yml)** from the **course** org's `.github` Actions tab, input `cohort_org` = `DSL-Demo-f2026`. It:
   - seeds **`welcome`** repo (public; containing the Join issue + `onboard` workflow),
   - seeds **`classroom-config`** repo (private) with placeholders
      - `README.md`,
      - `students.csv`,
      - `teams.csv`,
      - `schedule.yml`,
      - `people.yml`,
      - `grades/`,
   - applies the course org's current `course_admins` to this cohort's own `course-admin`
     team,
   - scaffolds + deploys the site `dsl-demo-f2026.github.io`,
   - registers the cohort in the course org and propagates the token, then runs **Sync site**.

   The cohort org gets **no `dsl-course.yml`** of its own. Course admins are declared once on
   the [course org](01-new-course-org.md), mirrored down automatically - nothing to hand-edit
   here for them. Instructors/TAs are the opposite: declared **here**, per cohort (step 4a),
   since most cohorts have different lecturers/TAs.

4a. **Declare this cohort's instructors/TAs.** `classroom-config/people.yml` grants push
   access to this cohort's own team AND a course-org `instructors-<tag>` team (scoped to
   this year's content repos), reconciled by **Sync membership**:

   ```yaml
   people:
     instructors:
       - github_handle: "janedoe"
     teaching_assistants:
       - github_handle: "anOther"
         start: "2026-09-01"
         end: "2027-01-31"
   ```

4b. **Fill the cohort's schedule.** `classroom-config/schedule.yml` holds this cohort's
   release calendar and due dates (these vary by year). Edit locally or in the web UI →
   commit to `main` → run **Sync site**:

   ```yaml
   sessions:
     "1": 2026-09-07
     "3": 2026-09-21
   semester_start: 2026-09-07
   assignments:
     assignment-1:
       due: 2026-10-13        # due date students see (the SSOT)
       grace_days: 0          # optional grading-only extension (default 0)
   exams: [{ name: MidTerm Exam, date: 2026-11-03 }]
   ```

5. **Load the roster.** Replace the example row in `classroom-config/students.csv` with
   registrar data (`student_id, hertie_email, name, section`; leave `github_handle, github_id`
   blank - onboarding fills them). The repo's own `README.md` documents every column.

## Next

- [Enrol students](05-enrol-students-to-cohort.md).
- [Release to the cohort](06-release-materials-to-cohort.md).

---
**Demo:** cohort [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026), bootstrapped from
[`DSL-Demo-Course-E1234`](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/bootstrap-cohort.yml).
