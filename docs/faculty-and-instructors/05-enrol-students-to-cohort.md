# Enrol students

Email each registrar-listed student an **enrolment code**; they paste it into a Join issue and
land in the cohort org and their role team.

## Prerequisites

- A bootstrapped [cohort org](04-new-cohort-org.md) with the roster loaded in
  `classroom-config/students.csv`.
- To actually *send* email: the `GRAPH_*` (preferred) or `SMTP_*` Actions secrets. Without them
  every send stays a preview (codes are still written to the roster).

## Steps

1. **Send enrolment codes.** Course org → `.github` → **Actions** →
   [Send enrolment codes](https://github.com/DSL-Demo-Course-E1234/.github/actions/workflows/send-codes.yml),
   pick the cohort. Writes an `enrol_code` onto every roster row that lacks one and emails it to
   each not-yet-onboarded student at their `hertie_email`.

   > **`dry_run` defaults to `true`** - the first run only previews the codes and emails. Untick
   > it to actually write and send.

2. **Students self-onboard.** Each opens a **Join** issue in the cohort's `welcome` repo and
   pastes their code; they're added to the org and to the team their `role` names (`students`,
   or `auditors`). **They must accept the org invite** before they can see anything.

   > **Testing the flow yourself?** A Join issue opened by an org owner/admin gets labelled
   > `staff` and stops - no team is added, because that would demote you and lock you out. Use a
   > non-staff account to exercise the real student path.

3. **Keep the roster true.** Any push to `classroom-config/students.csv` triggers **Sync
   membership**: deleting a row off-boards that student, changing their `role` moves them
   between teams. A daily cron re-runs it; the button is the manual escape hatch.

## Auditors

Set `role: auditor` on a roster row (blank means enrolled). Auditors get **read on every
released-materials repo, exactly like enrolled students**, but no assignment repo, no gradebook
and no marks. A **Join team** issue from an auditor is refused and labelled `needs-review`.

## Group assignments (optional)

Students open a **Join team** issue in `welcome`, or you edit `classroom-config/teams.csv`
(`assignment, team, github_handle`) - either way **Sync membership** creates a GitHub team per
group. A **Release assignment** run with `group` ticked then grants each team its shared repo.

## Next

- [Release an assignment](08-release-assignment-to-cohort.md) once students have onboarded - or
  let the [schedule](06-schedule-releases.md) hand it out for you.

---
**Demo:** Join issue in [`DSL-Demo-f2026/welcome`](https://github.com/DSL-Demo-f2026).
