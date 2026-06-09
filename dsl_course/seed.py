"""dsl-course seed -- render + place the run-from-repo faculty workflows.

The Release / Provision actions live INSIDE course content (and assignment-template)
repos, so faculty trigger them from the repo they're working in. The repo the workflow
runs in is the SOURCE; the action pushes into a chosen cohort org/repo.

The cohort org / cohort repo inputs are GitHub `choice` dropdowns. GitHub can't
populate a dropdown live, so the options are rendered into the YAML from the cohort
registry and refreshed on demand: `refresh` reads the course org's
.github/cohort-courses-pages.yml `cohorts:` list (maintained by `bootstrap --cohort
--course X`, or by hand), lists their repos, and re-pushes the workflows to the
content-template + every already-equipped repo. No cron, no app.

Actions:
  equip   --course-org X --repo R   push the two wrappers into course-org/R
  refresh --course-org X            re-render with fresh options + push to the
                                    content-template and all equipped repos
"""

from __future__ import annotations

import argparse
import json
import re
import sys

import yaml

from .utils import get_file_content, gh, log, log_ok, log_step, put_file, repo_exists

COHORTS_PATH = (
    "cohort-courses-pages.yml"  # standalone registry in the course org's .github repo
)

CENTRAL = "hertie-data-science-lab/dsl-teaching-course-setup"
# TEMP: seeded workflows run code from this ref. While PR #9 is unmerged we pin to the
# branch so the buttons work; set back to "main" (or drop the ref:) once it's merged.
CENTRAL_REF = "feature/adr-0010-inverted-model"
TEMPLATE_REPO = "content-template"
# Target is ONE cohort repo holding lectures/ + readings/ as SUBDIRS (not separate
# repos), so the only default target is `materials`; real content repos are discovered.
DEFAULT_COHORT_REPOS = ["materials"]
INFRA_REPOS = {"welcome", "classroom-config", ".github"}
WORKFLOWS = (
    ".github/workflows/release-materials.yml",
    ".github/workflows/release-assignment.yml",
)

_CHECK_TEAM = """  check-team:
    runs-on: ubuntu-latest
    steps:
      - name: Verify the user may run actions for THIS course org
        env:
          GH_TOKEN: ${{ secrets.DSL_BOT_TOKEN }}
          ACTOR: ${{ github.actor }}
          ORG: ${{ github.repository_owner }}
        run: |
          # Org owners pass; else must be on this course's instructors/course-admin team.
          role=$(gh api "orgs/$ORG/memberships/$ACTOR" --jq '.role' 2>/tmp/gherr || true)
          if [ "$role" = "admin" ]; then exit 0; fi
          for team in instructors course-admin; do
            state=$(gh api "orgs/$ORG/teams/$team/memberships/$ACTOR" --jq '.state' 2>>/tmp/gherr || true)
            if [ "$state" = "active" ]; then exit 0; fi
          done
          echo "::error::@$ACTOR not authorised for $ORG (role='$role'). gh api errors (if any):"
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


def _choice(options: list[str]) -> str:
    opts = options or ["(none-yet)"]
    return "\n".join(f"          - {o}" for o in opts)


def _week_input(weeks: list[str]) -> str:
    """Week as a dropdown of discovered weeks, or a free-text box if none found yet."""
    if weeks:
        return (
            '      week:\n        description: "Week to release"\n'
            "        required: true\n        type: choice\n        options:\n"
            + _choice(weeks)
        )
    return '      week:\n        description: "Week number (e.g. 1)"\n        required: true'


def render_release(
    cohort_orgs: list[str], cohort_repos: list[str], weeks: list[str] | None = None
) -> str:
    return f"""name: Release materials

# Run from a course content repo (this repo is the SOURCE). Publishes one week's
# lecture/reading files into the chosen cohort repo. Dropdowns are refreshed by the
# 'Refresh actions' workflow.

on:
  workflow_dispatch:
    inputs:
      cohort_org:
        description: "Target cohort org"
        required: true
        type: choice
        options:
{_choice(cohort_orgs)}
      cohort_repo:
        description: "Target repo in the cohort org"
        required: true
        type: choice
        options:
{_choice(cohort_repos)}
{_week_input(weeks or [])}
      include_lectures:
        description: "Include lectures"
        type: boolean
        default: true
      include_readings:
        description: "Include readings"
        type: boolean
        default: true

