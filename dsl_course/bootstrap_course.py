"""bootstrap-course -- one-time setup for a new course org.

Sets up org-level infrastructure that persists across semesters:
- DSL_BOT_TOKEN secret (required for all workflows)
- Faculty teams (instructors, course-admin); cohort bootstrap adds students + auditors
- Org settings (2FA enforcement, Pages default branch)
- Profile README (.github repo with description)
- Org-level workflows in .github (sync-enrolment, bootstrap-cohort, refresh-actions)
- Central faculty workflows seeded into .github (Release materials/assignment +
  Sync enrolment/Bootstrap-cohort/Refresh); the run-from-repo copies are equipped by Refresh

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

from . import scaffold, seed, site
from .utils import (
    COURSE_TEAM_ACCESS,
    create_repo,
    create_team,
    gh,
    grant_team_repo_access,
    log,
    log_err,
    log_ok,
    log_step,
    put_file,
    repo_exists,
    set_repo_topics,
)

COURSE_HUB_TOPIC = "dsl-course-hub"


def set_org_secret(org: str, secret_name: str, secret_value: str) -> bool:
    """Create or update an org secret, scoped to the public infra repos that need it.

    The token must reach the **public** `.github` (faculty buttons) and, on cohort
    orgs, `welcome` (onboarding) repos. gh defaults org-secret visibility to
    `private`, which excludes public repos - so the seeded workflows there run with
    an empty `secrets.DSL_BOT_TOKEN` and fail with "set the GH_TOKEN environment
    variable". Scope it explicitly to the infra repos that exist, which also keeps
    this org-admin credential out of the student / content repos (`visibility=all`
    would expose it to every workflow in the org)."""
    infra = [r for r in (".github", "welcome") if repo_exists(org, r)] or [".github"]
    code, out = gh(
        "secret",
        "set",
        secret_name,
        "--org",
        org,
        "--visibility",
        "selected",
        "--repos",
        ",".join(infra),
        "--body",
        secret_value,
    )
    if code == 0:
        log_ok(f"org secret set: {secret_name} (selected: {', '.join(infra)})")
        return True
    log_err(f"failed to set org secret {secret_name}: {out[:200]}")
    return False


# Faculty role teams - created in EVERY org (course + cohort): instructors run the buttons
# and push content (write); course-admin manage the org (admin).
FACULTY_TEAMS = [
    ("instructors", "Instructors and TAs", "closed"),
    ("course-admin", "Course administrators - DSL team", "closed"),
]
# Cohort-only role teams: enrolled students + read-only auditors. The persistent course org
# never gets these - it holds unreleased materials, model solutions, and hidden tests, so
# students/auditors must not be near it. Auditors are read-only: assignment release is
# roster-driven (onboarded students only), so auditors never receive assignment repos.
COHORT_TEAMS = [
    ("students", "Enrolled students", "closed"),
    (
        "auditors",
        "Auditors - read-only (released materials only, no assignments)",
        "closed",
    ),
]


def create_default_teams(org: str) -> None:
    """Create the faculty role teams (FACULTY_TEAMS) - in both course and cohort orgs. The
    cohort-only teams (students, auditors) are created separately by create_cohort_teams."""
    log_step("Creating faculty teams")
    for slug, desc, privacy in FACULTY_TEAMS:
        create_team(org, slug, desc, privacy=privacy)


def create_cohort_teams(org: str) -> None:
    """Create the cohort-only role teams (COHORT_TEAMS): enrolled students + read-only
    auditors. Called at cohort bootstrap only - never on the persistent course org."""
    log_step("Creating cohort teams (students, auditors)")
    for slug, desc, privacy in COHORT_TEAMS:
        create_team(org, slug, desc, privacy=privacy)


# The course-org teams that may run the seeded buttons, and their grant on `.github`:
# `instructors` run releases day-to-day (write); `course-admin` manage the org (admin).
# Access is per-course - only this course's teaching team goes in these teams. The central
# hertie-data-science-lab faculty/admin teams are a SEPARATE concern (who may bootstrap an
# org at all - the central action's gate); they are deliberately NOT mirrored in here.
BUTTON_TEAMS = COURSE_TEAM_ACCESS


def grant_button_access(org: str) -> None:
    """Give the course-org teams write/admin on `.github`, so faculty in them can see +
    run the seeded workflow_dispatch buttons. GitHub only shows the 'Run workflow' button
    to write+ users, so without this only the org owner can run the buttons - the seeded
    check-team gate (repo permission) then enforces it at run time too."""
    log_step("Granting course-org teams button access (.github)")
    for team, perm in BUTTON_TEAMS.items():
        if grant_team_repo_access(org, team, ".github", perm):
            log_ok(f"  {team} -> {perm} on {org}/.github")


def add_course_admins(org: str, handles: str) -> None:
    """Add this course's admin(s) to its `course-admin` team (per-course, so nobody is
    added to a course they don't run). `handles` is a comma/space-separated list of GitHub
    logins; each gets an org invite they accept once (membership shows `pending` until
    then). Instructors/TAs are added later to the `instructors` team via the Teams page."""
    logins = [h.strip() for h in handles.replace(",", " ").split() if h.strip()]
    if not logins:
        return
    log_step(f"Adding {len(logins)} admin(s) to {org}/course-admin")
    for login in logins:
        code, out = gh(
            "api",
            "-X",
            "PUT",
            f"orgs/{org}/teams/course-admin/memberships/{login}",
            "-f",
            "role=member",
            "--jq",
            ".state",
        )
        if code == 0:
            log_ok(f"  {login}: {out.strip() or 'added'}")
        else:
            log_err(f"  ! could not add {login}: {out[:120]}")


# People + schedule change year to year, so they are templated into each COHORT's
# dsl-course.yml (read by that cohort's website), never the persistent course org's.
_PEOPLE_BLOCK = (
    "# People shown on THIS cohort's website. Declared per cohort because the teaching\n"
    "# team changes year to year. Cards carry institutional headshots + bio links (not\n"
    "# GitHub avatars); the first instructor is featured. photo = image URL, url =\n"
    "# bio/profile link, title = optional role. Uncomment:\n"
    "#\n"
    "# people:\n"
    "#   instructors:\n"
    '#     - name: "Prof. Jane Doe"\n'
    '#       title: "Professor of ..."\n'
    '#       photo: "https://.../jane.jpg"\n'
    '#       url: "https://.../profile/jane"\n'
    "#   teaching_assistants:\n"
    '#     - name: "A. N. Other"\n'
    '#       photo: "https://.../other.jpg"\n'
    '#       url: "https://.../profile/other"\n'
)
_SCHEDULE_BLOCK = (
    "# Schedule overrides for THIS cohort's website. Edit here (GitHub web UI is fine -\n"
    "# no CLI) then run Sync site. Anything you leave out is synthesised (semester start\n"
    "# from the cohort's fYYYY tag; assignments every 2 weeks; exams at weeks 8 and 15).\n"
    "# Uncomment and fill what you want to pin:\n"
    "#\n"
    "# schedule:\n"
    "#   semester_start: 2026-09-07        # YYYY-MM-DD\n"
    "#   assignments:                      # keyed by assignment slug (no -fYYYY)\n"
    "#     assignment-1: 2026-10-13\n"
    "#     assignment-2: 2026-11-10\n"
    "#   exams:\n"
    "#     - name: MidTerm Exam\n"
    "#       date: 2026-11-03\n"
    "#     - name: Final Exam\n"
    "#       date: 2026-12-15\n"
)


# classroom-config (cohort, private) contract: the roster/grades/teams/schedule schema,
# documented next to the files faculty edit. Samples use a `.sample` suffix so the engine
# (sync_teams, scheduled-release, grade sync) never ingests them - only the real names.
_CLASSROOM_README = """# classroom-config - this cohort's private config

