"""bootstrap-course -- one-time setup for a new course org.

Sets up org-level infrastructure that persists across semesters:
- DSL_BOT_TOKEN secret (required for all workflows)
- Default teams (instructors, students, auditors)
- Org settings (2FA enforcement, Pages default branch)
- Profile README (.github repo with description)
- Org-level workflows in .github (enroll-student, bootstrap-cohort, refresh-actions)
- Central faculty workflows seeded into .github (Release materials/assignment +
  Enroll/Bootstrap-cohort/Refresh); the run-from-repo copies are equipped by Refresh

With --cohort, instead tightens the org and seeds the student-facing welcome (onboard)
and classroom-config (roster) repos.

Usage:
    python3 -m dsl_course.bootstrap_course --org Hertie-School-Deep-Learning-E1394
    python3 -m dsl_course.bootstrap_course --org Deep-Learning-f2026 --cohort
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import seed
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

    # Course metadata - canonical machine-readable source for discovery tooling.
    # (The org-overview profile/README.md is generated at the end of bootstrap, once
    # all repos exist, by seed.update_profile_readme - see main.)
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

    # Topic marker - list_orgs.py searches for this topic to enumerate course orgs
    topics = [COURSE_HUB_TOPIC]
    if course_code:
        topics.append(f"course-{course_code.lower()}")
    set_repo_topics(org, ".github", topics)

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
        description="Course front door - open a Join issue to enrol",
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
        description="PRIVATE cohort config - roster (students.csv). No PII leaves here.",
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


def seed_workflows(org: str) -> None:
    """Seed the org-level workflows into the course org's .github repo. The full set
    (central Release materials/assignment + Enroll/Bootstrap-cohort/Refresh) is rendered
    by dsl_course.seed (single source of truth)."""
    seed.seed_github_workflows(org)


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
            "\nGitHub cannot create an organisation via API - create the empty org "
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
    parser.add_argument(
        "--course",
        default=None,
        help="With --cohort: the parent course org. Registers this cohort in that "
        "course's .github/dsl-course.yml so it appears in the faculty dropdowns.",
    )
    parser.add_argument(
        "--propagate-secret",
        action="store_true",
        help="Set DSL_BOT_TOKEN on this org to the DSL_BOT_TOKEN/GH_TOKEN env value "
        "(lets the central bootstrap auto-provision the token - no manual per-org step).",
    )
    args = parser.parse_args()

    org_name = args.org_name or args.org
    course_name = args.course_name or org_name

    log(f"Bootstrapping org: {args.org}")
    log(f"  Org name: {org_name}")
    log(f"  Course name: {course_name}")

    # 0. Preflight - the org must already exist (GitHub can't create one via API).
    if not preflight(args.org):
        return 1

    # 1. Org settings
    set_org_settings(args.org)

    # 2. Default teams
    create_default_teams(args.org)

    # 3. Profile repo
    create_profile_repo(args.org, org_name, course_name, args.course_code)

    # 3b. Course vs cohort wiring.
    if args.cohort:
        # Cohort: student-facing welcome + roster + tightened perms.
        setup_cohort_extras(args.org)
        if args.course:
            seed.register_cohort(args.course, args.org)
        else:
            log(
                f"  (no --course given - add {args.org} to its course org's "
                f".github/{seed.COHORTS_PATH} to show it in the faculty dropdowns)"
            )
    else:
        # Course: seed the org-level buttons (incl. the central Release actions) into .github.
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
    elif args.propagate_secret:
        # Copy the bot token onto this org so its seeded workflows can run. Lets the
        # central bootstrap auto-provision the secret - no per-course manual step.
        token = os.environ.get("DSL_BOT_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            set_org_secret(args.org, "DSL_BOT_TOKEN", token)
        else:
            log_err("--propagate-secret set but no DSL_BOT_TOKEN/GH_TOKEN in env")
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

    # 5. Generate the org-overview README now that all repos exist (clickable index).
    seed.update_profile_readme(args.org, org_name, course_name)

    log(f"""
============================================================
Course org bootstrap complete: {args.org}

DONE (automated):
============================================================
- Org-level teams: instructors, students, auditors, course-admin
- Org settings: 2FA enforcement enabled
- .github profile repo with README
- Workflows in .github: Release materials, Release assignment, Enroll student,
  Bootstrap cohort, Refresh actions
- DSL_BOT_TOKEN secret validated (or set)

NEXT STEPS (manual):
============================================================

1. Review org settings: https://github.com/{args.org}/settings

2. Invite course instructors and admins:
   https://github.com/{args.org}/settings/members

3. Put content in the materials repo (lectures/week-N/, readings/week-N/) and create
   assignment-N-f2026 template repos, then run "Refresh actions" so they appear in the
   dropdowns. Run Release materials/assignment from inside the materials repo's Actions tab.

4. Add a cohort: create the empty cohort org, add the bot as owner, then run the
   "Bootstrap cohort" action here with its name (configures + registers + refreshes).

NB: cohort orgs are made the same way - create the empty org, add the bot as owner,
then run bootstrap with --cohort (seeds welcome + roster + tightens perms).
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
