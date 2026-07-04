"""dsl-course seed -- render + place the run-from-repo faculty workflows.

The Release / Provision actions live INSIDE course content (and assignment-template)
repos, so faculty trigger them from the repo they're working in. The repo the workflow
runs in is the SOURCE; the action pushes into a chosen cohort org/repo.

The cohort org input is a GitHub `choice` dropdown. GitHub can't populate a dropdown
live, so its options are rendered into the YAML from the cohort registry and
refreshed on demand: `refresh` reads the course org's .github/cohort-courses-pages.yml
`cohorts:` list (maintained by `bootstrap --cohort --course X`, or by hand), lists
their repos, and re-pushes the content actions to every course repo. No cron, no app.

Sections/sessions in the Release materials button are discovered the same way
(scanned from the source repo's own directory structure - see
discover_sections_and_sessions): each section gets a free-text destination field
(_section_destinations) routing it to a repo (created if missing) or repo/subpath,
and sessions are a comma/range free-text field (_sessions_input) - GitHub's
workflow_dispatch has no multi-select widget and a checkbox per session would blow
past its 10-input cap, unlike the small, bounded set of sections.

CLI:
  refresh --course-org X   re-render the content actions into every course repo with
                           fresh cohort/session/assignment dropdowns, and rebuild the
                           org profile README. (Run by the Refresh-actions and
                           Bootstrap-cohort workflows.)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import yaml

from .utils import (
    delete_file,
    get_default_branch,
    get_file_content,
    gh,
    log_ok,
    log_step,
    put_file,
    session_number,
)

COHORTS_PATH = (
    "cohort-courses-pages.yml"  # standalone registry in the course org's .github repo
)

CENTRAL = "hertie-data-science-lab/dsl-teaching-course-setup"
# Seeded workflows run the engine code from this ref of the central repo.
CENTRAL_REF = "main"
INFRA_REPOS = {"welcome", "classroom-config", ".github"}
# Per-org identity/people/schedule config, lives at the root of each org's `.github` repo.
COURSE_CONFIG = "dsl-course.yml"
WORKFLOWS = (
    ".github/workflows/release-materials.yml",
    ".github/workflows/release-assignment.yml",
    ".github/workflows/release-code.yml",
)

_CHECK_TEAM = """  check-team:
    if: github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    steps:
      - name: Verify the user may run actions for THIS repo
        env:
          GH_TOKEN: ${{ secrets.DSL_BOT_TOKEN }}
          ACTOR: ${{ github.actor }}
          REPO: ${{ github.repository }}
        run: |
          # Faculty have write+ on the course repos; students never do (and triggering a
          # workflow_dispatch already requires write), so repo permission is the gate.
          perm=$(gh api "repos/$REPO/collaborators/$ACTOR/permission" --jq '.permission' 2>/tmp/gherr || true)
          case "$perm" in admin|write|maintain) exit 0 ;; esac
          echo "::error::@$ACTOR lacks write on $REPO (permission='$perm'). gh api said:"
          cat /tmp/gherr || true
          exit 1
"""

_RUN_PREAMBLE = f"""    needs: check-team
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          repository: {CENTRAL}
          ref: {CENTRAL_REF}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
"""


# SMTP secrets, wired into the env of the buttons that send email (enrolment codes, grade
# notifications). A plain string (not the f-string body) so the GitHub `${{ }}` is literal.
_MAIL_ENV = """\
          GRAPH_TENANT_ID: ${{ secrets.GRAPH_TENANT_ID }}
          GRAPH_CLIENT_ID: ${{ secrets.GRAPH_CLIENT_ID }}
          GRAPH_CLIENT_SECRET: ${{ secrets.GRAPH_CLIENT_SECRET }}
          GRAPH_SENDER: ${{ secrets.GRAPH_SENDER }}
          SMTP_HOST: ${{ secrets.SMTP_HOST }}
          SMTP_PORT: ${{ secrets.SMTP_PORT }}
          SMTP_USER: ${{ secrets.SMTP_USER }}
          SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
          SMTP_FROM: ${{ secrets.SMTP_FROM }}"""


def _choice(options: list[str]) -> str:
    opts = options or ["(none-yet)"]
    return "\n".join(f"          - {o}" for o in opts)


def _sessions_input(sessions: list[str]) -> str:
    """Session(s) to release, as free text (comma and/or hyphen-range list, e.g.
    "1,3,5-7" - see utils.expand_int_spec for the parser). GitHub's workflow_dispatch
    has no multi-select widget, and a checkbox-per-session would blow past its 10-input
    cap once a course has more than a handful of sessions (lectures alone can run to
    15) - unlike sections, which stay small and bounded and so get real checkboxes
    (see _section_destinations)."""
    hint = f" (available: {', '.join(sessions)})" if sessions else ""
    return (
        "      sessions:\n"
        f'        description: "Session(s) to release - comma and/or range list, e.g.'
        f' 1,3,5-7{hint}"\n'
        "        required: true"
    )


# Shared cohort_org + cohort_repo dropdowns and the include_* toggles - used by
# render_release_code, which (unlike the materials releasers below) always targets one
# repo picked from a dropdown.
_COHORT_INPUTS = """\
      cohort_org:
        description: "Target cohort org"
        required: true
        type: choice
        options:
{cohort_orgs}
      cohort_repo:
        description: "Target repo in the cohort org"
        required: true
        type: choice
        options:
{cohort_repos}"""
# cohort_org alone - the materials-release renderers route each section to its own
# destination repo instead of picking one repo up front (see _section_destinations).
_COHORT_ORG_INPUT = """\
      cohort_org:
        description: "Target cohort org"
        required: true
        type: choice
        options:
{cohort_orgs}"""
_ROOT_INCLUDES = """\
      include_syllabus:
        description: "Also release the syllabus (root *syllabus* files) - overwrites"
        type: boolean
        default: false
      include_readme:
        description: "Also release the source README to the cohort root - overwrites"
        type: boolean
        default: false"""


def _dest_env_name(section: str) -> str:
    return f"DEST_{section.upper().replace('-', '_')}"


def _check_no_env_name_collisions(sections: list[str]) -> None:
    """Shell env var names can't contain hyphens, so section names are folded to
    match ('case-studies' and 'case_studies' both become DEST_CASE_STUDIES) - raise
    loudly at render time rather than silently dropping one section's destination."""
    seen: dict[str, str] = {}
    for s in sections:
        env_name = _dest_env_name(s)
        if env_name in seen and seen[env_name] != s:
            raise ValueError(
                f"sections {seen[env_name]!r} and {s!r} both map to the env var "
                f"{env_name} - rename one (they differ only by '-' vs '_')"
            )
        seen[env_name] = s