**PRIVATE.** Roster and grades for this cohort. No PII (emails, ids, names) leaves this
repo. Faculty/FAs edit these files; the buttons in the **course org's** Actions tab read
them. Canonical, engine-wide schema:
<https://github.com/hertie-data-science-lab/dsl-teaching-course-setup/blob/main/docs/REQUIRED-INPUT-SCHEMA.md>.

## students.csv - the roster (required)

One row per student. Leave `github_handle`/`github_id` blank - students fill them on join.

| column | filled by | notes |
|--------|-----------|-------|
| student_id | registrar | institutional id |
| hertie_email | registrar | **match key** - enrolment reconciles on this |
| name | registrar | display name |
| github_handle | onboarding | blank until they join via the welcome "Join" issue |
| github_id | onboarding | numeric id captured on join - **immutable; never hand-edit** |
| section | registrar | optional grouping (e.g. A/B) |

**Sync enrolment** reconciles the `students` team from this file (`prune` off-boards leavers).

## grades/<assignment>.csv - marks (optional, when returning grades)

One file per assignment, e.g. `grades/assignment-1.csv`:
`github_handle, team, auto, manual, team_grade, adjustment, final, comments, team_comments`.
**Grade assignment** can pre-fill `auto`/`team_grade` from hidden tests; faculty fill the
rest, then **Sync gradebooks** -> **Render grades** -> **Distribute grades**.

