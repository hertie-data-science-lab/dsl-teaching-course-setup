# New cohort org (once per year)

Stand up the per-year, student-facing org: onboarding, the roster, released materials, the
cohort website, and the schedule that runs the term. Once each year; the
[course org](01-new-course-org.md) it hangs off is permanent.

## Prerequisites

- You're in the course org's `course-admin` team (or a prior cohort's `instructors-<tag>`
  team) - the *Bootstrap cohort* button lives in the **course** org's control panel.

## Steps

Live example of every file below: [`example-course/cohort-org/`](../example-course/cohort-org).

1. **Create the cohort org** in the web UI, named **`<course-name>-f/sYYYY`**
   (e.g. `DSL-Demo-f2026`). The `fYYYY`/`sYYYY` tag drives the semester label ("Fall 2026") and
   which year's `assignment-*` templates the site lists.

2. **Invite `hertie-dsl-bot` as Owner** (Org → People → Invite → role *Owner*).

3. **Run [Bootstrap cohort](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/bootstrap-cohort.yml)**
   from the **course** org's `.github` Actions tab, `cohort_org` = `DSL-Demo-f2026`. You get the
   public **`welcome`** repo (Join course issue + onboarding, plus a student-facing `README.md`
   telling them how to join - yours to reword, it is never overwritten), the private
   **`classroom-config`** repo
   (`students.csv`, `teams.csv`, `schedule.yml`, `people.yml`, `grades/`), the `students` +
   `auditors` teams, this cohort's `course-admin` team, and the site `dsl-demo-f2026.github.io`.

4. **Fill in `classroom-config/schedule.yml` for the whole term** (edit locally or in the web UI
   → commit to `main`). Its dates drive every release, the grading deadlines and the website.
   Full guide: [Schedule releases](06-schedule-releases.md); full schema:
   [the schedule](DEPLOYMENT-CHECKLIST.md#scheduleyml).

   ```yaml
   timezone: Europe/Berlin
   materials_releases:
     session_1:
       calendar_event: 2026-09-07T14:00   # when the class happens - shown on the site
       deploy:
         - {source_repo: course-materials-f2026, source_path: lectures/01_intro, dest_repo: materials,
            deploy_datetime: 2026-09-07T13:00}   # optional: ship this copy 1h early
   semester_start: 2026-09-07
   semester_end: 2026-12-18
   assignments:
     assignment-1:
       handout: 2026-09-22T09:00    # repos provisioned automatically (per team if the
                                    # template's grading.yml says type: group)
       due: 2026-10-13              # due date students see; bare date -> 23:59:59
       grading_deadline: 2026-10-15 # optional; snapshot + autograde fire here (once)
   exams:
     - {name: MidTerm Exam, date: 2026-11-03}        # bare date -> shown at 09:00
     - {name: Final Exam, date: 2026-12-15T14:00}    # real start time, shown as given
   ```

5. *(optional)* **Declare this cohort's instructors/TAs** in `classroom-config/people.yml`.
   This grants them push on this cohort and on this year's course content repos, and supplies
   the cohort site's cards.

   ```yaml
   people:
     instructors:
       - github_handle: "janedoe"
     teaching_assistants:
       - github_handle: "anOther"
         start: "2026-09-01"
         end: "2027-01-31"
   ```

6. **Load the roster.** Fill `classroom-config/students.csv` (seeded header-only) with
   registrar data (`student_id, hertie_email, name, section`; leave `github_handle, github_id`
   blank - onboarding fills them). Add `role: auditor` for anyone who should get the released
   materials but no assignments and no grades. `students.csv.sample` next to it shows a filled
   row of each kind, and that repo's `README.md` documents every column.

## Next

- [Enrol students](05-enrol-students-to-cohort.md).
- [Schedule releases](06-schedule-releases.md) - the full guide to the plan you started in step 4.
- [Release ad hoc](07-release-materials-to-cohort.md), if you want something out before the
  schedule says so.

---
**Demo:** cohort [`DSL-Demo-f2026`](https://github.com/DSL-Demo-f2026), bootstrapped from
[`DSL-Demo-Course-E1234`](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/bootstrap-cohort.yml).
