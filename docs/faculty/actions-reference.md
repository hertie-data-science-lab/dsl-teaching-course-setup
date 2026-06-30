# Faculty actions reference

What each faculty button does, at a glance. They live in the **course org's `.github` Actions
tab** (seeded at bootstrap); **Release materials** and **Release assignment** *also* live inside
each content / assignment-template repo ("run-from-repo"), where `week` is a dropdown of that
repo's own weeks.

For the **step-by-step flows** (which button, which inputs, in what order), see the
[workflow runbooks](README.md). For the **data contract** (file layouts, CSV columns), see
[`required-input-schema.md`](required-input-schema.md).

## One-time setup

| Action | Where | Effect |
| --- | --- | --- |
| **Bootstrap cohort** | `.github` | Configure a pre-created cohort org (welcome + roster + tighten + website), register it, refresh. |
| **Sync enrolment** | `.github` | Reconcile org + `students`-team access from `students.csv` (students self-onboard via the Join issue; faculty run this to true-up). `prune` off-boards members no longer on the roster. |
| **New materials repo** | `.github` | Scaffold a structured `course-materials-<tag>` repo (week folders + Release buttons). |
| **New assignment** | `.github` | Scaffold an `assignment-N-<tag>` template (starter + autograder on `main`, an empty `solution` branch). |
| **Refresh actions** | `.github` | Re-seed the run-from-repo buttons into every content repo, propagate the repo secret, repopulate all dropdowns, rebuild the profile READMEs. _(Across all DSL-managed repos at once: [`Refresh Course Org Inventory`](https://github.com/hertie-data-science-lab/dsl-teaching-course-setup/actions/workflows/refresh-inventory.yml) in the central repo.)_ |

## Weekly cadence

| Action | Where | Effect |
| --- | --- | --- |
| **Release materials** | `.github` (pick source repo, type week) **or** the materials repo (week dropdown) | Copies the *whole* `lectures/week-N/` + `readings/week-N/` folders - every file - into the cohort `materials` repo (private + `students` read), nested under `week-N/`. Only released weeks appear. Optional `syllabus` / `README` toggles (default off). |
| **Release assignment** | `.github` or the materials repo | Two stages: freeze a cohort-level template repo `<slug>` from the chosen `assignment-*` template, then generate one private `<slug>-<handle>` repo per onboarded student *from that cohort template* (+ collaborator). `include_solution` pushes the template's `solution` branch into each student repo. |
| **Grade assignment** | `.github` | Faculty-side autograder: pins each submission to the assignment's scheduled due date (cohort `schedule` + `grace_days`), runs the hidden tests, records the machine score. |
| **Sync site** | `.github` | Regenerate a cohort's website from the org structure - releases do this automatically; the standard workflow has no need for manual sync. |

## Optional: public course website

| Action | Where | Effect |
| --- | --- | --- |
| **Publish course website** | `.github` | Build/refresh a **public** `<course-org>.github.io` site sharing this course's lectures + readings. Opt-in + manual (first run scaffolds it). Pick a materials repo; choose readings as `reading-list` (citations only) or `actual-readings` (also host the files). Because the materials repos are private, the site **hosts** the shared files itself. Separate from the per-cohort student-gated sites; releases/refresh never touch it. |