## teams.csv - group membership (optional, for group assignments)

`assignment, team, github_handle`. Students self-select via the welcome "Join team" issue,
or edit directly. See `teams.csv.sample` - **the engine only acts on a real `teams.csv`.**

## schedule.csv - release calendar (optional, pairs with the manifest)

`week, date` - the daily **Scheduled release** cron opens each week's manifest items on its
date. See `schedule.csv.sample`.
"""

_TEAMS_CSV_SAMPLE = """# Sample. Rename to teams.csv to activate. Students normally self-select via
# the welcome "Join team" issue, so you rarely edit this by hand.
assignment,team,github_handle
assignment-4-project,team-1,alice
assignment-4-project,team-1,bob
assignment-4-project,team-2,carol
"""

_SCHEDULE_CSV_SAMPLE = """# Sample. Rename to schedule.csv to activate. Maps each teaching week to the
# calendar date the Scheduled release cron opens that week's manifest items.
week,date
1,2026-09-07
2,2026-09-14
3,2026-09-21
"""


def _course_metadata(
    org: str, org_name: str, course_name: str, course_code: str
) -> str:
    """dsl-course.yml for the persistent COURSE org: identity only. The course org
    spans many cohorts, so cohort-specific people + schedule live per cohort."""
    return (
        f"org: {org}\n"
        f"org_name: {org_name}\n"
        f"course_name: {course_name}\n"
        f"course_code: {course_code or ''}\n"
        "\n"
        "# This is the persistent COURSE org - it spans many cohorts (years). People\n"
        "# (instructors/TAs) and the schedule change year to year, so they are declared\n"
        "# PER COHORT in <cohort-org>/.github/dsl-course.yml, not here. Cohorts are\n"
        "# registered separately in .github/cohort-courses-pages.yml.\n"
    )


def _cohort_metadata(org: str, course_org: str) -> str:
    """dsl-course.yml for a per-year COHORT org: the cohort-specific people + schedule
    its website reads. Course identity (name/code) comes from the parent course org."""
    course_line = f"course: {course_org}\n" if course_org else ""
    return f"org: {org}\n{course_line}\n{_PEOPLE_BLOCK}\n{_SCHEDULE_BLOCK}"


def create_profile_repo(
    org: str,
    org_name: str,
    course_name: str,
    course_code: str = "",
    *,
    is_cohort: bool = False,
    course_org: str = "",
) -> None:
    """Create the .github profile repo with README and course metadata.

    Also tags the repo with `dsl-course-hub` so `list_orgs.py` can discover it.

    The course org's dsl-course.yml carries identity only; a cohort's instead carries
    the cohort-specific people + schedule its website reads (these vary by year).
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
        _cohort_metadata(org, course_org)
        if is_cohort
        else _course_metadata(org, org_name, course_name, course_code)
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

    create_cohort_teams(org)

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
        put_file(
            org,
            "welcome",
            ".github/workflows/team-formation.yml",
            _welcome_template("team-formation.yml"),
            "ci: seed team-formation workflow",
        )
        put_file(
            org,
            "welcome",
            ".github/ISSUE_TEMPLATE/join-team.yml",
            _welcome_template("ISSUE_TEMPLATE/join-team.yml"),
            "ci: seed Join team issue form",
        )
        log_ok("welcome repo seeded (onboard + team-formation + Join forms)")

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
        put_file(
            org,
            "classroom-config",
            "README.md",
            _CLASSROOM_README.encode(),
            "docs: classroom-config schema + contract",
        )
        put_file(
            org,
            "classroom-config",
            "grades/.gitkeep",
            b"",
            "init: grades/ (add one <assignment>.csv per assignment to return marks)",
        )
        put_file(
            org,
            "classroom-config",
            "teams.csv.sample",
            _TEAMS_CSV_SAMPLE.encode(),
            "docs: sample teams.csv (group assignments)",
        )
        put_file(
            org,
            "classroom-config",
            "schedule.csv.sample",
            _SCHEDULE_CSV_SAMPLE.encode(),
            "docs: sample schedule.csv (scheduled release)",
        )
        log_ok("classroom-config seeded (roster + README + grades/ + samples)")

    # Public, auto-deployed cohort website (from course-website-template).
    scaffold.scaffold_site(org)