def _section_destinations(sections: list[str]) -> str:
    """One free-text dest_<section> field per section DISCOVERED AT RENDER TIME,
    defaulting to the section's own name. This single field both selects the section
    (blank = skip it) and routes it: a bare repo name ("lectures") releases at that
    repo's root; "repo/subpath" (e.g. "materials/lectures") nests it under a subfolder,
    so two sections can share one repo, or each can get its own. The repo is created
    if it doesn't exist yet. Only usable when the source repo is known at render time
    (run-from-repo); the central button can target any repo at RUN time, so it gets a
    single cohort_repo field + --exclude instead (see render_central_release)."""
    if not sections:
        return ""
    lines = "\n".join(
        f'      dest_{s}:\n        description: "Where to release {s}: a repo name'
        f' (released at that repo\'s root), or repo/subpath to nest under a folder'
        f' there (e.g. materials/{s}) - shared by other sections pointed at the same'
        f' repo. Leave blank to skip {s}."\n        default: "{s}"\n'
        "        required: false"
        for s in sections
    )
    return "\n" + lines


def _render_release(
    header: str,
    inputs_block: str,
    src_repo_expr: str,
    mode: str,
    sections: list[str] = (),
    sessions: list[str] = (),
) -> str:
    """`mode="repo"` (run-from-repo, sections known at render time): one dest_<section>
    free-text field per discovered section, routing it to a repo (or repo/subpath) -
    see _section_destinations. `mode="central"`: the source repo (and so its sections)
    isn't known until the button runs, so instead there's a single cohort_repo field
    (every released section nests under its own subfolder there) plus a --exclude
    list. Sessions are always free text (_sessions_input) in both modes."""
    if mode == "repo":
        _check_no_env_name_collisions(sections)
        target_inputs = _section_destinations(sections)
        target_env = "\n".join(
            f"          {_dest_env_name(s)}: ${{{{ inputs.dest_{s} }}}}" for s in sections
        )
        target_build = "\n".join(
            [
                f'          [ -n "${_dest_env_name(s)}" ] && destinations="$destinations {s}=${_dest_env_name(s)}"'
                for s in sections
            ]
            + ['          [ -n "$destinations" ] && args+=(--destinations "$destinations")']
        )
    else:
        target_inputs = (
            '\n      cohort_repo:\n        description: "Target repo in the cohort org'
            ' - every released section nests under its own subfolder there"\n'
            '        required: true\n      exclude:\n        description:'
            ' "Space/comma-separated sections to skip (e.g. readings)"\n'
            "        required: false"
        )
        target_env = (
            "          COHORT_REPO: ${{ inputs.cohort_repo }}\n"
            "          EXCLUDE_INPUT: ${{ inputs.exclude }}"
        )
        target_build = "\n".join(
            [
                '          [ -n "$COHORT_REPO" ] && args+=(--default-repo "$COHORT_REPO")',
                '          [ -n "$EXCLUDE_INPUT" ] && args+=(--exclude "$EXCLUDE_INPUT")',
            ]
        )

    return f"""name: Release materials
{header}
on:
  workflow_dispatch:
    inputs:
{inputs_block}{target_inputs}
{_sessions_input(sessions)}
{_ROOT_INCLUDES}

jobs:
{_CHECK_TEAM}
  release:
{_RUN_PREAMBLE}      - name: Release
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          SRC_ORG: ${{{{ github.repository_owner }}}}
          SRC_REPO: {src_repo_expr}
          COHORT_ORG: ${{{{ inputs.cohort_org }}}}
          SESSIONS: ${{{{ inputs.sessions }}}}
          INC_SYL: ${{{{ inputs.include_syllabus }}}}
          INC_RM: ${{{{ inputs.include_readme }}}}
{target_env}
        run: |
          gh auth setup-git
          args=(--source-org "$SRC_ORG" --source-repo "$SRC_REPO"
                --cohort-org "$COHORT_ORG" --sessions "$SESSIONS")
{target_build}
          [ "$INC_SYL" = "true" ] && args+=(--syllabus)
          [ "$INC_RM" = "true" ] && args+=(--readme)
          python3 -m dsl_course.release "${{args[@]}}"
"""


def render_release(
    cohort_orgs: list[str],
    sessions: list[str] | None = None,
    sections: list[str] | None = None,
) -> str:
    """Run-from-repo copy: the SOURCE is the repo it lives in. Sections (known for this
    one repo) get real checkboxes that double as destination routing; session(s) are
    free text - see _render_release."""
    cohort_org_input = _COHORT_ORG_INPUT.format(cohort_orgs=_choice(cohort_orgs))
    return _render_release(
        header=(
            "\n# Run from a course content repo (this repo is the SOURCE). Publishes the"
            " chosen session(s)'\n# content into the cohort repo(s) named in each"
            " section's destination field below.\n# Dropdowns are refreshed by the"
            " 'Refresh actions' workflow.\n"
        ),
        inputs_block=cohort_org_input,
        src_repo_expr="${{ github.event.repository.name }}",
        mode="repo",
        sections=sections or [],
        sessions=sessions or [],
    )


def render_release_code(cohort_orgs: list[str], cohort_repos: list[str]) -> str:
    """Run-from-repo: copy a package PATH (subpackage folder or module file) from THIS
    repo into a cohort repo's tree, additively. Phased disclosure of a growing package."""
    cohort = _COHORT_INPUTS.format(
        cohort_orgs=_choice(cohort_orgs), cohort_repos=_choice(cohort_repos)
    )
    return f"""name: Release code

# Run from the repo that holds your package (this repo = SOURCE). Copies a chosen path
# - a subpackage folder (e.g. mlpkg/simulation) or a single module (mlpkg/train/warmup.py)
# - into the cohort repo's tree, additively. Release a topic when you teach it; the
# package must tolerate not-yet-released submodules so partial release still imports.

on:
  workflow_dispatch:
    inputs:
{cohort}
      path:
        description: "Path to release (e.g. mlpkg/simulation or mlpkg/train/warmup.py)"
        required: true

jobs:
{_CHECK_TEAM}
  release-code:
{_RUN_PREAMBLE}      - name: Release code
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          SRC_ORG: ${{{{ github.repository_owner }}}}
          SRC_REPO: ${{{{ github.event.repository.name }}}}
          COHORT_ORG: ${{{{ inputs.cohort_org }}}}
          COHORT_REPO: ${{{{ inputs.cohort_repo }}}}
          REL_PATH: ${{{{ inputs.path }}}}
        run: |
          gh auth setup-git
          python3 -m dsl_course.release_code --source-org "$SRC_ORG" \\
            --source-repo "$SRC_REPO" --cohort-org "$COHORT_ORG" \\
            --cohort-repo "$COHORT_REPO" --path "$REL_PATH"
"""


