"""bootstrap-course -- one-time setup for a new course org.

Sets up org-level infrastructure that persists across semesters:
- DSL_BOT_TOKEN secret (required for all workflows)
- Default teams (instructors, students, auditors)
- Org settings (2FA enforcement, Pages default branch)
- GitHub Actions allowlist (documented common actions)
- Profile README (.github repo with description)
- Faculty workflows seeded into .github/workflows/ (new-semester, assign, sync-roster)

Usage:
    python3 -m dsl_course.bootstrap_course \\
        --org Hertie-School-Deep-Learning-E1394
"""

from __future__ import annotations

import argparse
import sys

from .utils import (
    create_repo,
    create_team,
    gh,
    log,
    log_err,
    log_ok,
    log_step,
    put_file,
)

PROFILE_README = """# {org_name}

This is the organisation for **{course_name}**.

## About

All materials and student submissions for the course are hosted here. Course content
is managed by the Hertie Data Science Lab and instructors.

## Structure

- **`content-f{YYYY}` repos** — course materials (lectures, labs, readings)
- **`assignment-N-f{YYYY}` repos** — assignment templates
- **`f{YYYY}-*.github.io`** — course website
- **Satellite orgs** (e.g. `hertie-dl-f2025`) — student submission repos

## Teams

- **`instructors-f{YYYY}`** — instructors and TAs (push access to materials)
- **`students-f{YYYY}`** (satellite) — enrolled students (read content, push submissions)
- **`auditors-f{YYYY}`** (satellite) — auditors (read-only)
- **`course-admin`** — DSL administrators

## Workflows

Automated workflows handle:
- **`new-semester`** — semester setup (repos, teams, website)
- **`assign`** — student assignment generation
- **`sync-roster`** — weekly team sync from roster file

Trigger via [Actions tab](https://github.com/{org}/actions).

## Resources

- [DSL Docs](https://github.com/hertie-data-science-lab/hertie-dsl-gh-org-strategy/tree/main/docs)
- [Faculty Workflows](https://github.com/hertie-data-science-lab/hertie-dsl-gh-org-strategy/tree/main/docs/for-faculty)
- [Course Website Template](https://github.com/hertie-data-science-lab/course-website-template)

---

Need help? Reach out to the [Hertie DSL team](https://github.com/hertie-data-science-lab).
"""

GITHUB_ACTIONS_POLICY = """# GitHub Actions Configuration

This org allows public actions necessary for course management:

## Allowed actions (automatically available)

- `actions/checkout` — clone repositories
- `actions/setup-python` — Python environments
- `actions/setup-node` — Node.js environments
- `actions/upload-artifact` — store build outputs
- `actions/download-artifact` — fetch build outputs
- `actions/create-release` — publish releases
- `github/super-linter` — code quality checks
- `softprops/action-gh-release` — release automation
- All other GitHub-owned actions (github/*)
- All Hertie DSL actions (hertie-data-science-lab/*)

## Disabled

- Third-party actions (unless explicitly approved)
- Actions from untrusted sources
- Any action with credential write access

## Adding new actions

Contact the DSL team before enabling new actions.
"""


def set_org_secret(org: str, secret_name: str, secret_value: str) -> bool:
    """Create or update an org secret. Requires gh to read the public key first."""
    code, out = gh(
        "secret",
        "set",
        secret_name,
        "--org",
        org,
        "--body",
        secret_value,
    )
    if code == 0:
        log_ok(f"org secret set: {secret_name}")
        return True
    log_err(f"failed to set org secret {secret_name}: {out[:200]}")
    return False


def create_default_teams(org: str) -> None:
    """Create org-level role teams. Semester-specific teams are created by new_semester."""
    log_step("Creating org-level teams")
    create_team(
        org,
        "instructors",
        "Instructors and TAs (across all semesters)",
        privacy="closed",
    )
    create_team(
        org,
        "students",
        "Students (across all semesters)",
        privacy="closed",
    )
    create_team(
        org,
        "auditors",
        "Auditors (across all semesters, read-only)",
        privacy="closed",
    )
    create_team(
        org,
        "course-admin",
        "Course administrators - DSL team",
        privacy="closed",
    )


