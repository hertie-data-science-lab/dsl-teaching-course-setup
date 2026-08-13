"""Generate an org's landing pages from its live contents.

Two documents per org, both auto-generated and both overwritten on every refresh:

- `profile/README.md` - the org landing page. A cohort org gets a student-facing page
  (how to enrol, where the materials are); a course org gets the faculty-facing index of
  cohorts, repos, and every action button.
- the `.github` repo's own `README.md` - the orientation a faculty member sees on
  landing in that repo, next to the Actions tab where the buttons live.

Rendering is pure (render_profile_readme / render_dotgithub_readme take the repo list);
update_profile_readme is the one function that touches the network.
"""

from __future__ import annotations

import yaml

from .central import CENTRAL, CENTRAL_REF
from .discovery import discover_cohorts, list_org_repos
from .utils import get_file_content, log_ok, put_file

# Per-org identity/people/schedule config, lives at the root of each org's `.github` repo.
COURSE_CONFIG = "dsl-course.yml"


def _repo_table(repos: list[dict]) -> str:
    """Clickable repo table, with `welcome` first (most logical landing repo)."""
    visible = [r for r in repos if r["name"] != ".github"]
    visible.sort(key=lambda r: (r["name"].lower() != "welcome", r["name"].lower()))
    rows = []
    for r in visible:
        desc = (r.get("description") or "").replace("|", "\\|").strip()
        rows.append(
            f"| [{r['name']}]({r['url']}) | {r['visibility'].lower()} | {desc} |"
        )
    return "\n".join(rows) or "| _(no repos yet)_ | | |"


def render_dotgithub_readme(org: str, course_name: str, is_cohort: bool) -> str:
    """The `.github` repo's OWN README - the orientation a faculty & instructors member sees on landing
    in this repo just after bootstrap. Distinct from profile/README.md (the org landing
    page); this shows on the repo itself, next to the Actions tab where the buttons live."""
    if is_cohort:
        return f"""# {course_name} - cohort control repo

This is the **`.github` repo** for the `{org}` cohort org. It holds this cohort's configuration
and the auto-generated student-facing org page - **faculty, instructors and faculty assistants (FAs) delivering the course rarely need to touch it directly.**

- The **faculty & instructors action buttons** (Release, Grade, Sync ...) live in the **parent course org's**
  `.github` **Actions** tab, not here. This repo has no `dsl-course.yml` of its own - all of
  this cohort's config lives in **classroom-config** instead:
  `schedule.yml` (release calendar + due dates), `people.yml` (this cohort's own
  instructors/TAs), `students.csv`, `teams.csv`, `grades/`.
- Course identity (name/code) and `course_admins` are inherited from the parent course org,
  kept in sync by **Sync membership**.
- `profile/README.md` - the student-facing org landing page (auto-generated; don't hand-edit).
- Students join via the **welcome** repo's "Join course" issue; the roster lives in **classroom-config**.

Built and kept in sync by the [DSL teaching toolkit](https://github.com/{CENTRAL}).
"""
    return f"""# {course_name} - course control panel

This is the **`.github` repo** for the `{org}` course org - the control panel faculty & instructors use to run
the course. **You never need a CLI or to write code: every action is a clickable UI button.**

## Run an action

Open the **[Actions tab](https://github.com/{org}/.github/actions)**, pick a workflow, and click
**Run workflow**. Buttons only show if you have write access - you're in this org's
`course-admin` team (declared here, course-wide), or a cohort's `instructors-<tag>` team
(declared in that cohort's own `classroom-config/people.yml`). The full, annotated list of
actions is on the **[org home page](https://github.com/{org})**.

## Typical flow

1. **New materials repo** / **New assignment** - scaffold your content repos, then fill them in.
2. Create an empty **cohort org** for the year, add the bot as an Owner, then run **Bootstrap cohort**.
3. Each session: **Release materials** / **Release assignment**. Students self-onboard via the cohort's
   **welcome** "Join" issue.
4. Grading: **Grade assignment** -> **Sync gradebooks** -> **Render grades** -> **Distribute grades**.

## What's in here

- `.github/workflows/` - the action buttons (seeded from the central toolkit; refreshed by **Refresh actions**).
- `{COURSE_CONFIG}` - this course's identity (name/code) and `course_admins` (the
  course-wide admin SSOT, kept in sync into every cohort by **Sync membership**).
  Instructors/TAs and the schedule are both declared per cohort instead, in that
  cohort's own `classroom-config`.
- `profile/README.md` - the public org landing page (auto-generated repo index).

Built and kept in sync by the [DSL teaching toolkit](https://github.com/{CENTRAL}).
"""