def render_central_release(source_repos: list[str], cohort_orgs: list[str]) -> str:
    """Central copy that lives in .github: pick the source materials repo, then a
    single target repo + sections to exclude (a central dropdown can't know the
    source's sections until the button runs, so there's no per-section destination
    routing here - the run-from-repo copy inside each materials repo has that, see
    render_release)."""
    source = (
        '      source_repo:\n        description: "Source materials repo (in this course'
        ' org)"\n        required: true\n        type: choice\n        options:\n'
        f"{_choice(source_repos)}"
    )
    cohort_org_input = _COHORT_ORG_INPUT.format(cohort_orgs=_choice(cohort_orgs))
    return _render_release(
        header="",
        inputs_block=f"{source}\n{cohort_org_input}",
        src_repo_expr="${{ inputs.source_repo }}",
        mode="central",
    )


def _assignment_input(assignments: list[str]) -> str:
    """Assignment as a dropdown of discovered assignments/ folders, or free-text."""
    if assignments:
        return (
            '      assignment:\n        description: "Assignment"\n'
            "        required: true\n        type: choice\n        options:\n"
            + _choice(assignments)
        )
    return (
        '      assignment:\n        description: "Assignment template repo (e.g. assignment-1-f2026)"\n'
        "        required: true"
    )


def render_provision(
    cohort_orgs: list[str], assignments: list[str] | None = None
) -> str:
    return f"""name: Release assignment

# Generates one private repo per onboarded student from the chosen assignment template
# repo (native template-generate). The assignment dropdown lists the course org's
# assignment-* template repos; refresh repopulates it.

on:
  workflow_dispatch:
    inputs:
      cohort_org:
        description: "Target cohort org"
        required: true
        type: choice
        options:
{_choice(cohort_orgs)}
{_assignment_input(assignments or [])}
      include_solution:
        description: "Also push the solution (from the template's solution branch) into each student repo"
        type: boolean
        default: false
      group:
        description: "Group assignment - one repo per team (from teams.csv), all members as collaborators"
        type: boolean
        default: false
      dry_run:
        description: "Preview only - list the repos that WOULD be created, don't create them"
        type: boolean
        default: false

jobs:
{_CHECK_TEAM}
  provision:
{_RUN_PREAMBLE}      - name: Provision
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          MASTER_ORG: ${{{{ github.repository_owner }}}}
          COHORT_ORG: ${{{{ inputs.cohort_org }}}}
          TEMPLATE: ${{{{ inputs.assignment }}}}
          INC_SOL: ${{{{ inputs.include_solution }}}}
          GROUP: ${{{{ inputs.group }}}}
          DRY_RUN: ${{{{ inputs.dry_run }}}}
        run: |
          gh auth setup-git
          args=(--master-org "$MASTER_ORG" --template "$TEMPLATE" --cohort-org "$COHORT_ORG")
          [ "$INC_SOL" = "true" ] && args+=(--solution)
          [ "$GROUP" = "true" ] && args+=(--group)
          [ "$DRY_RUN" = "true" ] && args+=(--dry-run)
          python3 -m dsl_course.assign "${{args[@]}}"
"""


def render_grade_assignment(
    cohort_orgs: list[str], assignments: list[str] | None = None
) -> str:
    """Faculty-side autograder button: run hidden tests after the deadline, record scores."""
    return f"""name: Grade assignment

# Faculty-side autograder. Clones each submission as of its scheduled due date (the cohort
# schedule's date + grace_days - SSOT, no input here), runs the HIDDEN tests
# from the template's solution branch, archives result.json, and records the machine score
# into the private grades CSV (faculty then add manual marks; Render + Distribute send them).
# Nothing is written to student repos. dry_run lists what would be graded.

on:
  workflow_dispatch:
    inputs:
      cohort_org:
        description: "Cohort org (submissions)"
        required: true
        type: choice
        options:
{_choice(cohort_orgs)}
{_assignment_input(assignments or [])}
      group:
        description: "Group assignment - grade one repo per team"
        type: boolean
        default: false
      dry_run:
        description: "Preview only - list the repos that WOULD be graded"
        type: boolean
        default: false

jobs:
{_CHECK_TEAM}
  grade:
{_RUN_PREAMBLE}      - name: Grade
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          MASTER_ORG: ${{{{ github.repository_owner }}}}
          COHORT_ORG: ${{{{ inputs.cohort_org }}}}
          TEMPLATE: ${{{{ inputs.assignment }}}}
          GROUP: ${{{{ inputs.group }}}}
          DRY_RUN: ${{{{ inputs.dry_run }}}}
        run: |
          gh auth setup-git
          pip install --quiet pytest nbconvert
          args=(--master-org "$MASTER_ORG" --template "$TEMPLATE" --cohort-org "$COHORT_ORG")
          [ "$GROUP" = "true" ] && args+=(--group)
          [ "$DRY_RUN" = "true" ] && args+=(--dry-run)
          python3 -m dsl_course.collect "${{args[@]}}"
"""


_FACULTY_ONLY = "(faculty only)"


def render_sync_membership(cohort_orgs: list[str]) -> str:
    """Consolidated roster + project-teams + faculty sync (replaces the old separate
    Sync enrolment / Sync teams buttons).

    Faculty always reconciles - split by role: course_admins (from THIS org's
    declared `people:` block) into the course org + every cohort's own course-admin
    team; and, for whichever cohort is in scope, that cohort's own instructors/TAs
    (from its classroom-config/people.yml) into its own instructors team + a
    course-org instructors-<tag> team. Roster (students.csv) + project teams
    (teams.csv) additionally reconcile for whichever cohort is in scope. Fully
    automatic, including removals (no --prune flag - config is the live truth):

    - push to this file's own dsl-course.yml -> course_admins only (no single cohort
      implied - but still applied to every cohort's own course-admin team)
    - repository_dispatch (from a cohort's classroom-config dispatcher on push to its
      students.csv/teams.csv/people.yml) -> course_admins + that one cohort's
      instructors/TAs
    - daily cron -> course_admins + EVERY registered cohort (roster/teams/instructors,
      catching any start/end date rotation with no edit that day, and any drift
      generally)
    - workflow_dispatch -> manual escape hatch, gated by check-team (the other three
      trigger types skip that gate, same as the existing scheduler workflow already
      does for cron)
    """
    return f"""name: Sync membership

on:
  push:
    branches: [main]
    paths:
      - dsl-course.yml
  repository_dispatch:
    types: [sync-membership]
  schedule:
    - cron: "0 6 * * *"
  workflow_dispatch:
    inputs:
{_cohort_dropdown(cohort_orgs, optional=True)}

jobs:
{_CHECK_TEAM}
  sync-dispatch:
{_RUN_PREAMBLE}      - name: Sync membership
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          COURSE: ${{{{ github.repository_owner }}}}
          COHORT_ORG: ${{{{ inputs.cohort_org }}}}
        run: |
          args=(--course-org "$COURSE")
          [ "$COHORT_ORG" != "{_FACULTY_ONLY}" ] && args+=(--cohort-org "$COHORT_ORG")
          python3 -m dsl_course.sync_membership "${{args[@]}}"

  sync-auto:
    if: github.event_name != 'workflow_dispatch'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          repository: {CENTRAL}
          ref: {CENTRAL_REF}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - name: Sync membership
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          COURSE: ${{{{ github.repository_owner }}}}
          EVENT: ${{{{ github.event_name }}}}
          DISPATCH_COHORT: ${{{{ github.event.client_payload.cohort_org }}}}
        run: |
          args=(--course-org "$COURSE")
          case "$EVENT" in
            schedule) args+=(--all-cohorts) ;;
            repository_dispatch) [ -n "$DISPATCH_COHORT" ] && args+=(--cohort-org "$DISPATCH_COHORT") ;;
          esac
          python3 -m dsl_course.sync_membership "${{args[@]}}"
"""