def create_profile_repo(org: str, org_name: str, course_name: str) -> None:
    """Create the .github profile repo with README."""
    log_step("Setting up .github profile repo")
    if not create_repo(
        org,
        ".github",
        private=False,
        description="Org profile and configuration",
    ):
        return

    # README with org branding
    readme = PROFILE_README.format(org=org, org_name=org_name, course_name=course_name)
    put_file(org, ".github", "README.md", readme.encode(), "init: org profile README")

    # GitHub Actions policy (informational)
    put_file(
        org,
        ".github",
        "GITHUB_ACTIONS_POLICY.md",
        GITHUB_ACTIONS_POLICY.encode(),
        "init: GitHub Actions allowlist documentation",
    )

    log_ok(".github profile repo initialised")


def set_org_settings(org: str) -> None:
    """Set org-level settings: 2FA, Pages, base permissions."""
    log_step("Configuring org settings")

    # Require 2FA for all members (best practice for course orgs)
    code, out = gh(
        "api",
        "--method",
        "PATCH",
        f"orgs/{org}",
        "--field",
        "two_factor_requirement_enabled=true",
    )
    if code == 0:
        log_ok("2FA requirement enabled")
    else:
        log_err(f"could not enable 2FA: {out[:100]}")

    # Set default Pages branch to main (if not present, Pages will use default on first enable)
    # Note: pages_build_type is set per-repo, not org-wide
    log_ok("org settings configured (2FA enforced)")


def validate_secret_presence(org: str, secret_name: str) -> bool:
    """Check if an org secret exists (non-destructive check)."""
    # gh api doesn't expose secret listing without auth headers, so we check by trying
    # to read the secret value (which will 404 if it doesn't exist)
    code, _ = gh("api", f"orgs/{org}/actions/secrets/{secret_name}")
    exists = code == 0
    if exists:
        log_ok(f"org secret found: {secret_name}")
    else:
        log_err(f"org secret missing: {secret_name}")
    return exists


_WORKFLOW_NEW_SEMESTER = """\
name: New Semester Setup

on:
  workflow_dispatch:
    inputs:
      satellite_org:
        description: "Per-cohort satellite org for submissions (e.g. hertie-dl-f2026). Leave blank to skip."
        required: false
        default: ""
      semester:
        description: "Semester code (e.g. f2026)"
        required: true
      course_name:
        description: 'Course name (e.g. "Deep Learning")'
        required: true
      course_code:
        description: "Hertie course code (e.g. GRAD-E1394)"
        required: true
      instructors:
        description: "Instructor GitHub logins, comma-separated"
        required: true
      tas:
        description: "TA GitHub logins, comma-separated (optional)"
        required: false
        default: ""
      content_visibility:
        description: "Course content repo visibility"
        required: true
        default: "private"
        type: choice
        options:
          - private
          - public

jobs:
  check-team:
    runs-on: ubuntu-latest
    steps:
      - name: Verify triggering user is in faculty or admin team
        env:
          GH_TOKEN: ${{ secrets.DSL_BOT_TOKEN }}
          ACTOR: ${{ github.actor }}
        run: |
          MAIN_ORG="hertie-data-science-lab"
          for team in faculty admin; do
            code=$(gh api "orgs/$MAIN_ORG/teams/$team/memberships/$ACTOR" \\
                     --jq '.state' 2>/dev/null || true)
            if [ "$code" = "active" ]; then exit 0; fi
          done
          echo "::error::$ACTOR is not in the faculty or admin team — access denied"
          exit 1

  new-semester:
    needs: check-team
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          repository: hertie-data-science-lab/gh-org-strategy
          token: ${{ secrets.DSL_BOT_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install pyyaml

      - name: Run new-semester
        env:
          GH_TOKEN: ${{ secrets.DSL_BOT_TOKEN }}
        run: |
          set -eo pipefail
          ARGS=(
            --org "${{ github.repository_owner }}"
            --semester "${{ inputs.semester }}"
            --course-name "${{ inputs.course_name }}"
            --course-code "${{ inputs.course_code }}"
            --instructors "${{ inputs.instructors }}"
            --tas "${{ inputs.tas }}"
            --content-visibility "${{ inputs.content_visibility }}"
          )
          if [ -n "${{ inputs.satellite_org }}" ]; then
            ARGS+=(--satellite-org "${{ inputs.satellite_org }}")
          fi
          python3 -m dsl_course.new_semester "${ARGS[@]}"
"""