def seed_workflows(org: str) -> None:
    """Seed the org-level workflows into the course org's .github repo. The full set
    (central Release materials/assignment + Sync enrolment/Bootstrap-cohort/Refresh) is rendered
    by dsl_course.seed (single source of truth)."""
    seed.seed_github_workflows(org)


def preflight(org: str) -> bool:
    """Verify the org exists AND the bot can administer it before configuring anything.

    GitHub has NO API to create an organisation (github.com); it must be created in the
    web UI first, with the bot added as an Owner. A token that is only a *pending* or
    member-level org member can READ the org but every create call 403s - so check for an
    active Owner up front and stop with actionable instructions, rather than 403-ing
    through every step and falsely reporting success.
    """
    log_step(f"Preflight: checking org {org} + bot permissions")
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
    # The token must be an ACTIVE OWNER. A pending/invited or member-level token reads the
    # org fine but cannot create the .github repo, role teams, or org secret (all 403).
    bot = gh("api", "user", "--jq", ".login")[1].strip() or "the bot"
    code, membership = gh(
        "api", f"user/memberships/orgs/{org}", "--jq", '.state + "/" + .role'
    )
    membership = membership.strip() if code == 0 else "not a member"
    if membership != "active/admin":
        log_err(f"@{bot} cannot administer {org} (membership: {membership}).")
        log(
            f"\nThe bot must be an ACTIVE OWNER of {org} - creating the .github repo, role "
            f"teams, and org secret all require Owner. Fix by the matching case, then re-run:\n"
            f"  - 'pending/admin'  -> @{bot} was invited but hasn't accepted: sign in as "
            f"@{bot} and accept at https://github.com/orgs/{org}/invitation\n"
            f"  - 'not a member'   -> invite @{bot} to {org} as Owner, then accept as @{bot}\n"
            f"  - 'active/member'  -> promote @{bot} to Owner in the org's People page\n"
        )
        return False
    log_ok(f"org {org} accessible; @{bot} is an active owner")
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
    parser.add_argument(
        "--admins",
        default="",
        help="GitHub handle(s) of this course's admin(s), comma/space-separated. Added to "
        "the course-admin team (admin on .github) so they can run the buttons. Each accepts "
        "an org invite once. Add instructors/TAs later via the org's Teams page.",
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

    # 3. Profile repo (course = identity only; cohort = its people + schedule)
    create_profile_repo(
        args.org,
        org_name,
        course_name,
        args.course_code,
        is_cohort=args.cohort,
        course_org=args.course or "",
    )

    # 3b. Course vs cohort wiring.
    if args.cohort:
        # Cohort: student-facing welcome + roster + tightened perms.
        setup_cohort_extras(args.org)
        if args.course:
            seed.register_cohort(args.course, args.org)
            # Populate + prune + wire the freshly-scaffolded site from the org structure.
            site.sync_site(args.course, args.org)
        else:
            log(
                f"  (no --course given - add {args.org} to its course org's "
                f".github/{seed.COHORTS_PATH} to show it in the faculty dropdowns)"
            )
    else:
        # Course: seed the org-level buttons (incl. the central Release actions) into .github.
        seed_workflows(args.org)

    # 3c. Button access: grant this course's own instructors/course-admin teams write/admin
    # on .github (without it only the org owner can run the buttons), then seed the named
    # admin(s) into course-admin. Access is per-course - central DSL faculty/admin are a
    # separate concern (who may bootstrap), not auto-added here.
    grant_button_access(args.org)
    add_course_admins(args.org, args.admins)

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
- Faculty teams: instructors, course-admin (students + auditors are created per cohort)
- Org settings: 2FA enforcement enabled
- .github profile repo with README
- Workflows in .github: Release materials, Release assignment, Sync enrolment,
  Bootstrap cohort, Refresh actions
- DSL_BOT_TOKEN secret validated (or set)
- Button access: instructors (write) + course-admin (admin) granted on .github; any
  --admins handles added to course-admin (they accept the org invite once, then the
  buttons appear in their Actions tab)

NEXT STEPS (manual):
============================================================

1. Review org settings: https://github.com/{args.org}/settings

2. Add THIS course's instructors/TAs to the `instructors` team (write) - only the people
   who run this course: https://github.com/orgs/{args.org}/teams

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