def _cohort_dropdown(cohort_orgs: list[str], optional: bool = False) -> str:
    options = ([_FACULTY_ONLY] + cohort_orgs) if optional else cohort_orgs
    default = f'\n        default: "{_FACULTY_ONLY}"' if optional else ""
    return (
        '      cohort_org:\n        description: "Cohort org"\n'
        f"        required: true\n        type: choice{default}\n        options:\n"
        + _choice(options)
    )


def render_sync_gradebooks(cohort_orgs: list[str]) -> str:
    """Provision one private grades-<handle> repo per onboarded student (idempotent)."""
    return f"""name: Sync gradebooks

# Ensures every onboarded student has a PRIVATE grades-<handle> repo (student = read) -
# the single home for all their grades. Idempotent; safe to re-run after new enrolments.

on:
  workflow_dispatch:
    inputs:
{_cohort_dropdown(cohort_orgs)}
      dry_run:
        description: "Preview only - list the gradebook repos that WOULD be created"
        type: boolean
        default: false

jobs:
{_CHECK_TEAM}
  sync-gradebooks:
{_RUN_PREAMBLE}      - name: Sync gradebooks
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          COHORT_ORG: ${{{{ inputs.cohort_org }}}}
          DRY_RUN: ${{{{ inputs.dry_run }}}}
        run: |
          args=(--cohort-org "$COHORT_ORG")
          [ "$DRY_RUN" = "true" ] && args+=(--dry-run)
          python3 -m dsl_course.grades sync "${{args[@]}}"
"""


def render_render_grades(cohort_orgs: list[str]) -> str:
    """Build per-student gradebook YAML from the grade CSVs and open the preview PR."""
    return f"""name: Render grades (preview)

# Reads classroom-config/grades/<assignment>.csv, builds one gradebook/<handle>.yml per
# student, and opens ONE pull request in classroom-config. THAT PR IS THE PREVIEW: review
# every student's grades in the diff, then merge to distribute (Distribute grades).

on:
  workflow_dispatch:
    inputs:
{_cohort_dropdown(cohort_orgs)}

jobs:
{_CHECK_TEAM}
  render-grades:
{_RUN_PREAMBLE}      - name: Render grades
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          COHORT_ORG: ${{{{ inputs.cohort_org }}}}
        run: |
          gh auth setup-git
          python3 -m dsl_course.grades render --cohort-org "$COHORT_ORG"
"""


def render_distribute_grades(cohort_orgs: list[str]) -> str:
    """Fan the merged gradebook/<handle>.yml files out into each private grades-<handle>."""
    return f"""name: Distribute grades

# Run AFTER merging the Render grades preview PR. Copies each merged gradebook/<handle>.yml
# into that student's private grades-<handle> repo and (unless silenced) emails them a
# notification to their university inbox. Needs the GRAPH_* (or SMTP_*) secrets for the email.

on:
  workflow_dispatch:
    inputs:
{_cohort_dropdown(cohort_orgs)}
      dry_run:
        description: "Preview the grade emails - push nothing, send nothing"
        type: boolean
        default: true
      silent:
        description: "Skip the email notification (just push the grades)"
        type: boolean
        default: false

jobs:
{_CHECK_TEAM}
  distribute-grades:
{_RUN_PREAMBLE}      - name: Distribute grades
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          COHORT_ORG: ${{{{ inputs.cohort_org }}}}
          DRY_RUN: ${{{{ inputs.dry_run }}}}
          SILENT: ${{{{ inputs.silent }}}}
{_MAIL_ENV}
        run: |
          args=(--cohort-org "$COHORT_ORG")
          [ "$DRY_RUN" = "true" ] && args+=(--dry-run)
          [ "$SILENT" = "true" ] && args+=(--no-notify)
          python3 -m dsl_course.grades distribute "${{args[@]}}"
"""


def render_send_codes(cohort_orgs: list[str]) -> str:
    """Generate a non-PII enrolment code per student and email each their code over SMTP."""
    return f"""name: Send enrolment codes

# Generates a random enrolment code per student (into classroom-config/students.csv) and
# emails each not-yet-onboarded student their code to their university inbox. Students paste
# the code into the welcome Join issue - no personal data in the public repo. dry_run
# previews the codes + emails without writing or sending. Needs the GRAPH_* (or SMTP_*) secrets.

on:
  workflow_dispatch:
    inputs:
{_cohort_dropdown(cohort_orgs)}
      dry_run:
        description: "Preview the codes + emails - write nothing, send nothing"
        type: boolean
        default: true

jobs:
{_CHECK_TEAM}
  send-codes:
{_RUN_PREAMBLE}      - name: Send enrolment codes
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          COHORT_ORG: ${{{{ inputs.cohort_org }}}}
          DRY_RUN: ${{{{ inputs.dry_run }}}}
{_MAIL_ENV}
        run: |
          args=(--cohort-org "$COHORT_ORG")
          [ "$DRY_RUN" = "true" ] && args+=(--dry-run)
          python3 -m dsl_course.enrol_codes "${{args[@]}}"
"""


def render_bootstrap_cohort() -> str:
    """Configure a (pre-created, empty) cohort org from the course org: welcome +
    classroom-config + tightened perms, register it, and refresh the dropdowns."""
    return f"""name: Bootstrap cohort

# You create the empty cohort org in the web UI first (GitHub has no org-creation API)
# and add the bot as an owner. Then run this with that org's name.

on:
  workflow_dispatch:
    inputs:
      cohort_org:
        description: "Empty cohort org you've already created (bot must be an owner)"
        required: true

jobs:
{_CHECK_TEAM}
  bootstrap-cohort:
{_RUN_PREAMBLE}      - name: Bootstrap + register + refresh
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          DSL_BOT_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          COURSE: ${{{{ github.repository_owner }}}}
          COHORT: ${{{{ inputs.cohort_org }}}}
        run: |
          python3 -m dsl_course.bootstrap_course --org "$COHORT" --org-name "$COHORT" \\
            --cohort --course "$COURSE" --propagate-secret
          python3 -m dsl_course.seed refresh --course-org "$COURSE"
"""