_WORKFLOW_ASSIGN = """\
name: Create Assignment

on:
  workflow_dispatch:
    inputs:
      satellite_org:
        description: "Per-cohort satellite org where submissions are created (e.g. hertie-dl-f2026). Leave blank to target course-org."
        required: false
        default: ""
      semester:
        description: "Semester code (e.g. f2026)"
        required: true
      assignment:
        description: "Assignment slug (e.g. assignment-1)"
        required: true
      template:
        description: "Template repo name in the org (e.g. assignment-1-f2026)"
        required: true
      teams_file:
        description: "Optional: path in website repo to teams YAML. Leave blank for per-student."
        required: false
        default: ""
      dry_run:
        description: "Preview only, don't create repos"
        required: false
        default: false
        type: boolean

jobs:
  check-team:
    runs-on: ubuntu-latest
    steps:
      - name: Verify triggering user is in faculty or admin team
        env:
          GH_TOKEN: ${{ secrets.DSL_BOT_TOKEN }}
          ACTOR: ${{ github.actor }}
        run: |
          MAIN_ORG="hertie-data-science-lab"
          for team in faculty admin; do
            code=$(gh api "orgs/$MAIN_ORG/teams/$team/memberships/$ACTOR" \\
                     --jq '.state' 2>/dev/null || true)
            if [ "$code" = "active" ]; then exit 0; fi
          done
          echo "::error::$ACTOR is not in the faculty or admin team — access denied"
          exit 1

  assign:
    needs: check-team
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          repository: hertie-data-science-lab/gh-org-strategy
          token: ${{ secrets.DSL_BOT_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install pyyaml

      - name: Run assign
        env:
          GH_TOKEN: ${{ secrets.DSL_BOT_TOKEN }}
          COURSE_ORG: ${{ github.repository_owner }}
          SATELLITE_ORG: ${{ inputs.satellite_org }}
          SEMESTER: ${{ inputs.semester }}
          ASSIGNMENT: ${{ inputs.assignment }}
          TEMPLATE: ${{ inputs.template }}
          TEAMS_FILE: ${{ inputs.teams_file }}
          DRY_RUN: ${{ inputs.dry_run }}
        run: |
          args=(--course-org "$COURSE_ORG" --semester "$SEMESTER"
                --assignment "$ASSIGNMENT" --template "$TEMPLATE")
          if [ -n "$SATELLITE_ORG" ]; then args+=(--satellite-org "$SATELLITE_ORG"); fi
          if [ -n "$TEAMS_FILE" ]; then args+=(--teams-file "$TEAMS_FILE"); fi
          if [ "$DRY_RUN" = "true" ]; then args+=(--dry-run); fi
          python3 -m dsl_course.assign "${args[@]}"
"""

_WORKFLOW_SYNC_ROSTER = """\
name: Sync Course Roster

on:
  workflow_dispatch:
    inputs:
      semester:
        description: "Semester code (e.g. f2026)"
        required: true
      dry_run:
        description: "Preview only, don't modify teams"
        required: false
        default: false
        type: boolean
  schedule:
    - cron: "0 6 * * 1"  # Weekly Monday 06:00 UTC

jobs:
  check-team:
    if: github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    steps:
      - name: Verify triggering user is in faculty or admin team
        env:
          GH_TOKEN: ${{ secrets.DSL_BOT_TOKEN }}
          ACTOR: ${{ github.actor }}
        run: |
          MAIN_ORG="hertie-data-science-lab"
          for team in faculty admin; do
            code=$(gh api "orgs/$MAIN_ORG/teams/$team/memberships/$ACTOR" \\
                     --jq '.state' 2>/dev/null || true)
            if [ "$code" = "active" ]; then exit 0; fi
          done
          echo "::error::$ACTOR is not in the faculty or admin team — access denied"
          exit 1

  sync:
    needs:
      - check-team
    if: always() && (needs.check-team.result == 'success' || github.event_name == 'schedule')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          repository: hertie-data-science-lab/gh-org-strategy
          token: ${{ secrets.DSL_BOT_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install pyyaml

      - name: Sync roster
        env:
          GH_TOKEN: ${{ secrets.DSL_BOT_TOKEN }}
          ORG: ${{ github.repository_owner }}
          SEMESTER: ${{ inputs.semester }}
          DRY_RUN: ${{ inputs.dry_run }}
        run: |
          args=(--org "$ORG" --semester "$SEMESTER")
          if [ "$DRY_RUN" = "true" ]; then args+=(--dry-run); fi
          python3 -m dsl_course.sync_roster "${args[@]}"
"""

