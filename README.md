# DSL Teaching & Course Setup

Central control plane for course delivery at the Hertie Data Science Lab. It's the
single home of the faculty automation: faculty trigger everything as **GitHub Actions
buttons** (no CLI), and the Python in `dsl_course/` is the one implementation behind
them.

**Access**: every action is gated on **repo permission** - the triggering user must have
write/maintain/admin on the repo the action runs in. Faculty do; students never do.

## The model

Two org tiers; the course org is the persistent source of truth, the cohort org is the
per-year student-facing target.

```
COURSE org   e.g. Hertie-School-Deep-Learning-E1394   (persistent, private)
  materials-f2026         lectures/week-N/ + readings/week-N/ (+ syllabus, README at root)
  assignment-1-f2026 ...  template repos (is_template) + autograder
  .github                 profile (auto) + ALL faculty buttons + cohort registry
        |
        |  release / generate  (bot token, cross-org)
        v
COHORT org   e.g. Deep-Learning-f2026                  (per-year, private)
  welcome           Join issue -> onboard.yml (enrol)
  classroom-config  students.csv roster (PRIVATE)
  materials         released lectures/readings (students-team read)
  <assignment>-<handle>   one private repo per student (generated; autograder rides along)
  students team
```

## Hard constraint: orgs are created by hand

**GitHub has no API to create an organisation.** So every org (course or cohort) is
created once in the web UI, the bot is added as an owner, and then **automation
configures it**. That's the only manual step; everything after is a button.

## Setting up a course (one-time)

1. **Create the empty course org** in the web UI; add the bot as an owner.
2. **Bootstrap** it - this repo's Actions tab -> **Bootstrap Course Org** (`org` =
   the new org). It sets teams, 2FA, the `.github` profile, all the faculty buttons,
   and propagates `DSL_BOT_TOKEN`.
3. **Add content** in the course org: a `materials-f2026` repo with `lectures/week-N/`
   and `readings/week-N/` folders (and optionally a syllabus + README at the root), and
   one `assignment-N-f2026` template repo per assignment (mark `is_template`; put the
   starter + an autograder in it).
4. **Refresh actions** (org button) so the content repos get their run-from-repo Release
   buttons, the repo secret is propagated, and every dropdown populates.

## Adding a cohort (per year)

1. **Create the empty cohort org** in the web UI; add the bot as an owner.
2. Course org -> **Bootstrap cohort** (org button) with the cohort's name. It seeds the
   `welcome` (onboard) + `classroom-config` (roster) repos, tightens permissions,
   **registers** the cohort in `.github/cohort-courses-pages.yml`, and refreshes the
   dropdowns so the cohort appears everywhere.

## Faculty actions

All five live in the course org's **`.github`** Actions tab. **Release materials** and
**Release assignment** *also* live inside each content / assignment-template repo
("run-from-repo"), where the source is that repo and `week` is a dropdown of that repo's
weeks.

| Action | Where | Effect |
| --- | --- | --- |
| **Release materials** | `.github` (pick source repo, type week) **or** the materials repo (week dropdown) | Copies `lectures/week-N/` + `readings/week-N/` into the cohort repo (private + `students` read). Optional `syllabus` / `README` toggles (default off) copy those root files to the cohort root, overwriting. |
| **Release assignment** | `.github` or the materials repo | Native template-`generate`: one private `<slug>-<handle>` repo per onboarded student from the chosen `assignment-*` template; adds the student as collaborator. |
| **Enroll student** | `.github` | Grant a handle org + `students`-team access (faculty override for the Join issue). Blank handle = reconcile the whole roster. |
| **Bootstrap cohort** | `.github` | Configure a pre-created cohort org (welcome + roster + tighten), register it, refresh. |
| **Refresh actions** | `.github` | Re-seed the run-from-repo buttons into every content repo, propagate the repo secret, repopulate all dropdowns, rebuild the profile READMEs. |

**Student onboarding** (cohort-side): students open a **Join** issue in the public
`welcome` repo; `onboard.yml` matches their student ID against the private roster,
records their authenticated handle + GitHub id, and grants org + `students`-team access.
No CLI.

## Dynamic dropdowns

`workflow_dispatch` dropdowns are static YAML and can't depend on another input, so
**Refresh actions** regenerates them from live state and re-pushes the workflows (no
cron, no app):

- **cohort_org** - from the `.github/cohort-courses-pages.yml` registry.
- **cohort_repo** - the cohort's content repos, with `materials` as the default.
- **week** - the source materials repo's `lectures/week-N/` folders (run-from-repo copy);
  the central `.github` copy uses a free-text week, since it can't depend on the chosen
  source repo.
- **source_repo** (central only) / **assignment** - the course org's content / `assignment-*` repos.

## Token

All workflows run under **`secrets.DSL_BOT_TOKEN`**. On the **GitHub Free plan, org
secrets don't reach private repos** - so bootstrap propagates the token as an *org*
secret (for the public `.github`/`welcome`) **and** Refresh sets it as a *repo* secret on
each private content repo. The token needs cross-org repo admin + members + contents.
Production target: a **GitHub App** (fine-grained, short-lived) - or GitHub Team/Enterprise,
where org secrets reach private repos and this propagation is unnecessary.

## Repo layout

Self-contained - workflows + their Python implementation live here.

- `.github/workflows/` - `bootstrap-org` (+ the legacy create-tier); the faculty
  workflows are rendered + seeded into the course/cohort orgs, not kept here.
- `dsl_course/` - the package:
  - `bootstrap_course` - configure a course or (`--cohort`) cohort org.
  - `seed` - render the workflows (central + run-from-repo), discover dropdown options, refresh.
  - `release` - publish a week's materials (+ optional syllabus/README) into a cohort repo.
  - `assign` - generate per-student repos from an assignment template.
  - `sync_roster` - enrol / materialise team access from `students.csv`.
  - `roster` - read the per-cohort `students.csv`.
  - `utils` - shared `gh`/git helpers with rate-limit backoff.
  - `new_semester` / `post_migrate` / `bootstrap_org` / `list_orgs` - legacy create-tier
    (older course-side model; the next slimming target).
- `templates/welcome/` - the cohort onboarding workflow + Join issue form.

## Related reading

Decisions, inventory, and session notes live in the
[`gh-org-strategy`](https://github.com/hertie-data-science-lab/gh-org-strategy)
coordination hub. That hub is not required at runtime; this repo stands on its own.