def render_scheduler() -> str:
    """Daily cron that auto-releases whatever the manifest x calendar says is due, across
    every registered cohort. No check-team gate: scheduled runs have no actor, and the
    scheduler only calls idempotent release functions (manual dispatch still needs write)."""
    return f"""name: Scheduled release

# Joins each cohort's manifests/<cohort>.yml (in this .github repo) with its classroom-config
# classroom-config/schedule.yml and releases everything now due. Idempotent, so a daily run re-releasing
# past sessions is a no-op. On the cron it releases for real; manual runs default to dry-run.

on:
  schedule:
    - cron: "0 6 * * *"
  workflow_dispatch:
    inputs:
      dry_run:
        description: "Preview only - list what WOULD open, release nothing"
        type: boolean
        default: true

jobs:
  scheduled-release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          repository: {CENTRAL}
          ref: {CENTRAL_REF}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - name: Run scheduler
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          COURSE: ${{{{ github.repository_owner }}}}
          DRY_RUN: ${{{{ inputs.dry_run }}}}
        run: |
          gh auth setup-git
          args=(--course-org "$COURSE" --all-cohorts)
          [ "$DRY_RUN" = "true" ] && args+=(--dry-run)
          python3 -m dsl_course.scheduler "${{args[@]}}"
"""


def render_status(cohort_orgs: list[str]) -> str:
    """Per-cohort checklist of every faculty input location - identity, people,
    manifest, schedule, roster, teams, grades, session calendar - with the current
    value and a direct edit link for anything missing. Read-only; changes nothing."""
    return f"""name: Show status

# A per-cohort glance view of everything configured (and everything still missing),
# with direct links to fix it. Read-only - this button changes nothing.

on:
  workflow_dispatch:
    inputs:
{_cohort_dropdown(cohort_orgs)}

jobs:
{_CHECK_TEAM}
  status:
{_RUN_PREAMBLE}      - name: Show status
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          COURSE: ${{{{ github.repository_owner }}}}
          COHORT_ORG: ${{{{ inputs.cohort_org }}}}
        run: |
          python3 -m dsl_course.status --course-org "$COURSE" --cohort-org "$COHORT_ORG" >> "$GITHUB_STEP_SUMMARY"
"""


def render_refresh() -> str:
    """Repopulate dropdowns, re-seed content actions, propagate the repo secret, and
    rebuild the profile README across the course org."""
    return f"""name: Refresh actions

on:
  workflow_dispatch: {{}}

jobs:
{_CHECK_TEAM}
  refresh:
{_RUN_PREAMBLE}      - name: Refresh
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          DSL_BOT_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
        run: |
          python3 -m dsl_course.seed refresh --course-org "${{{{ github.repository_owner }}}}"
"""


def render_new_materials() -> str:
    """Scaffold a correctly-structured course-materials-<tag> repo, then refresh."""
    return f"""name: New materials repo

on:
  workflow_dispatch:
    inputs:
      tag:
        description: "Year tag, e.g. f2026 or s2026 - creates course-materials-<tag>"
        required: true

jobs:
{_CHECK_TEAM}
  scaffold:
{_RUN_PREAMBLE}      - name: Scaffold materials
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          DSL_BOT_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          ORG: ${{{{ github.repository_owner }}}}
        run: |
          gh auth setup-git
          python3 -m dsl_course.scaffold materials --org "$ORG" --tag "${{{{ inputs.tag }}}}"
          python3 -m dsl_course.seed refresh --course-org "$ORG"
"""


def render_new_assignment() -> str:
    """Scaffold an assignment-N-<tag> template repo (main + solution branch), then refresh."""
    return f"""name: New assignment

on:
  workflow_dispatch:
    inputs:
      number:
        description: "Assignment number (e.g. 1)"
        required: true
      tag:
        description: "Year tag, e.g. f2026 or s2026 - creates assignment-<number>-<tag>"
        required: true

jobs:
{_CHECK_TEAM}
  scaffold:
{_RUN_PREAMBLE}      - name: Scaffold assignment
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          ORG: ${{{{ github.repository_owner }}}}
        run: |
          gh auth setup-git
          python3 -m dsl_course.scaffold assignment --org "$ORG" --number "${{{{ inputs.number }}}}" --tag "${{{{ inputs.tag }}}}"
          python3 -m dsl_course.seed refresh --course-org "$ORG"
"""


def render_sync_site(cohort_orgs: list[str]) -> str:
    """Regenerate a cohort's website from the live org structure (released sessions +
    assignment catalog). Releases also trigger this automatically."""
    return f"""name: Sync site

on:
  workflow_dispatch:
    inputs:
      cohort_org:
        description: "Cohort whose site to regenerate from the org structure"
        required: true
        type: choice
        options:
{_choice(cohort_orgs)}

jobs:
{_CHECK_TEAM}
  sync:
{_RUN_PREAMBLE}      - name: Sync site
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
        run: |
          gh auth setup-git
          python3 -m dsl_course.site sync --course-org "${{{{ github.repository_owner }}}}" --cohort-org "${{{{ inputs.cohort_org }}}}"
"""


def render_publish_site(source_repos: list[str]) -> str:
    """Build/refresh the PUBLIC course site <course-org>.github.io (open courseware).

    Opt-in + manual: the first run scaffolds the site, later runs re-sync it. Hosts the
    chosen materials repo's lecture files in the public site (the source repos are private,
    so links would 404); readings are a text-only list or hosted files. Separate from the
    per-cohort student-gated sites; releases/refresh never touch it."""
    return f"""name: Publish course website

# Build/refresh the PUBLIC course site <course-org>.github.io (open courseware). The
# course materials repos are private, so this HOSTS the chosen repo's lecture files in
# the site (links would otherwise 404). Readings: 'reading-list' shows citations as text
# only; 'actual-readings' also hosts + links the files (you carry the copyright
# responsibility); 'none' skips them. Opt-in + manual - the first run scaffolds the site.

on:
  workflow_dispatch:
    inputs:
      source_repo:
        description: "Source materials repo (in this course org) to publish"
        required: true
        type: choice
        options:
{_choice(source_repos)}
      readings_mode:
        description: "Readings: reading-list (citations) / actual-readings (files) / none"
        required: true
        type: choice
        default: reading-list
        options:
          - reading-list
          - actual-readings
          - none
      include_lectures:
        description: "Publish lecture files (the point of the site)"
        type: boolean
        default: true

jobs:
{_CHECK_TEAM}
  publish:
{_RUN_PREAMBLE}      - name: Publish course website
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          COURSE_ORG: ${{{{ github.repository_owner }}}}
          SOURCE_REPO: ${{{{ inputs.source_repo }}}}
          READINGS_MODE: ${{{{ inputs.readings_mode }}}}
          INC_LEC: ${{{{ inputs.include_lectures }}}}
        run: |
          gh auth setup-git
          args=(--course-org "$COURSE_ORG" --source-repo "$SOURCE_REPO" --readings-mode "$READINGS_MODE")
          [ "$INC_LEC" = "false" ] && args+=(--no-include-lectures)
          python3 -m dsl_course.site public-sync "${{args[@]}}"
"""