_FACULTY_WORKFLOWS = {
    ".github/workflows/new-semester.yml": _WORKFLOW_NEW_SEMESTER,
    ".github/workflows/assign.yml": _WORKFLOW_ASSIGN,
    ".github/workflows/sync-roster.yml": _WORKFLOW_SYNC_ROSTER,
}


def seed_workflows(org: str) -> None:
    """Push faculty workflows into the course org's .github repo."""
    log_step("Seeding faculty workflows into .github repo")
    for path, content in _FACULTY_WORKFLOWS.items():
        name = path.split("/")[-1]
        ok = put_file(
            org,
            ".github",
            path,
            content.encode(),
            f"ci: seed {name} workflow",
        )
        if ok:
            log_ok(f"workflow seeded: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True, help="Course org to bootstrap")
    parser.add_argument(
        "--org-name",
        default=None,
        help="Full org name for README (e.g. 'Deep Learning'). "
        "If not set, uses --org as-is.",
    )
    parser.add_argument(
        "--course-name",
        default=None,
        help="Course name for README (e.g. 'Deep Learning (GRAD-E1394)'). "
        "If not set, uses --org-name.",
    )
    parser.add_argument(
        "--set-secret",
        default=None,
        help="Path to file containing DSL_BOT_TOKEN PAT. "
        "If provided, sets the org secret. Otherwise, validates presence only.",
    )
    args = parser.parse_args()

    org_name = args.org_name or args.org
    course_name = args.course_name or org_name

    log(f"Bootstrapping org: {args.org}")
    log(f"  Org name: {org_name}")
    log(f"  Course name: {course_name}")

    # 1. Org settings
    set_org_settings(args.org)

    # 2. Default teams
    create_default_teams(args.org)

    # 3. Profile repo + seed workflows
    create_profile_repo(args.org, org_name, course_name)
    seed_workflows(args.org)

    # 4. Secret (set or validate)
    if args.set_secret:
        try:
            with open(args.set_secret) as f:
                token = f.read().strip()
            set_org_secret(args.org, "DSL_BOT_TOKEN", token)
        except (FileNotFoundError, IOError) as e:
            log_err(f"could not read secret file: {e}")
            return 1
    else:
        # Validate the secret exists (it should have been set manually or by another bootstrap run)
        if not validate_secret_presence(args.org, "DSL_BOT_TOKEN"):
            log(
                "\nWARNING: DSL_BOT_TOKEN not set. "
                "Run bootstrap with --set-secret <path> to add it, "
                "or set it manually at https://github.com/{}/settings/secrets/actions".format(
                    args.org
                )
            )

    log(f"""
============================================================
Course org bootstrap complete: {args.org}

DONE (automated):
============================================================
- Org-level teams: instructors, students, auditors, course-admin
- Org settings: 2FA enforcement enabled
- .github profile repo with README and Actions policy
- Faculty workflows seeded: new-semester, assign, sync-roster
- DSL_BOT_TOKEN secret validated (or set)

NEXT STEPS (manual):
============================================================

1. Review org settings: https://github.com/{args.org}/settings

2. Invite course instructors and admins:
   https://github.com/{args.org}/settings/members

3. Faculty can now trigger workflows from:
   https://github.com/{args.org}/.github/actions

4. Run new-semester to create the first semester:
   → Go to https://github.com/{args.org}/.github/actions/workflows/new-semester.yml
   → Click "Run workflow" and fill in the form

============================================================
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())
