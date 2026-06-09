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
import sys

import yaml

from .utils import get_file_content, gh, log, log_ok, log_step, put_file, repo_exists

COHORTS_PATH = (
    "cohort-courses-pages.yml"  # standalone registry in the course org's .github repo
)

CENTRAL = "hertie-data-science-lab/dsl-teaching-course-setup"
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
          # Org owners always pass; otherwise must be on this course's instructors/course-admin team.
          role=$(gh api "orgs/$ORG/memberships/$ACTOR" --jq '.role' 2>/dev/null || true)
          if [ "$role" = "admin" ]; then exit 0; fi
          for team in instructors course-admin; do
            state=$(gh api "orgs/$ORG/teams/$team/memberships/$ACTOR" --jq '.state' 2>/dev/null || true)
            if [ "$state" = "active" ]; then exit 0; fi
          done
          echo "::error::@$ACTOR is not an owner or on $ORG's instructors/course-admin team (or DSL_BOT_TOKEN is missing/lacks org read)"
          exit 1
"""

_RUN_PREAMBLE = f"""    needs: check-team
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          repository: {CENTRAL}
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
"""


def _choice(options: list[str]) -> str:
    opts = options or ["(none-yet)"]
    return "\n".join(f"          - {o}" for o in opts)


def render_release(cohort_orgs: list[str], cohort_repos: list[str]) -> str:
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
      week:
        description: "Week number (e.g. 1)"
        required: true
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


def render_provision(cohort_orgs: list[str]) -> str:
    return f"""name: Release assignment

# Run from an assignment-template repo (this repo is the TEMPLATE). Generates one
# private {{assignment}}-{{handle}} repo per onboarded student in the chosen cohort.

on:
  workflow_dispatch:
    inputs:
      cohort_org:
        description: "Target cohort org"
        required: true
        type: choice
        options:
{_choice(cohort_orgs)}
      assignment:
        description: "Assignment slug (e.g. assignment-1)"
        required: true
      dry_run:
        description: "Preview only"
        type: boolean
        default: false

jobs:
{_CHECK_TEAM}
  provision:
{_RUN_PREAMBLE}      - name: Provision
        env:
          GH_TOKEN: ${{{{ secrets.DSL_BOT_TOKEN }}}}
          MASTER_ORG: ${{{{ github.repository_owner }}}}
          TEMPLATE: ${{{{ github.event.repository.name }}}}
          COHORT_ORG: ${{{{ inputs.cohort_org }}}}
          ASSIGNMENT: ${{{{ inputs.assignment }}}}
          DRY_RUN: ${{{{ inputs.dry_run }}}}
        run: |
          args=(--master-org "$MASTER_ORG" --template "$TEMPLATE"
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


def discover_equipped_repos(course_org: str) -> list[str]:
    """Course-org repos that already carry the release wrapper."""
    code, out = gh(
        "repo",
        "list",
        course_org,
        "--limit",
        "200",
        "--json",
        "name",
        "--jq",
        ".[].name",
    )
    if code != 0:
        return []
    equipped = []
    for r in out.splitlines():
        # .github holds org-level buttons (not content actions); the template is
        # refreshed separately. Skip both so they never get content wrappers.
        if r in (".github", TEMPLATE_REPO):
            continue
        if (
            gh(
                "api",
                f"repos/{course_org}/{r}/contents/.github/workflows/release-materials.yml",
            )[0]
            == 0
        ):
            equipped.append(r)
    return equipped


def _push_workflows(
    org: str, repo: str, cohort_orgs: list[str], cohort_repos: list[str]
) -> None:
    put_file(
        org,
        repo,
        WORKFLOWS[0],
        render_release(cohort_orgs, cohort_repos).encode(),
        "ci: release-materials wrapper",
    )
    put_file(
        org,
        repo,
        WORKFLOWS[1],
        render_provision(cohort_orgs).encode(),
        "ci: provision-assignment wrapper",
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


def render_profile_readme(
    org: str, org_name: str, course_name: str, repos: list[dict]
) -> str:
    """Org overview: a header + a clickable table indexing the org's repos."""
    rows = []
    for r in sorted(repos, key=lambda x: x["name"].lower()):
        if r["name"] == ".github":
            continue
        desc = (r.get("description") or "").replace("|", "\\|").strip()
        rows.append(
            f"| [{r['name']}]({r['url']}) | {r['visibility'].lower()} | {desc} |"
        )
    table = "\n".join(rows) or "| _(no repos yet)_ | | |"
    return f"""# {org_name}

**{course_name}** — managed by the Hertie Data Science Lab.
_This page is auto-generated; edits will be overwritten on the next refresh._

## Repositories

| Repo | Visibility | Description |
| --- | --- | --- |
{table}

## Faculty actions

- **Release materials** / **Release assignment** — run from inside a content or
  assignment-template repo (its own Actions tab; the repo is the source).
- **Enroll student** / **Equip repo** / **Refresh actions** — in the
  [.github repo's Actions tab](https://github.com/{org}/.github/actions).

---
Maintained by the [Hertie Data Science Lab](https://github.com/hertie-data-science-lab).
"""


def update_profile_readme(
    org: str, org_name: str | None = None, course_name: str | None = None
) -> None:
    """(Re)generate the org's profile/README.md from its metadata + live repo list."""
    if org_name is None or course_name is None:
        cfg = {}
        content = get_file_content(org, ".github", "dsl-course.yml")
        if content:
            cfg = yaml.safe_load(content) or {}
        org_name = org_name or cfg.get("org_name") or org
        course_name = course_name or cfg.get("course_name") or org_name
    body = render_profile_readme(org, org_name, course_name, list_org_repos(org))
    put_file(
        org,
        ".github",
        "profile/README.md",
        body.encode(),
        "docs: refresh org profile README (repo index)",
    )
    log_ok("profile README refreshed")


def refresh(course_org: str) -> int:
    cohorts = discover_cohorts(course_org)
    cohort_repos = discover_cohort_repos(cohorts)
    targets = set(discover_equipped_repos(course_org))
    if repo_exists(course_org, TEMPLATE_REPO):
        targets.add(TEMPLATE_REPO)
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