def _read_cohorts(course_org: str) -> list[str]:
    """Read the course org's standalone .github/cohort-courses-pages.yml registry."""
    content = get_file_content(course_org, ".github", COHORTS_PATH)
    if not content:
        return []
    data = yaml.safe_load(content) or []
    cohorts = data.get("cohorts", []) if isinstance(data, dict) else data
    return [c for c in cohorts if c]


def discover_cohorts(course_org: str) -> list[str]:
    """Cohort orgs are listed explicitly in the course's .github/cohort-courses-pages.yml
    (naming-independent). `bootstrap --cohort --course X` appends; faculty can edit it."""
    return sorted(_read_cohorts(course_org))


def register_cohort(course_org: str, cohort_org: str) -> None:
    """Append cohort_org to the course's cohort-courses-pages.yml registry (idempotent)."""
    cohorts = set(_read_cohorts(course_org))
    if cohort_org in cohorts:
        log_ok(f"{cohort_org} already in {course_org}/.github/{COHORTS_PATH}")
        return
    cohorts.add(cohort_org)
    body = yaml.safe_dump({"cohorts": sorted(cohorts)}, sort_keys=False)
    put_file(
        course_org,
        ".github",
        COHORTS_PATH,
        body.encode(),
        f"registry: add cohort {cohort_org}",
    )
    log_ok(f"registered {cohort_org} under {course_org}")


def discover_cohort_repos(cohort_orgs: list[str]) -> list[str]:
    """Candidate target repos: real cohort content repos, excluding infra
    (welcome/classroom-config/.github), the website, per-student submission repos
    (`submission` topic) and the frozen assignment templates (`assignment-template`).
    Only what genuinely exists - no placeholder default, so an org with nothing
    registered yet correctly shows an empty (not phantom) dropdown."""
    repos: set[str] = set()
    for org in cohort_orgs:
        code, out = gh(
            "repo", "list", org, "--limit", "300", "--json", "name,repositoryTopics"
        )
        if code != 0:
            continue
        for r in json.loads(out):
            topics = {t["name"] for t in (r.get("repositoryTopics") or [])}
            if (
                r["name"] in INFRA_REPOS
                or r["name"].endswith(".github.io")
                or topics & {"submission", "assignment-template"}
            ):
                continue
            repos.add(r["name"])
    return sorted(repos)


def list_dirs(org: str, repo: str, path: str = "") -> list[str]:
    """Directory names directly under `path` (the repo root if omitted)."""
    endpoint = f"repos/{org}/{repo}/contents/{path}" if path else f"repos/{org}/{repo}/contents"
    code, out = gh("api", endpoint, "--jq", '.[] | select(.type=="dir") | .name')
    return out.splitlines() if code == 0 else []


def _section_session_pairs(org: str, repo: str) -> list[tuple[str, int]]:
    """(section, session_number) for every immediate child - across every top-level
    directory - whose name has an ordinal prefix. One recursive tree fetch, rather
    than listing each top-level directory individually (N+1 API calls)."""
    branch = get_default_branch(org, repo) or "main"
    code, out = gh(
        "api",
        f"repos/{org}/{repo}/git/trees/{branch}?recursive=1",
        "--jq",
        '.tree[] | select(.type=="tree") | .path',
    )
    if code != 0:
        return []
    pairs = []
    for path in out.splitlines():
        parts = path.split("/")
        if len(parts) == 2:
            n = session_number(parts[1])
            if n is not None:
                pairs.append((parts[0], n))
    return pairs


def discover_sections_and_sessions(org: str, repo: str) -> tuple[list[str], list[str]]:
    """(sections, sessions) from one shared tree fetch - use this over calling
    discover_sections/discover_sessions separately when you need both, to avoid
    fetching the same tree twice."""
    pairs = _section_session_pairs(org, repo)
    sections = sorted({section for section, _ in pairs})
    sessions = [str(n) for n in sorted({n for _, n in pairs})]
    return sections, sessions


def discover_sections(org: str, repo: str) -> list[str]:
    """Top-level directories in a content repo containing at least one
    ordinal-prefixed subdirectory - the releasable sections. No declared config; the
    repo's own structure is the only source of truth."""
    return sorted({section for section, _ in _section_session_pairs(org, repo)})


def discover_sessions(org: str, repo: str) -> list[str]:
    """Session numbers present in a content repo, across every discovered section.
    Used to populate the session dropdown."""
    return [str(n) for n in sorted({n for _, n in _section_session_pairs(org, repo)})]


def discover_assignments(course_org: str) -> list[str]:
    """Assignment template repos in the course org (named assignment-*) - the dropdown."""
    code, out = gh(
        "repo", "list", course_org, "--limit", "300", "--json", "name,isTemplate"
    )
    if code != 0:
        return []
    return sorted(
        r["name"]
        for r in json.loads(out)
        if r["name"].startswith("assignment-") and r.get("isTemplate")
    )


def discover_content_repos(course_org: str) -> list[str]:
    """Repos that should HOST the release buttons: the materials repo(s), not the
    `.github` profile repo and not the assignment-* template repos (those are generate
    sources - equipping them would copy the faculty workflows into every student repo)."""
    return [
        r["name"]
        for r in list_org_repos(course_org)
        if r["name"] != ".github" and not r["name"].startswith("assignment-")
    ]


def _push_workflows(
    org: str,
    repo: str,
    cohort_orgs: list[str],
    cohort_repos: list[str],
    assignments: list[str],
) -> None:
    sections, sessions = discover_sections_and_sessions(org, repo)
    put_file(
        org,
        repo,
        WORKFLOWS[0],
        render_release(cohort_orgs, sessions, sections).encode(),
        "ci: release-materials wrapper",
    )
    put_file(
        org,
        repo,
        WORKFLOWS[1],
        render_provision(cohort_orgs, assignments).encode(),
        "ci: release-assignment wrapper",
    )
    put_file(
        org,
        repo,
        WORKFLOWS[2],
        render_release_code(cohort_orgs, cohort_repos).encode(),
        "ci: release-code wrapper",
    )
    log_ok(f"workflows -> {org}/{repo}")