jobs:
{_CHECK_TEAM}
  release:
{_RUN_PREAMBLE}      - name: Release
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          SRC_ORG: ${{{{ github.repository_owner }}}}
          SRC_REPO: ${{{{ github.event.repository.name }}}}
          COHORT_ORG: ${{{{ inputs.cohort_org }}}}
          COHORT_REPO: ${{{{ inputs.cohort_repo }}}}
          WEEK: ${{{{ inputs.week }}}}
          INC_LEC: ${{{{ inputs.include_lectures }}}}
          INC_READ: ${{{{ inputs.include_readings }}}}
        run: |
          gh auth setup-git
          args=(--source-org "$SRC_ORG" --source-repo "$SRC_REPO"
                --cohort-org "$COHORT_ORG" --cohort-repo "$COHORT_REPO" --week "$WEEK")
          [ "$INC_LEC" = "false" ] && args+=(--no-lectures)
          [ "$INC_READ" = "false" ] && args+=(--no-readings)
          python3 -m dsl_course.release "${{args[@]}}"
"""


def _assignment_input(assignments: list[str]) -> str:
    """Assignment as a dropdown of discovered assignments/ folders, or free-text."""
    if assignments:
        return (
            '      assignment:\n        description: "Assignment"\n'
            "        required: true\n        type: choice\n        options:\n"
            + _choice(assignments)
        )
    return (
        '      assignment:\n        description: "Assignment folder (e.g. assignment-1)"\n'
        "        required: true"
    )


def render_provision(
    cohort_orgs: list[str], assignments: list[str] | None = None
) -> str:
    return f"""name: Release assignment

# Run from a content repo (this repo is the SOURCE). Copies one assignments/<name>/
# folder into a private repo per onboarded student in the chosen cohort.

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
      dry_run:
        description: "Preview only — list the repos that WOULD be created, don't create them"
        type: boolean
        default: false

jobs:
{_CHECK_TEAM}
  provision:
{_RUN_PREAMBLE}      - name: Provision
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          SRC_ORG: ${{{{ github.repository_owner }}}}
          SRC_REPO: ${{{{ github.event.repository.name }}}}
          COHORT_ORG: ${{{{ inputs.cohort_org }}}}
          ASSIGNMENT: ${{{{ inputs.assignment }}}}
          DRY_RUN: ${{{{ inputs.dry_run }}}}
        run: |
          args=(--source-org "$SRC_ORG" --source-repo "$SRC_REPO"
                --cohort-org "$COHORT_ORG" --assignment "$ASSIGNMENT")
          [ "$DRY_RUN" = "true" ] && args+=(--dry-run)
          python3 -m dsl_course.assign "${{args[@]}}"
"""


def render_enroll(cohort_orgs: list[str]) -> str:
    """Org-level enrol (faculty override for the self-service Join issue)."""
    return f"""name: Enroll student

on:
  workflow_dispatch:
    inputs:
      cohort_org:
        description: "Cohort org"
        required: true
        type: choice
        options:
{_choice(cohort_orgs)}
      handle:
        description: "GitHub handle to enroll (blank = sync whole roster)"
        required: false
        default: ""
      prune:
        description: "When syncing the whole roster, remove members no longer on it"
        type: boolean
        default: false

jobs:
{_CHECK_TEAM}
  enroll:
{_RUN_PREAMBLE}      - name: Enroll
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          COHORT_ORG: ${{{{ inputs.cohort_org }}}}
          HANDLE: ${{{{ inputs.handle }}}}
          PRUNE: ${{{{ inputs.prune }}}}
        run: |
          args=(--cohort-org "$COHORT_ORG")
          [ -n "$HANDLE" ] && args+=(--handle "$HANDLE")
          [ "$PRUNE" = "true" ] && args+=(--prune)
          python3 -m dsl_course.sync_roster "${{args[@]}}"
"""


def render_equip() -> str:
    """Retrofit an existing course repo with the release/provision wrappers."""
    return f"""name: Equip repo

on:
  workflow_dispatch:
    inputs:
      repo:
        description: "Repo in THIS org to add the release/provision actions to"
        required: true

