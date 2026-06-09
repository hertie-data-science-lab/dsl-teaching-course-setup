"""bootstrap-course -- one-time setup for a new course org.

Sets up org-level infrastructure that persists across semesters:
- DSL_BOT_TOKEN secret (required for all workflows)
- Default teams (instructors, students, auditors)
- Org settings (2FA enforcement, Pages default branch)
- GitHub Actions allowlist (documented common actions)
- Profile README (.github repo with description)
- Faculty workflows seeded into .github/workflows/ (provision-assignment,
  release-materials, enroll-student)

With --cohort, also tightens the org and seeds the student-facing welcome (onboard)
and classroom-config (roster) repos.

Usage:
    python3 -m dsl_course.bootstrap_course --org Hertie-School-Deep-Learning-E1394
    python3 -m dsl_course.bootstrap_course --org Deep-Learning-f2026 --cohort
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .utils import (
    create_repo,
    create_team,
    gh,
    log,
    log_err,
    log_ok,
    log_step,
    put_file,
    set_repo_topics,
)

COURSE_HUB_TOPIC = "dsl-course-hub"

PROFILE_README = """# {org_name}

This is the organisation for **{course_name}**.

## About

All materials and student submissions for the course are hosted here. Course content
is managed by the Hertie Data Science Lab and instructors.

## Structure

- **`content-f{{YYYY}}` repos** — course materials (lectures, labs, readings)
- **`assignment-N-f{{YYYY}}` repos** — assignment templates
- **`f{{YYYY}}-*.github.io`** — course website
- **Satellite orgs** (e.g. `hertie-dl-f2025`) — student submission repos

## Teams

- **`instructors-f{{YYYY}}`** — instructors and TAs (push access to materials)
- **`students-f{{YYYY}}`** (satellite) — enrolled students (read content, push submissions)
- **`auditors-f{{YYYY}}`** (satellite) — auditors (read-only)
- **`course-admin`** — DSL administrators

## Workflows