def render_profile_readme(
    org: str,
    org_name: str,
    course_name: str,
    repos: list[dict],
    is_cohort: bool,
    cohorts: list[str] | None = None,
) -> str:
    """Org overview. Cohort orgs get a student-facing page; course orgs a faculty & instructors one."""
    table = _repo_table(repos)
    cohort_lines = (
        "\n".join(f"- [{c}](https://github.com/{c})" for c in (cohorts or []))
        or "_(none registered yet - run Bootstrap cohort)_"
    )
    if is_cohort:
        return f"""# {course_name}

Welcome! This is the course organisation for **{course_name}**.

## Course website

**[{course_name} - course website](https://{org.lower()}.github.io/)** - schedule,
lectures, assignments, and the teaching team. Auto-generated and kept in sync with this
org; updates on every release.

## Getting started

1. Open a **Join** issue in
   [`welcome`](https://github.com/{org}/welcome/issues/new/choose) to enrol - your
   GitHub handle is captured automatically.
2. Once you're enrolled, course **materials** open up here session by session, and your
   own assignment repositories appear in this org.

## Where things are

| Repo | Visibility | What it's for |
| --- | --- | --- |
{table}

_Teaching staff (instructors, TAs, faculty assistants): your action buttons aren't here - they live in the
parent **course org's** `.github` control panel, on its Actions tab._

---
_Hertie Data Science Lab. This page is auto-generated._
"""
    return f"""# {org_name}

**{course_name}** - the persistent **course org** for this course, managed by the Hertie Data
Science Lab. It is the control panel: version-controlled materials + assignment templates, plus
every faculty & instructors action button. Each year's students live in a separate **cohort org** that
receives releases from here.

> **Faculty & instructors - start here:** run everything from the
> **[`.github` Actions tab](https://github.com/{org}/.github/actions)**. New to the platform?
> Follow the step-by-step
> **[workflow runbooks](https://github.com/{CENTRAL}/blob/{CENTRAL_REF}/docs/README.md)**.
> The sections below are a live index of this org's cohorts, repositories, and actions.

_This page is auto-generated; edits will be overwritten on the next refresh._

## Cohorts

List of cohort orgs registered to receive releases from this course org. _Auto-discovered from the
`cohort-courses-pages.yml` registry_:

{cohort_lines}

## Repositories

List of all repositories associated with the course org; a centralised registry and historical
record of course-related content. _Add new course-related content here, then push to the relevant
cohort org using the GitHub Actions below_.

| Repo | Visibility | Description |
| --- | --- | --- |
{table}

## Available actions for faculty, instructors & admin

All actions live in the [`.github` repo's Actions tab](https://github.com/{org}/.github/actions)
_(automatically bootstrapped from the central
[dsl-teaching-course-setup repo](https://github.com/{CENTRAL}))_:

### One-time setup actions:
- [**Bootstrap cohort**](https://github.com/{org}/.github/actions/workflows/bootstrap-cohort.yml) - configure a freshly-created cohort org (sets up scaffold repos), register it with the course org, refresh dropdowns.
- [**Send enrolment codes**](https://github.com/{org}/.github/actions/workflows/send-codes.yml) - generate a random non-PII enrolment code per student and email each their code (to their university inbox). Students paste the code into the welcome Join issue - no personal data in the public repo. `dry_run` previews codes + emails. Needs the `GRAPH_*` (or `SMTP_*`) secrets.
- [**Sync membership**](https://github.com/{org}/.github/actions/workflows/sync-membership.yml) - one consolidated, fully-automatic reconcile of org + `students`-team access (from `students.csv`), project teams (from `teams.csv`), `course_admins` (from this org's declared `people:` block, mirrored into every cohort's own `course-admin` team), and each cohort's own `instructors`/`teaching_assistants` (from its `classroom-config/people.yml`, reconciled into that cohort's `instructors` team AND a course-org `instructors-<tag>` team). Triggers on push (editing any of those files takes effect immediately, including removals - there's no prune toggle, the file is the live truth) and on a daily cron (catches a faculty entry's `start`/`end` rotation with no edit that day); `workflow_dispatch` is a manual escape hatch.
- [**New materials repo**](https://github.com/{org}/.github/actions/workflows/new-materials.yml) - scaffold a correctly-structured `course-materials-<year>` repo (session folders + the Release buttons).
- [**New assignment**](https://github.com/{org}/.github/actions/workflows/new-assignment.yml) - scaffold an `assignment-N-<year>` template repo (starter on `main`; the `solution` branch carries the model solution, `grading.yml`, and the hidden tests).
- [**Refresh actions**](https://github.com/{org}/.github/actions/workflows/refresh-actions.yml) - repopulate the cohort/session/assignment dropdowns, re-equip content repos, and rebuild this index. Runs itself nightly, so this org stays in step with the central toolkit on its own.
- [**Check cohort setup**](https://github.com/{org}/.github/actions/workflows/check-cohort-setup.yml) - a per-cohort checklist of everything configured (identity, people, schedule + release plan, roster, teams, grades) with direct edit links for anything missing. Read-only.

### Optional: public course website (open courseware)
- [**Publish course website**](https://github.com/{org}/.github/actions/workflows/publish-site.yml) - build/refresh a PUBLIC site `{org}.github.io` that shares this course's lecture materials and readings with the world. Opt-in (the first run scaffolds the site); afterwards a daily cron re-syncs it from the settings that run chose, so later materials edits appear without another click. Pick a materials repo and choose for readings: `reading-list` (citations only) or `actual-readings` (also host the files). Because the materials repos are private, the site **hosts** the shared files itself. This is separate from each cohort's student-facing site.

### Session cadence actions:
- [**Release materials**](https://github.com/{org}/.github/actions/workflows/release-materials.yml) - copy path(s) from a course repo into a cohort repo: any folder or file (a session folder, a whole section, a subpackage of a growing importable package), one or several at a time.
- [**Release assignment**](https://github.com/{org}/.github/actions/workflows/release-assignment.yml) - generate one private repo per student from a chosen `assignment-*` template repo.

NB: alternatively each materials repo *also* carries its own **Release** buttons (run from inside the
repo; there `course_source_repo` is pre-filled with that repo instead of being a dropdown).

### Grades (private, previewable):
- [**Grade assignment**](https://github.com/{org}/.github/actions/workflows/grade-assignment.yml) - faculty-side autograder: after the deadline, run the HIDDEN tests (from the template's `solution` branch) against each submission and record the machine score into `classroom-config/grades/<assignment>.csv`. Nothing is written to student repos; faculty & instructors then add manual marks. Optional per assignment (skipped if `grading.yml` sets `autograde: false`).
- [**Sync gradebooks**](https://github.com/{org}/.github/actions/workflows/sync-gradebooks.yml) - ensure every onboarded student has a PRIVATE `grades-<handle>` repo (the single home for all their grades). Idempotent.
- [**Render grades (preview)**](https://github.com/{org}/.github/actions/workflows/render-grades.yml) - build per-student `gradebook/<handle>.yml` from `classroom-config/grades/<assignment>.csv` and open ONE pull request. **That PR is the preview** - review every student's grades in the diff before sending.
- [**Distribute grades**](https://github.com/{org}/.github/actions/workflows/distribute-grades.yml) - after merging the preview PR, copy each student's gradebook into their private repo and (unless silenced) email each student a notification to their university inbox (needs the `GRAPH_*` or `SMTP_*` secrets).

- [**Scheduled release**](https://github.com/{org}/.github/actions/workflows/scheduled-release.yml) - hourly cron that auto-releases whatever each cohort's `classroom-config/schedule.yml` `releases:` plan says is now due (honouring each release's `when` time to the hour). Manual runs default to a dry-run preview ("what opens when"). Manual buttons above still work for early/ad-hoc release.

- _[**Sync site**](https://github.com/{org}/.github/actions/workflows/sync-site.yml) - regenerate a cohort's website from the org structure (releases do this automatically; standard workflow has no need for manual sync)._

## How the actions behave

**Release materials** - run it from the materials repo (`course_source_repo` pre-filled with
that repo) or from the course org's central `.github` control panel (`course_source_repo` is
a dropdown). **Both** take the same five fields, which are exactly a `schedule.yml` `deploy:`
entry: `cohort_org`, `course_source_repo`, `course_source_path`, `cohort_dest_repo`,
`cohort_dest_path` - so the manual button and the scheduled release plan share one
vocabulary. `course_source_path` is any folder or file (`lectures/03_regression`,
`mlpkg/simulation`, `SYLLABUS.md`); a folder is copied whole, **every file** in it.
`course_source_path` and `cohort_dest_path` accept comma-separated lists paired in order, so
one click can release several paths at once; a blank `cohort_dest_path` mirrors each source
path. `cohort_dest_repo` (default `materials`) is created on demand, private, with
`students` **and** `auditors` read. Copies are additive and idempotent: only what you have
released appears, and re-releasing changes nothing.

**Release assignment** - two stages: (1) it freezes a cohort-level template repo
`<assignment>` from your `assignment-*-<year>` template; (2) it generates one private
`<assignment>-<handle>` repo per onboarded student **from that cohort template**, adding
each as collaborator. After the assignment deadline, rerun with **include_solution** to push the
template's `solution` branch into every student repo. Solutions stay on the `solution`
branch so a normal release never leaks them.

**The cohort website** - every cohort has an auto-deployed site `<org>.github.io`. It is regenerated
on every release (and via **Sync site**). Its lecture links point at the cohort's private repos, so
they only resolve for enrolled members (deliberate).

**The public course website** (optional) - `Publish course website` builds `{org}.github.io`, a public
open-courseware site for the course as a whole. Unlike the cohort sites it **hosts** the shared lecture
files (the source repos are private, so links would 404); readings are published either as a text-only
reading list or as hosted files. It is opt-in - releases and refresh never touch it, so a public site
only exists once you run the action - but after that first run a daily cron re-syncs it from the
settings you chose, so later materials edits reach it on their own.

## Repository structure (required)

```
{org}/                            <- this COURSE org (persistent)
|-- .github/                      profile + faculty & instructors action buttons + cohort registry
|-- course-materials-<year>/      lectures/01_.../   readings/01_.../   (+ syllabus, README)
`-- assignment-<n>-<year>/        is_template repo:
                                    main      -> starter + autograder   (students get this)
                                    solution  -> solution/   (pushed to students on demand)

<Course>-f<year>/                 <- one COHORT org per year (Bootstrap cohort sets it up)
|-- welcome/                      Join issue -> onboard (enrol)
|-- classroom-config/             students.csv  (private roster)
|-- materials/                    released lectures/readings  (students-team read)
|-- <org>.github.io/              auto-deployed website (synced from this structure)
`-- <assignment>-<handle>/        one private repo per student
```

This whole structure is bootstrapped from the central
[`dsl-teaching-course-setup`](https://github.com/{CENTRAL})
repo (via its **Bootstrap Course Org** action), and the actions above run that same central code.

The course-level actions assume this layout - use **New materials repo** / **New assignment** above to scaffold correctly.

**Materials repo** (`course-materials-<year>`) - the source for Release materials. Any path
in it can be released; the convention below is what the cohort **website** reads, since it
lists whatever sits in an ordinal-prefixed (`01_`, `02_`, `03_`, ...) folder:
- `lectures/01_.../` - one folder per session's lecture files;
- `readings/01_.../` - one folder per session's readings;
- add more sections freely (e.g. `labs/01_.../`) - nothing declares them;
- root files (`SYLLABUS.md`, `README.md`) release like any other path - name the file as the
  `course_source_path`.

**Assignment repo** (`assignment-N-<year>`, an `is_template` repo) - the source for Release assignment:
- **`main` branch** - the starter code only (no tests, no autograder). This is exactly what students receive (native template-generate copies `main` only).
- **`solution` branch** - the model solution (`solution/`), plus **`grading.yml`** and the **hidden tests** that the Grade assignment button runs faculty-side. **All of this MUST live on this branch, never on `main`** - that is what guarantees it is never copied into student repos on generate. Only the `solution/` folder reaches students, and only when you run Release assignment with **include_solution** ticked (a separate, later commit); the hidden tests and `grading.yml` never do.

---
Maintained by the [Hertie Data Science Lab](https://github.com/hertie-data-science-lab).
"""


def update_profile_readme(
    org: str, org_name: str | None = None, course_name: str | None = None
) -> None:
    """(Re)generate the org's profile/README.md from its metadata + live repo list.

    A cohort org (one with a `welcome` repo) gets a student-facing page; a course org
    gets the faculty-facing one."""
    if org_name is None or course_name is None:
        cfg = {}
        content = get_file_content(org, ".github", COURSE_CONFIG)
        if content:
            cfg = yaml.safe_load(content) or {}
        org_name = org_name or cfg.get("org_name") or org
        course_name = course_name or cfg.get("course_name") or org_name
    repos = list_org_repos(org)
    is_cohort = any(r["name"] == "welcome" for r in repos)
    cohorts = None if is_cohort else discover_cohorts(org)
    body = render_profile_readme(org, org_name, course_name, repos, is_cohort, cohorts)
    put_file(
        org,
        ".github",
        "profile/README.md",
        body.encode(),
        "docs: refresh org profile README (repo index)",
    )
    put_file(
        org,
        ".github",
        "README.md",
        render_dotgithub_readme(org, course_name, is_cohort).encode(),
        "docs: orientation README for the .github repo",
    )
    log_ok("profile + .github READMEs refreshed")