jobs:
{_CHECK_TEAM}
  equip:
{_RUN_PREAMBLE}      - name: Equip
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
        run: |
          python3 -m dsl_course.seed equip --course-org "${{{{ github.repository_owner }}}}" --repo "${{{{ inputs.repo }}}}"
"""


def render_refresh() -> str:
    """Repopulate the cohort dropdowns across the template + all equipped repos."""
    return f"""name: Refresh actions

on:
  workflow_dispatch: {{}}

jobs:
{_CHECK_TEAM}
  refresh:
{_RUN_PREAMBLE}      - name: Refresh
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
        run: |
          python3 -m dsl_course.seed refresh --course-org "${{{{ github.repository_owner }}}}"
"""


def _read_cohorts(course_org: str) -> list[str]:
    """Read the course org's standalone .github/cohorts.yml registry."""
    content = get_file_content(course_org, ".github", COHORTS_PATH)
    if not content:
        return []
    data = yaml.safe_load(content) or []
    cohorts = data.get("cohorts", []) if isinstance(data, dict) else data
    return [c for c in cohorts if c]


def discover_cohorts(course_org: str) -> list[str]:
    """Cohort orgs are listed explicitly in the course's .github/cohorts.yml
    (naming-independent). `bootstrap --cohort --course X` appends; faculty can edit it."""
    return sorted(_read_cohorts(course_org))


def register_cohort(course_org: str, cohort_org: str) -> None:
    """Append cohort_org to the course's cohorts.yml registry (idempotent)."""
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
    """Candidate target repos: the default(s) + real cohort content repos, excluding
    infra (welcome/classroom-config/.github) and per-student submission repos (tagged
    `submission` by the provisioner)."""
    repos = set(DEFAULT_COHORT_REPOS)
    for org in cohort_orgs:
        code, out = gh(
            "repo", "list", org, "--limit", "300", "--json", "name,repositoryTopics"
        )
        if code != 0:
            continue
        for r in json.loads(out):
            topics = {t["name"] for t in (r.get("repositoryTopics") or [])}
            if r["name"] in INFRA_REPOS or "submission" in topics:
                continue
            repos.add(r["name"])
    return sorted(repos)


def discover_weeks(org: str, repo: str) -> list[str]:
    """Weeks present in a content repo, from lectures/Session<n>_* and
    readings/required/session-<nn>. Used to populate the week dropdown."""
    weeks = set()
    code, out = gh("api", f"repos/{org}/{repo}/contents/lectures", "--jq", ".[].name")
    if code == 0:
        for name in out.splitlines():
            m = re.match(r"Session0*(\d+)", name)
            if m:
                weeks.add(int(m.group(1)))
    code, out = gh(
        "api", f"repos/{org}/{repo}/contents/readings/required", "--jq", ".[].name"
    )
    if code == 0:
        for name in out.splitlines():
            m = re.match(r"session-0*(\d+)", name)
            if m:
                weeks.add(int(m.group(1)))
    return [str(w) for w in sorted(weeks)]


def discover_assignments(org: str, repo: str) -> list[str]:
    """Assignment folder names under assignments/ in a content repo (the dropdown)."""
    code, out = gh(
        "api",
        f"repos/{org}/{repo}/contents/assignments",
        "--jq",
        '.[] | select(.type=="dir") | .name',
    )
    return sorted(out.splitlines()) if code == 0 and out else []


def discover_content_repos(course_org: str) -> list[str]:
    """Every repo in the course org that should carry the content actions — i.e. all
    of them except the `.github` profile repo (which holds the org-level buttons).
    Refresh seeds the release/assignment actions into all of these."""
    return [r["name"] for r in list_org_repos(course_org) if r["name"] != ".github"]


def _push_workflows(
    org: str, repo: str, cohort_orgs: list[str], cohort_repos: list[str]
) -> None:
    weeks = discover_weeks(org, repo)
    assignments = discover_assignments(org, repo)
    put_file(
        org,
        repo,
        WORKFLOWS[0],
        render_release(cohort_orgs, cohort_repos, weeks).encode(),
        "ci: release-materials wrapper",
    )
    put_file(
        org,
        repo,
        WORKFLOWS[1],
        render_provision(cohort_orgs, assignments).encode(),
        "ci: release-assignment wrapper",
    )
    log_ok(f"workflows -> {org}/{repo}")