Faculty run these from the [Actions tab](https://github.com/{org}/actions):
- **`provision-assignment`** — one private repo per student from a master template
- **`release-materials`** — drip course materials into the cohort
- **`enroll-student`** — grant org + students-team access

Leave the org field blank to target this org.

## Resources

- [Teaching & Course Setup](https://github.com/hertie-data-science-lab/dsl-teaching-course-setup) — workflows + docs
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


def create_profile_repo(
    org: str,
    org_name: str,
    course_name: str,
    course_code: str = "",
) -> None:
    """Create the .github profile repo with README and course metadata.

    Also tags the repo with `dsl-course-hub` so `list_orgs.py` can discover it.
    """
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

    # Course metadata — canonical machine-readable source for discovery tooling
    metadata = (
        f"org: {org}\n"
        f"org_name: {org_name}\n"
        f"course_name: {course_name}\n"
        f"course_code: {course_code or ''}\n"
    )
    put_file(
        org,
        ".github",
        "dsl-course.yml",
        metadata.encode(),
        "init: course metadata for DSL discovery tooling",
    )

    # Topic marker — list_orgs.py searches for this topic to enumerate course orgs
    topics = [COURSE_HUB_TOPIC]
    if course_code:
        topics.append(f"course-{course_code.lower()}")
    set_repo_topics(org, ".github", topics)

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


def _welcome_template(rel: str) -> bytes:
    """Read a seeded-welcome template from the repo's templates/welcome/ dir."""
    return (
        Path(__file__).resolve().parents[1] / "templates" / "welcome" / rel
    ).read_bytes()


def setup_cohort_extras(org: str) -> None:
    """Cohort-only: tighten the org and seed the student-facing repos.

    Layered on top of the common bootstrap when --cohort is passed:
    - safe-by-default permissions (members get no repo access unless granted);
    - public `welcome` repo with the Join issue form + onboard workflow;
    - private `classroom-config` repo with a starter students.csv.
    The `materials` repo is created on the first release, so it's not made here.
    """
    log_step("Cohort setup: tighten org + seed welcome/classroom-config")

    code, out = gh(
        "api",
        "--method",
        "PATCH",
        f"orgs/{org}",
        "--field",
        "default_repository_permission=none",
        "--field",
        "members_can_create_repositories=false",
    )
    if code == 0:
        log_ok(
            "org tightened (default_repository_permission=none, no member repo creation)"
        )
    else:
        log_err(f"could not tighten org settings: {out[:120]}")

    if create_repo(
        org,
        "welcome",
        private=False,
        description="Course front door — open a Join issue to enrol",
    ):
        put_file(
            org,
            "welcome",
            ".github/workflows/onboard.yml",
            _welcome_template("onboard.yml"),
            "ci: seed onboard workflow",
        )
        put_file(
            org,
            "welcome",
            ".github/ISSUE_TEMPLATE/join.yml",
            _welcome_template("ISSUE_TEMPLATE/join.yml"),
            "ci: seed Join issue form",
        )
        log_ok("welcome repo seeded (onboard.yml + Join form)")

    if create_repo(
        org,
        "classroom-config",
        private=True,
        description="PRIVATE cohort config — roster (students.csv). No PII leaves here.",
    ):
        roster = (
            "student_id,hertie_email,name,github_handle,github_id,section\n"
            "000001,student@example.edu,Example Student,,,A\n"
        )
        put_file(
            org,
            "classroom-config",
            "students.csv",
            roster.encode(),
            "init: starter roster (replace the example row with registrar data)",
        )
        log_ok("classroom-config seeded (students.csv starter)")


# Thin wrapper workflows seeded into each course AND cohort org's .github repo.
# They check out the public central repo at run-time and run the module — so the
# logic is single-sourced here, never duplicated, and runs locally in the faculty's
# own org. The "blank = this org" rule means ONE identical wrapper behaves the same
# whether it's seeded in a course (master) org or a cohort org: leave the local org's
# field blank and it resolves to the org the workflow is running in.
_CENTRAL = "hertie-data-science-lab/dsl-teaching-course-setup"

_CHECK_TEAM = """\
  check-team:
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
          echo "::error::$ACTOR is not in the faculty or admin team — access denied"
          exit 1
"""

_RUN_PREAMBLE = (
    """\
    needs: check-team
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          repository: %s
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
"""
    % _CENTRAL
)

_WORKFLOW_PROVISION = (
    """\
name: Provision assignment

on:
  workflow_dispatch:
    inputs:
      cohort_org:
        description: "Cohort org (target). Blank = this org."
        required: false
        default: ""
      master_org:
        description: "Master org (template source). Blank = this org."
        required: false
        default: ""
      assignment:
        description: "Assignment slug (e.g. assignment-1)"
        required: true
      template:
        description: "Template repo name in the master org (e.g. assignment-1-template)"
        required: true
      dry_run:
        description: "Preview only"
        required: false
        default: false
        type: boolean

jobs:
"""
    + _CHECK_TEAM
    + """
  provision:
"""
    + _RUN_PREAMBLE
    + """\
      - name: Provision
        env:
          GH_TOKEN: ${{ secrets.DSL_BOT_TOKEN }}
          OWNER: ${{ github.repository_owner }}
          MASTER_IN: ${{ inputs.master_org }}
          COHORT_IN: ${{ inputs.cohort_org }}
          ASSIGNMENT: ${{ inputs.assignment }}
          TEMPLATE: ${{ inputs.template }}
          DRY_RUN: ${{ inputs.dry_run }}
        run: |
          MASTER="${MASTER_IN:-$OWNER}"; COHORT="${COHORT_IN:-$OWNER}"
          args=(--master-org "$MASTER" --cohort-org "$COHORT" --assignment "$ASSIGNMENT" --template "$TEMPLATE")
          [ "$DRY_RUN" = "true" ] && args+=(--dry-run)
          python3 -m dsl_course.assign "${args[@]}"
"""
)

_WORKFLOW_RELEASE = (
    """\
name: Release materials

on:
  workflow_dispatch:
    inputs:
      cohort_org:
        description: "Cohort org (target). Blank = this org."
        required: false
        default: ""
      master_org:
        description: "Master org (content source). Blank = this org."
        required: false
        default: ""
      content_repo:
        description: "Content repo name in the master org (e.g. content-f2025)"
        required: true
      sessions:
        description: "Sessions to release, space-separated (e.g. 1 2 3)"
        required: true

jobs:
"""
    + _CHECK_TEAM
    + """
  release:
"""
    + _RUN_PREAMBLE
    + """\
      - name: Release
        env:
          GH_TOKEN: ${{ secrets.DSL_BOT_TOKEN }}
          OWNER: ${{ github.repository_owner }}
          MASTER_IN: ${{ inputs.master_org }}
          COHORT_IN: ${{ inputs.cohort_org }}
          CONTENT_REPO: ${{ inputs.content_repo }}
          SESSIONS: ${{ inputs.sessions }}
        run: |
          gh auth setup-git
          MASTER="${MASTER_IN:-$OWNER}"; COHORT="${COHORT_IN:-$OWNER}"
          python3 -m dsl_course.release --master-org "$MASTER" --content-repo "$CONTENT_REPO" --cohort-org "$COHORT" --sessions $SESSIONS
"""
)

_WORKFLOW_ENROLL = (
    """\
name: Enroll student

on:
  workflow_dispatch:
    inputs:
      cohort_org:
        description: "Cohort org. Blank = this org."
        required: false
        default: ""
      handle:
        description: "GitHub handle to enroll (blank = sync whole roster)"
        required: false
        default: ""
      prune:
        description: "When syncing the whole roster, remove members no longer on it"
        required: false
        default: false
        type: boolean

jobs:
"""
    + _CHECK_TEAM
    + """
  enroll:
"""
    + _RUN_PREAMBLE
    + """\
      - name: Enroll
        env:
          GH_TOKEN: ${{ secrets.DSL_BOT_TOKEN }}
          OWNER: ${{ github.repository_owner }}
          COHORT_IN: ${{ inputs.cohort_org }}
          HANDLE: ${{ inputs.handle }}
          PRUNE: ${{ inputs.prune }}
        run: |
          COHORT="${COHORT_IN:-$OWNER}"
          args=(--cohort-org "$COHORT")
          [ -n "$HANDLE" ] && args+=(--handle "$HANDLE")
          [ "$PRUNE" = "true" ] && args+=(--prune)
          python3 -m dsl_course.sync_roster "${args[@]}"
"""
)

_FACULTY_WORKFLOWS = {
    ".github/workflows/provision-assignment.yml": _WORKFLOW_PROVISION,
    ".github/workflows/release-materials.yml": _WORKFLOW_RELEASE,
    ".github/workflows/enroll-student.yml": _WORKFLOW_ENROLL,
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


def preflight(org: str) -> bool:
    """Verify the org exists and is accessible before configuring anything.

    GitHub has NO API to create an organisation (github.com); it must be created
    in the web UI first. If the org is missing, stop with instructions rather than
    404-ing through every step and falsely reporting success.
    """
    log_step(f"Preflight: checking org {org} exists and is accessible")
    code, _ = gh("api", f"orgs/{org}", "--jq", ".login")
    if code != 0:
        log_err(f"org '{org}' not found or not accessible by this token.")
        log(
            "\nGitHub cannot create an organisation via API — create the empty org "
            "first, then re-run:\n"
            "  1. Create it:  https://github.com/organizations/new\n"
            "  2. Add the DSL bot account as an org Owner (so this automation can configure it).\n"
            f"  3. Re-run bootstrap with --org {org}.\n"
        )
        return False
    log_ok(f"org {org} is accessible")
    return True


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
        "--course-code",
        default="",
        help="Hertie course code (e.g. 'GRAD-E1394'). Stored in "
        ".github/dsl-course.yml and set as a repo topic on .github.",
    )
    parser.add_argument(
        "--set-secret",
        default=None,
        help="Path to file containing DSL_BOT_TOKEN PAT. "
        "If provided, sets the org secret. Otherwise, validates presence only.",
    )
    parser.add_argument(
        "--cohort",
        action="store_true",
        help="Also do cohort student-facing setup: tighten the org and seed the "
        "welcome (onboard) + classroom-config (roster) repos.",
    )
    args = parser.parse_args()

    org_name = args.org_name or args.org
    course_name = args.course_name or org_name

    log(f"Bootstrapping org: {args.org}")
    log(f"  Org name: {org_name}")
    log(f"  Course name: {course_name}")

    # 0. Preflight — the org must already exist (GitHub can't create one via API).
    if not preflight(args.org):
        return 1

    # 1. Org settings
    set_org_settings(args.org)

    # 2. Default teams
    create_default_teams(args.org)

    # 3. Profile repo + seed workflows
    create_profile_repo(args.org, org_name, course_name, args.course_code)
    seed_workflows(args.org)

    # 3b. Cohort-only: tighten + seed welcome/classroom-config.
    if args.cohort:
        setup_cohort_extras(args.org)

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
- Faculty workflows seeded: provision-assignment, release-materials, enroll-student
- DSL_BOT_TOKEN secret validated (or set)

NEXT STEPS (manual):
============================================================

1. Review org settings: https://github.com/{args.org}/settings

2. Invite course instructors and admins:
   https://github.com/{args.org}/settings/members

3. Faculty can now run, from https://github.com/{args.org}/.github/actions :
   - Provision assignment · Release materials · Enroll student
   (leave the org field blank to target this org; fill the other org)

NB: cohort orgs are created the same way — make the empty org in the web UI, add the
bot as owner, then run this bootstrap with --cohort so it also seeds welcome + roster.
============================================================
""")

    if args.cohort:
        log(
            "COHORT extras done:\n"
            f"- org tightened (default_repository_permission=none)\n"
            f"- welcome repo (public): Join issue form + onboard workflow\n"
            f"- classroom-config repo (private): starter students.csv "
            f"(edit https://github.com/{args.org}/classroom-config/blob/HEAD/students.csv with registrar data)\n"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
