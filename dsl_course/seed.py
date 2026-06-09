"""dsl-course seed -- render + place the run-from-repo faculty workflows.

The Release / Provision actions live INSIDE course content (and assignment-template)
repos, so faculty trigger them from the repo they're working in. The repo the workflow
runs in is the SOURCE; the action pushes into a chosen cohort org/repo.

The cohort org / cohort repo inputs are GitHub `choice` dropdowns. GitHub can't
populate a dropdown live, so the options are rendered into the YAML from the current
cohorts and refreshed on demand: `refresh` re-discovers cohorts ({course-org}-*) and
their repos and re-pushes the workflows to the content-template + every already-equipped
repo. No cron, no app.

Actions:
  equip   --course-org X --repo R   push the two wrappers into course-org/R
  refresh --course-org X            re-render with fresh options + push to the
                                    content-template and all equipped repos
"""

from __future__ import annotations

import argparse
import sys

from .utils import gh, log, log_ok, log_step, put_file, repo_exists

CENTRAL = "hertie-data-science-lab/dsl-teaching-course-setup"
TEMPLATE_REPO = "content-template"
DEFAULT_COHORT_REPOS = ["materials", "lecture-slides", "readings", "slides"]
WORKFLOWS = (
    ".github/workflows/release-materials.yml",
    ".github/workflows/provision-assignment.yml",
)

_CHECK_TEAM = """  check-team:
    runs-on: ubuntu-latest
    steps:
      - name: Verify triggering user is in faculty or admin team
        env:
          GH_TOKEN: ${{ secrets.DSL_BOT_TOKEN }}
          ACTOR: ${{ github.actor }}
        run: |
          for team in faculty admin; do
            state=$(gh api "orgs/hertie-data-science-lab/teams/$team/memberships/$ACTOR" --jq '.state' 2>/dev/null || true)
            if [ "$state" = "active" ]; then exit 0; fi
          done
          echo "::error::could not verify @$ACTOR is in the faculty/admin team (or DSL_BOT_TOKEN is missing/lacks org read)"
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
    return f"""name: Provision assignment

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


def discover_cohorts(course_org: str) -> list[str]:
    """Cohort orgs = orgs the bot belongs to named '{course_org}-*'."""
    code, out = gh("api", "/user/orgs", "--paginate", "--jq", ".[].login")
    if code != 0:
        return []
    return sorted(o for o in out.splitlines() if o.startswith(f"{course_org}-"))


def discover_cohort_repos(cohort_orgs: list[str]) -> list[str]:
    repos = set(DEFAULT_COHORT_REPOS)
    for org in cohort_orgs:
        code, out = gh(
            "repo", "list", org, "--limit", "200", "--json", "name", "--jq", ".[].name"
        )
        if code == 0:
            repos |= set(out.splitlines())
    return sorted(r for r in repos if r)


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