def equip(course_org: str, repo: str) -> int:
    cohorts = discover_cohorts(course_org)
    cohort_repos = discover_cohort_repos(cohorts)
    log_step(f"Equipping {course_org}/{repo} (cohorts: {cohorts or 'none yet'})")
    if not repo_exists(course_org, repo):
        log("  [err] repo does not exist — create it first")
        return 1
    _push_workflows(course_org, repo, cohorts, cohort_repos)
    return 0


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


def render_profile_readme(
    org: str, org_name: str, course_name: str, repos: list[dict], is_cohort: bool
) -> str:
    """Org overview. Cohort orgs get a student-facing page; course orgs a faculty one."""
    table = _repo_table(repos)
    if is_cohort:
        return f"""# {course_name}

Welcome! This is the course organisation for **{course_name}**.

## Getting started

1. Open a **Join** issue in
   [`welcome`](https://github.com/{org}/welcome/issues/new/choose) to enrol — your
   GitHub handle is captured automatically.
2. Once you're enrolled, course **materials** open up here week by week, and your
   own assignment repositories appear in this org.

## Where things are

| Repo | Visibility | What it's for |
| --- | --- | --- |
{table}

---
_Hertie Data Science Lab. This page is auto-generated._
"""
    return f"""# {org_name}

**{course_name}** — managed by the Hertie Data Science Lab.
_This page is auto-generated; edits will be overwritten on the next refresh._

## Repositories

| Repo | Visibility | Description |
| --- | --- | --- |
{table}

## Available actions for faculty & admin

Content actions — run from inside a content repo (that repo is the source); the links
below open the copy in `content-template`, but they live in every content repo:

- [**Release materials**](https://github.com/{org}/content-template/actions/workflows/release-materials.yml) — publish one week's lectures/readings into a cohort repo.
- [**Release assignment**](https://github.com/{org}/content-template/actions/workflows/release-assignment.yml) — create a private repo per student from an `assignments/<n>/` folder.

Org actions — in the `.github` repo:

- [**Enroll student**](https://github.com/{org}/.github/actions/workflows/enroll-student.yml) — grant a student org + `students`-team access.
- [**Equip repo**](https://github.com/{org}/.github/actions/workflows/equip-repo.yml) — add the two content actions to an existing repo (repos made from `content-template` already have them; Equip retrofits older ones).
- [**Refresh actions**](https://github.com/{org}/.github/actions/workflows/refresh-actions.yml) — repopulate the cohort/week/assignment dropdowns and rebuild this index.

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
        content = get_file_content(org, ".github", "dsl-course.yml")
        if content:
            cfg = yaml.safe_load(content) or {}
        org_name = org_name or cfg.get("org_name") or org
        course_name = course_name or cfg.get("course_name") or org_name
    repos = list_org_repos(org)
    is_cohort = any(r["name"] == "welcome" for r in repos)
    body = render_profile_readme(org, org_name, course_name, repos, is_cohort)
    put_file(
        org,
        ".github",
        "profile/README.md",
        body.encode(),
        "docs: refresh org profile README (repo index)",
    )
    log_ok("profile README refreshed")


def refresh(course_org: str) -> int:
    """Seed/refresh the content actions into EVERY repo in the course org (except
    .github), refresh the cohort dropdowns, and rebuild the org profile README."""
    cohorts = discover_cohorts(course_org)
    cohort_repos = discover_cohort_repos(cohorts)
    targets = discover_content_repos(course_org)
    log_step(
        f"Refreshing {len(targets)} repo(s) in {course_org} with cohorts {cohorts or 'none'}"
    )
    for repo in sorted(targets):
        _push_workflows(course_org, repo, cohorts, cohort_repos)
    update_profile_readme(course_org)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    pe = sub.add_parser("equip")
    pe.add_argument("--course-org", required=True)
    pe.add_argument("--repo", required=True)
    pr = sub.add_parser("refresh")
    pr.add_argument("--course-org", required=True)
    args = parser.parse_args()
    if args.cmd == "equip":
        return equip(args.course_org, args.repo)
    return refresh(args.course_org)


if __name__ == "__main__":
    sys.exit(main())