def list_org_repos(org: str) -> list[dict]:
    code, out = gh(
        "repo",
        "list",
        org,
        "--limit",
        "300",
        "--json",
        "name,description,visibility,url",
    )
    return json.loads(out) if code == 0 else []


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
    """The `.github` repo's OWN README - the orientation a faculty member sees on landing
    in this repo just after bootstrap. Distinct from profile/README.md (the org landing
    page); this shows on the repo itself, next to the Actions tab where the buttons live."""
    if is_cohort:
        return f"""# {course_name} - cohort control repo

This is the **`.github` repo** for the `{org}` cohort org. It holds this cohort's configuration
and the auto-generated student-facing org page - **faculty / FAs delivering the course rarely need to touch it directly.**

- The **faculty action buttons** (Release, Grade, Sync ...) live in the **parent course org's**
  `.github` **Actions** tab, not here. This repo has no `dsl-course.yml` of its own - all of
  this cohort's config lives in **classroom-config** instead:
  `schedule.yml` (release calendar + due dates), `people.yml` (this cohort's own
  instructors/TAs), `students.csv`, `teams.csv`, `grades/`.
- Course identity (name/code) and `course_admins` are inherited from the parent course org,
  kept in sync by **Sync membership**.
- `profile/README.md` - the student-facing org landing page (auto-generated; don't hand-edit).
- Students join via the **welcome** repo's "Join" issue; the roster lives in **classroom-config**.

Built and kept in sync by the [DSL teaching toolkit](https://github.com/{CENTRAL}).
"""
    return f"""# {course_name} - course control panel

This is the **`.github` repo** for the `{org}` course org - the control panel faculty use to run
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
    """Org overview. Cohort orgs get a student-facing page; course orgs a faculty one."""
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

---
_Hertie Data Science Lab. This page is auto-generated._
"""
    return f"""# {org_name}

**{course_name}** - managed by the Hertie Data Science Lab.
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

## Available actions for faculty & admin

All actions live in the [`.github` repo's Actions tab](https://github.com/{org}/.github/actions)
_(automatically bootstrapped from the central
[dsl-teaching-course-setup repo](https://github.com/hertie-data-science-lab/dsl-teaching-course-setup))_:

### One-time setup actions:
- [**Bootstrap cohort**](https://github.com/{org}/.github/actions/workflows/bootstrap-cohort.yml) - configure a freshly-created cohort org (sets up scaffold repos), register it with the course org, refresh dropdowns.
- [**Send enrolment codes**](https://github.com/{org}/.github/actions/workflows/send-codes.yml) - generate a random non-PII enrolment code per student and email each their code (to their university inbox). Students paste the code into the welcome Join issue - no personal data in the public repo. `dry_run` previews codes + emails. Needs the `GRAPH_*` (or `SMTP_*`) secrets.
- [**Sync membership**](https://github.com/{org}/.github/actions/workflows/sync-membership.yml) - one consolidated, fully-automatic reconcile of org + `students`-team access (from `students.csv`), project teams (from `teams.csv`), `course_admins` (from this org's declared `people:` block, mirrored into every cohort's own `course-admin` team), and each cohort's own `instructors`/`teaching_assistants` (from its `classroom-config/people.yml`, reconciled into that cohort's `instructors` team AND a course-org `instructors-<tag>` team). Triggers on push (editing any of those files takes effect immediately, including removals - there's no prune toggle, the file is the live truth) and on a daily cron (catches a faculty entry's `start`/`end` rotation with no edit that day); `workflow_dispatch` is a manual escape hatch.
- [**New materials repo**](https://github.com/{org}/.github/actions/workflows/new-materials.yml) - scaffold a correctly-structured `course-materials-<year>` repo (session folders + the Release buttons).
- [**New assignment**](https://github.com/{org}/.github/actions/workflows/new-assignment.yml) - scaffold an `assignment-N-<year>` template repo (starter on `main`; the `solution` branch carries the model solution, `grading.yml`, and the hidden tests).
- [**Refresh actions**](https://github.com/{org}/.github/actions/workflows/refresh-actions.yml) - repopulate the cohort/session/assignment dropdowns, re-equip content repos, and rebuild this index.
- [**Show status**](https://github.com/{org}/.github/actions/workflows/status.yml) - a per-cohort checklist of everything configured (identity, people, manifest, schedule, roster, teams, grades, session calendar) with direct edit links for anything missing. Read-only.

### Optional: public course website (open courseware)
- [**Publish course website**](https://github.com/{org}/.github/actions/workflows/publish-site.yml) - build/refresh a PUBLIC site `{org}.github.io` that shares this course's lecture materials and readings with the world. Opt-in + manual (the first run scaffolds the site). Pick a materials repo and choose for readings: `reading-list` (citations only) or `actual-readings` (also host the files). Because the materials repos are private, the site **hosts** the shared files itself. This is separate from each cohort's student-facing site.

### Session cadence actions:
- [**Release materials**](https://github.com/{org}/.github/actions/workflows/release-materials.yml) - publish a given session's content, from every discovered section, into a cohort repo.
- [**Release assignment**](https://github.com/{org}/.github/actions/workflows/release-assignment.yml) - generate one private repo per student from a chosen `assignment-*` template repo.

- [**Release code**](https://github.com/{org}/.github/actions/workflows/release-code.yml) - run from the repo holding your package; copy a chosen path (a subpackage folder, or a single module file) into a cohort repo's tree, additively. Phased disclosure of a growing importable package - release a topic when you teach it.

NB: alternatively each materials repo *also* carries its own **Release** buttons (run from inside the
repo; there the `session` is a dropdown of that repo's sessions, and each discovered section gets its
own include checkbox).

### Grades (private, previewable):
- [**Grade assignment**](https://github.com/{org}/.github/actions/workflows/grade-assignment.yml) - faculty-side autograder: after the deadline, run the HIDDEN tests (from the template's `solution` branch) against each submission and record the machine score into `classroom-config/grades/<assignment>.csv`. Nothing is written to student repos; faculty then add manual marks. Optional per assignment (skipped if `grading.yml` sets `autograde: false`).
- [**Sync gradebooks**](https://github.com/{org}/.github/actions/workflows/sync-gradebooks.yml) - ensure every onboarded student has a PRIVATE `grades-<handle>` repo (the single home for all their grades). Idempotent.
- [**Render grades (preview)**](https://github.com/{org}/.github/actions/workflows/render-grades.yml) - build per-student `gradebook/<handle>.yml` from `classroom-config/grades/<assignment>.csv` and open ONE pull request. **That PR is the preview** - review every student's grades in the diff before sending.
- [**Distribute grades**](https://github.com/{org}/.github/actions/workflows/distribute-grades.yml) - after merging the preview PR, copy each student's gradebook into their private repo and (unless silenced) email each student a notification to their university inbox (needs the `GRAPH_*` or `SMTP_*` secrets).

- [**Scheduled release**](https://github.com/{org}/.github/actions/workflows/scheduled-release.yml) - daily cron that auto-releases whatever each cohort's `manifests/<cohort>.yml` (in `.github`) and its `classroom-config/schedule.yml` say is due. Manual runs default to a dry-run preview ("what opens when"). Manual buttons above still work for early/ad-hoc release.

- _[**Sync site**](https://github.com/{org}/.github/actions/workflows/sync-site.yml) - regenerate a cohort's website from the org structure (releases do this automatically; standard workflow has no need for manual sync)._

## How the actions behave

**Release materials** - run it from the materials repo (per-repo `session` dropdown, real
checkboxes per discovered section) or from the course org's central `.github` repo (pick the
source repo, type the session, and optionally list sections to exclude - the source repo is
only known once you run it, so there are no per-section toggles there). It copies the *whole*
`<section>/<NN>_.../` folders - **every file** (any number of sections, and any number of
files per session) - into the cohort's `materials` repo (private + `students` read), nested
under that same folder name. Only the sessions you release appear. `include_syllabus` /
`include_readme` (default off) also copy those root files to the cohort root, overwriting.

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
reading list or as hosted files. It is opt-in and manual - releases and refresh never touch it - so a
public site only exists, and only updates, when you run the action.

## Repository structure (required)

```
{org}/                            <- this COURSE org (persistent)
|-- .github/                      profile + faculty action buttons + cohort registry
|-- course-materials-<year>/      lectures/00_.../   readings/00_.../   (+ syllabus, README)
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
[`dsl-teaching-course-setup`](https://github.com/hertie-data-science-lab/dsl-teaching-course-setup)
repo (via its **Bootstrap Course Org** action), and the actions above run that same central code.

The course-level actions assume this layout - use **New materials repo** / **New assignment** above to scaffold correctly.

**Materials repo** (`course-materials-<year>`) - the source for Release materials. Any
top-level directory containing at least one ordinal-prefixed (`00_`, `01_`, ...)
subdirectory is a releasable section - no config to declare it:
- `lectures/00_.../` - one folder per session's lecture files;
- `readings/00_.../` - one folder per session's readings;
- add more sections freely (e.g. `labs/00_.../`) - **Refresh actions** picks up new ones;
- `*syllabus*`, `README.md` at the **root** (optional) - released via the syllabus / README toggles.

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


def seed_github_workflows(course_org: str) -> None:
    """Seed/refresh the org-level workflows into the course org's .github repo: the
    CENTRAL Release materials (source-repo dropdown), Release assignment, plus Sync
    enrolment / Bootstrap cohort / Refresh."""
    cohorts = discover_cohorts(course_org)
    source_repos = discover_content_repos(course_org)
    assignments = discover_assignments(course_org)
    files = {
        ".github/workflows/release-materials.yml": render_central_release(
            source_repos, cohorts
        ),
        ".github/workflows/release-assignment.yml": render_provision(
            cohorts, assignments
        ),
        ".github/workflows/grade-assignment.yml": render_grade_assignment(
            cohorts, assignments
        ),
        ".github/workflows/new-materials.yml": render_new_materials(),
        ".github/workflows/new-assignment.yml": render_new_assignment(),
        ".github/workflows/sync-site.yml": render_sync_site(cohorts),
        ".github/workflows/publish-site.yml": render_publish_site(source_repos),
        ".github/workflows/sync-membership.yml": render_sync_membership(cohorts),
        ".github/workflows/send-codes.yml": render_send_codes(cohorts),
        ".github/workflows/sync-gradebooks.yml": render_sync_gradebooks(cohorts),
        ".github/workflows/render-grades.yml": render_render_grades(cohorts),
        ".github/workflows/distribute-grades.yml": render_distribute_grades(cohorts),
        ".github/workflows/bootstrap-cohort.yml": render_bootstrap_cohort(),
        ".github/workflows/status.yml": render_status(cohorts),
        ".github/workflows/refresh-actions.yml": render_refresh(),
        ".github/workflows/scheduled-release.yml": render_scheduler(),
    }
    log_step(f"Seeding org-level workflows into {course_org}/.github")
    for path, content in files.items():
        if put_file(
            course_org, ".github", path, content.encode(), f"ci: {path.split('/')[-1]}"
        ):
            log_ok(f".github <- {path.split('/')[-1]}")

    # Retired in favour of sync-membership.yml (one consolidated button) - remove any
    # copies already seeded into orgs bootstrapped before this change.
    for retired in (
        ".github/workflows/sync-enrolment.yml",
        ".github/workflows/sync-teams.yml",
    ):
        delete_file(course_org, ".github", retired, f"ci: retire {retired.split('/')[-1]} (superseded by sync-membership.yml)")


def _propagate_repo_secret(course_org: str, repos: list[str]) -> None:
    """On GitHub Free, org secrets don't reach PRIVATE repos - so set DSL_BOT_TOKEN as a
    repo secret on each content repo (from the token this run already holds), letting
    their run-from-repo workflows authenticate."""
    token = os.environ.get("DSL_BOT_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return
    for repo in repos:
        code, _ = gh(
            "secret",
            "set",
            "DSL_BOT_TOKEN",
            "--repo",
            f"{course_org}/{repo}",
            "--body",
            token,
        )
        if code == 0:
            log_ok(f"repo secret -> {repo}")


def refresh(course_org: str) -> int:
    """Refresh both layers: the run-from-repo content actions in every content repo,
    AND the central org-level workflows in .github; repopulate dropdowns; rebuild the
    org profile README; and (Free-plan workaround) propagate the token as a repo secret
    so private content repos can authenticate."""
    cohorts = discover_cohorts(course_org)
    cohort_repos = discover_cohort_repos(cohorts)
    targets = discover_content_repos(course_org)
    assignments = discover_assignments(
        course_org
    )  # org-wide; discover once, not per repo
    log_step(
        f"Refreshing {len(targets)} content repo(s) in {course_org} with cohorts {cohorts or 'none'}"
    )
    for repo in sorted(targets):
        _push_workflows(course_org, repo, cohorts, cohort_repos, assignments)
    _propagate_repo_secret(course_org, targets)
    seed_github_workflows(course_org)
    update_profile_readme(course_org)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("refresh")
    pr.add_argument("--course-org", required=True)
    args = parser.parse_args()
    return refresh(args.course_org)


if __name__ == "__main__":
    sys.exit(main())
