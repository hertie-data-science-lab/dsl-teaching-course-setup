# Enrol students

Put the registrar's list into the roster, send each student an enrolment code, and they
self-onboard via a Join issue - no by-hand invites.

## Prerequisites

- A bootstrapped [cohort org](04-new-cohort-org.md).

## Steps

Live example roster: [`example-course/cohort-org/students.csv`](../../example-course/cohort-org/students.csv).

1. **Add the students to the roster.**
   - Edit `classroom-config/students.csv` in the **cohort** org
   - Editing directly via the web UI is fine, or edit the repo locally, commit & push
   - one row per student: `student_id, hertie_email, name, section`
   - **Leave `github_handle, github_id, enrol_code` blank** - onboarding and step 2 fill them automatically
   - Set `role: auditor` for anyone who should get the materials but no assignments or grades.


   >Someone joins late? Add their row, commit & push - then re-run step 2 for their code.
   >Someone drops? Delete their row - the commit & push off-boards them.

2. **Send enrolment codes.**
   - In Your **course** org → `.github` → **Actions** → **Send enrolment codes**: pick the cohort.
   - This workflow writes an `enrol_code` onto every roster row that lacks one and emails each not-yet-onboarded student at their `hertie_email`.

   > **NB: `dry_run` defaults to `true`.** Untick it to write and send.
   >
   > **If emailing isn't live for any reason** (1) notify the DSL (this functionality is configured centrally by the DSL team), (2) the codes
   > can still be written into `students.csv` by the `Send enrolment codes` workflow → then copy each student's code into an email of your own and send out manually.

3. **Students self-onboard.**
   - Each student opens a **Join** issue in the cohort's `welcome` repo and pastes their code
   - That adds them to the org and their role's team.
   - **They must accept the
   org invite** before they can see anything - chase anyone stuck on *pending*.

   > The cohort org's `welcome` repo is automatically seeded when the cohort org is [bootstrapped by the course org](04-new-cohort-org.md#steps).

   > **Testing the flow yourself?** A Join issue from an org owner/admin gets labelled `staff`
   > and stops (it would demote you). Use a non-staff account to test the student path.

## Group assignments 

- Students open a **Join team** issue in `welcome`, or you edit `classroom-config/teams.csv`
(`assignment, team, github_handle`)
- Either way **Sync membership** creates a GitHub team per group.
- A **Release assignment** run with `group` ticked then grants each team its shared repo.

## Auditors (optional)

Set `role: auditor` on a roster row (blank means enrolled). Auditors get **read on every
released-materials repo, exactly like enrolled students**, but no assignment repo, no gradebook
and no marks. A **Join team** issue from an auditor is refused and labelled `needs-review`.

## Next

- [Release an assignment](08-release-assignment-to-cohort.md) once students have onboarded - or
  let the [schedule](06-schedule-releases.md) hand it out for you.

---
**Demo:** [Send enrolment codes](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/send-codes.yml)
in the demo course org · Join issue in [`DSL-Demo-f2026/welcome`](https://github.com/DSL-Demo-f2026).
