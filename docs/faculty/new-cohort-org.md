# New cohort org (once per year)

Stand up the per-year, student-facing org: onboarding, the roster, released materials, and
the cohort website. Do this each year; the [course org](new-course-org.md) it hangs off is
permanent.

## Prerequisites

- **`hertie-dsl-bot` is an Owner** of the cohort org.
- **You're in the course org's `instructors` / `course-admin` team** - the *Bootstrap cohort*
  button lives in the **course** org's console and runs with the bot token, so you do **not**
  need any membership in the cohort org itself.

## Steps

1. **Create the cohort org** in the web UI. Naming convention: **`<course-name>-f/sYYYY`**
   (e.g. `DSL-Demo-f2026`). The `fYYYY` / `sYYYY` tag drives the semester label ("Fall 2026")
   and which year's `assignment-*` templates the site lists.

2. **Invite `hertie-dsl-bot` as Owner.**

3. **Run [Bootstrap cohort](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/bootstrap-cohort.yml)**
   from the **course** org's `.github` Actions tab, input `cohort_org` = `DSL-Demo-f2026`. It:
   - seeds **`welcome`** (the Join issue + `onboard` workflow),
   - seeds **`classroom-config`** (private): starter `students.csv`, a schema `README.md`,
     `grades/`, and sample `teams.csv` / `schedule.csv`,
   - writes the cohort **`.github/dsl-course.yml`** (people + schedule template),
   - scaffolds + deploys the site `dsl-demo-f2026.github.io`,
   - registers the cohort in the course org and propagates the token, then runs **Sync site**.

4. **Fill the cohort identity card.** The cohort `.github/dsl-course.yml` holds **people +
   schedule** (these vary by year; course name/code come from the course org). Edit in the web
   UI → commit to `main` → run **Sync site**:

   ```yaml
   people:
     instructors:        [{ name: ..., photo: <url>, url: <bio> }]
     teaching_assistants: [{ name: ..., photo: ..., url: ... }]
   schedule:
     semester_start: 2026-09-07
     assignments: { assignment-1: 2026-10-13 }
     exams: [{ name: MidTerm Exam, date: 2026-11-03 }]
   ```

   Anything you omit is **synthesised** (GitHub avatars from the teams; dates every 2 weeks;
   exams at weeks 8 & 15).

5. **Load the roster.** Replace the example row in `classroom-config/students.csv` with
   registrar data (`student_id, hertie_email, name, section`; leave `github_handle, github_id`
   blank - onboarding fills them). The repo's own `README.md` documents every column.

## Next

- [Enrol students](enrol-students.md).
- [Release to the cohort](release-to-cohort.md).

---
**Demo:** cohort [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026), bootstrapped from
[`DSL-Demo-Course-E1234`](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/bootstrap-cohort.yml).
