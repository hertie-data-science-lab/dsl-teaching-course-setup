"""bootstrap-course -- one-time setup for a new course org.

Sets up org-level infrastructure that persists across semesters:
- DSL_BOT_TOKEN secret (required for all workflows)
- Faculty teams (instructors, course-admin); cohort bootstrap adds students + auditors
- Org settings (2FA enforcement, Pages default branch)
- Profile README (.github repo with description)
- Org-level workflows in .github (sync-membership, bootstrap-cohort, refresh-actions)
- Central faculty workflows seeded into .github (Release materials/assignment +
  Sync membership/Bootstrap-cohort/Refresh); the run-from-repo copies are equipped by Refresh

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

from . import scaffold, seed, site, sync_faculty
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
    repo_is_private,
    set_repo_topics,
)

COURSE_HUB_TOPIC = "dsl-course-hub"


def set_org_secret(org: str, secret_name: str, secret_value: str) -> bool:
    """Create or update an org secret, scoped to the infra repos that need it.

    The token must reach the **public** `.github` (faculty buttons), `welcome`
    (onboarding), and `classroom-config` (its dispatch-sync workflow cross-repo
    triggers Sync membership in `.github`). gh defaults org-secret visibility to
    `private`, which excludes public repos - so the seeded workflows there run with
    an empty `secrets.DSL_BOT_TOKEN` and fail with "set the GH_TOKEN environment
    variable". Scope it explicitly to the infra repos that exist, which also keeps
    this org-admin credential out of student-facing/content repos (`visibility=all`
    would expose it to every workflow in the org) - classroom-config is already
    private/faculty-only, the same trust tier as `.github`."""
    infra = [
        r for r in (".github", "welcome", "classroom-config") if repo_exists(org, r)
    ] or [".github"]
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
    if code != 0:
        log_err(f"failed to set org secret {secret_name}: {out[:200]}")
        return False
    log_ok(f"org secret set: {secret_name} (selected: {', '.join(infra)})")

    # Free-plan delivery gap: an org secret with `selected` visibility is never
    # delivered to a PRIVATE repo (only public ones receive it). classroom-config is
    # private, so its dispatch workflows would read an empty `secrets.DSL_BOT_TOKEN`.
    # Mirror the value as a repo-level secret on each private infra repo so it lands.
    for r in infra:
        if not repo_is_private(org, r):
            continue
        rc, rout = gh(
            "secret", "set", secret_name, "--repo", f"{org}/{r}", "--body", secret_value
        )
        if rc == 0:
            log_ok(f"repo secret set (private infra): {org}/{r}")
        else:
            log_err(f"failed to set repo secret on {org}/{r}: {rout[:200]}")
    return True


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


def _parse_handles(handles: str) -> list[str]:
    return [h.strip() for h in handles.replace(",", " ").split() if h.strip()]


def add_course_admins(org: str, handles: str) -> None:
    """Add this course's admin(s) to its `course-admin` team (per-course, so nobody is
    added to a course they don't run). `handles` is a comma/space-separated list of GitHub
    logins; each gets an org invite they accept once (membership shows `pending` until
    then). Instructors/TAs are added later to the `instructors` team via the Teams page.

    This is a direct, immediate team invite ONLY - it does not persist anywhere. On the
    course org, `_course_metadata` also seeds these same handles into
    `dsl-course.yml`'s `people.course_admins` (the SSOT `sync_faculty` reconciles
    against), so the next sync doesn't undo this invite by pruning them right back out
    for not being declared. On a cohort org there's no SSOT to write to (course_admins
    stays exclusively course-level) - this invite is real but only until the next sync
    mirrors the course org's actual roster over it."""
    logins = _parse_handles(handles)
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


# course_admins are declared ONCE on the persistent COURSE org (this block) - the
# single source of truth for admin access, reconciled into this org's own
# `course-admin` GitHub team AND mirrored into every cohort org's own `course-admin`
# team. `github_handle` is the only required field (it's what actually grants
# access); `start`/`end` are optional ISO dates - omit either for open-ended, or set
# both to bound access to one window (auto-rotates, no manual removal needed).
#
# Instructors/TAs are NOT declared here - most cohorts have different lecturers/TAs,
# so they're declared per cohort instead, in that cohort's own
# classroom-config/people.yml (seeded alongside schedule.yml at Bootstrap cohort).
# Shared preamble + website-card scaffold for the course org's people: block, used by
# both the fully-commented default (_FACULTY_BLOCK) and the --admins-seeded variant
# (_course_admins_block). Kept in one place so the two variants can't drift.
_PEOPLE_HEADER = (
    "# ---------------------------------------------------------------------------\n"
    "# People. Two DIFFERENT things live under the `people:` key below - don't\n"
    "# confuse them:\n"
    "#\n"
    "#   course_admins        GRANTS ACCESS. The single source of truth for course-wide\n"
    "#                        admin rights - the `course-admin` team here, mirrored into\n"
    "#                        every cohort org. \"Sync membership\" reconciles that team\n"
    "#                        FROM this list: a handle added any other way (Teams UI, a\n"
    "#                        gh call) is reverted on the next sync unless it's declared\n"
    "#                        here, and removing a handle here revokes their access.\n"
    "#\n"
    "#   instructors /        DISPLAY ONLY - website cards (name/photo/title/link) for\n"
    "#   teaching_assistants  the course + cohort sites. They grant NO GitHub access.\n"
    "#                        Access for a cohort's teaching team is declared separately,\n"
    "#                        in that cohort's classroom-config/people.yml.\n"
    "# ---------------------------------------------------------------------------\n"
)

# The instructors/teaching_assistants website-card scaffold (display only). Shipped
# commented in both variants so faculty can see the cards exist and how to fill them -
# this is the schema site._people_from_meta reads for the course + cohort site headshots.
_CARD_SCAFFOLD = (
    "\n"
    "  # Website cards (optional, DISPLAY ONLY - no GitHub access). Uncomment and fill\n"
    "  # to show the teaching team on the course + cohort websites:\n"
    "  # instructors:\n"
    '  #   - github_handle: "janedoe"\n'
    '  #     name:  "Prof. Dr. Jane Doe"\n'
    '  #     title: "Professor of Data Science"\n'
    '  #     photo: "https://.../headshot.jpg"        # square image URL\n'
    '  #     url:   "https://.../profile/jane-doe"     # bio / profile link\n'
    "  # teaching_assistants:\n"
    '  #   - github_handle: "alexsmith"\n'
    '  #     name:  "Alex Smith"\n'
    '  #     title: "Teaching Assistant"\n'
    '  #     photo: "https://avatars.githubusercontent.com/u/000000?v=4"\n'
    '  #     url:   "https://github.com/alexsmith"\n'
)

_FACULTY_BLOCK = (
    _PEOPLE_HEADER
    + "\n"
    "# Uncomment and fill in at least one course admin (if you passed --admins at\n"
    "# bootstrap, this is already filled in for you):\n"
    "# people:\n"
    "#   course_admins:\n"
    '#     - github_handle: "adminhandle"    # required - grants the `course-admin` team\n'
    '#       start: "2026-09-01"             # optional - no start = active immediately\n'
    '#       end: "2027-06-30"               # optional - no end = indefinite\n'
    + _CARD_SCAFFOLD
)


# classroom-config (cohort, private) contract: the roster/grades/teams/schedule schema,
# documented next to the files faculty edit. Samples use a `.sample` suffix so the engine
# (sync_teams, scheduled-release, grade sync) never ingests them - only the real names.
_CLASSROOM_README = """# classroom-config - this cohort's private config

**PRIVATE.** This is the entire per-cohort data hub - roster, teams, grades,
schedule, and this cohort's own instructors/TAs. No PII (emails, ids, names) leaves
this repo. Course admins are managed at the **course org** level instead - see that
org's `.github/dsl-course.yml`; that access is kept current automatically. Faculty/FAs
edit these files; the buttons in the **course org's** Actions tab read them.
Canonical, engine-wide schema:
<https://github.com/hertie-data-science-lab/dsl-teaching-course-setup/blob/main/docs/faculty-and-instructors/required-input-schema.md>.

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

A push to this file triggers **Sync membership** automatically, reconciling the
`students` team to match (a deleted row revokes access on that same push - there is no
separate off-boarding step).

## grades/<assignment>.csv - marks (optional, when returning grades)

One file per assignment, e.g. `grades/assignment-1.csv`:
`github_handle, team, auto, manual, team_grade, adjustment, final, comments, team_comments`.
**Grade assignment** can pre-fill `auto`/`team_grade` from hidden tests; faculty fill the
rest, then **Sync gradebooks** -> **Render grades** -> **Distribute grades**. The autograder
pins to each assignment's **due date** from `schedule.yml` (`assignments.<slug>.due`,
plus optional `grace_days`) - there is no separate deadline input. A generated,
read-only `cohort-gradebook.csv` (one row per student, one column-group per
assignment) appears alongside the per-student gradebooks on every **Render grades** -
never hand-edit it, it's a glance view, not a source.

## teams.csv - group membership (optional, for group assignments)

`assignment, team, github_handle`. Students self-select via the welcome "Join team" issue,
or edit directly - a push here also triggers **Sync membership**. See `teams.csv.sample` -
**the engine only acts on a real `teams.csv`.**

## schedule.yml - the release plan + due dates + exams (optional)

This cohort's whole schedule in one file. `materials_releases:` is the **auto-release
plan** - labelled entries (`session_2`, `lab_1`, `bonus-dataset`, ...), each with a
`when:` datetime and one or more actions (`deploy` a source path -> a cohort repo,
`assignment` provision student repos, `grade` run the autograder). The hourly **Scheduled
release** cron fires each entry once its `when` has arrived (honoured to the hour). Also
holds `semester_start`/`semester_end`, `assignments` (due dates for the website + grading
pin, with an optional `grace_days`), and `exams`. Seeded mostly-commented - uncomment and
fill what you want; anything left out is synthesised or simply not scheduled.

## people.yml - this cohort's instructors/TAs (optional)

Most cohorts have different lecturers/TAs, so - unlike course admins (course-org level,
see above) - instructors/TAs are declared here, per cohort. **Sync membership**
reconciles them into this cohort's own `instructors` team AND a course-org
`instructors-<tag>` team (push access scoped to just this year's content repos, plus
the central `.github` repo so they can use the central dispatch buttons too), so they
can push materials without a course-level declaration. Seeded mostly-commented -
uncomment and fill what you want to pin.
"""

_TEAMS_CSV_SAMPLE = """# Sample. Rename to teams.csv to activate. Students normally self-select via
# the welcome "Join team" issue, so you rarely edit this by hand.
assignment,team,github_handle
assignment-4-project,team-1,alice
assignment-4-project,team-1,bob
assignment-4-project,team-2,carol
"""

# This cohort's entire schedule - the auto-release plan (materials_releases) + due
# dates/exams - lives in one file (classroom-config/schedule.yml, see dsl_course.schedule).
# Seeded live (not a .sample) and mostly commented, so faculty uncomment what they want to
# pin rather than rename a sample to activate it. The commented block is a MAXIMAL scaffold:
# it shows every action (deploy/assignment/grade) and every field, so faculty can copy the
# shape they need.
_SCHEDULE_YML = """# This cohort's schedule + auto-release plan. Edit here (GitHub web UI is fine - no CLI).
# Everything is optional: anything you leave out is synthesised (semester start from the
# fYYYY tag; website exams at weeks 8 & 15) or simply not scheduled. Uncomment and fill
# what you want. Times are Europe/Berlin unless you set `timezone:` or give an explicit
# offset; the Scheduled release cron runs hourly, so a `when:` time is honoured to the hour.

# timezone: Europe/Berlin              # optional - how the naive datetimes below are read

# ---------------------------------------------------------------------------
# materials_releases: the AUTO-RELEASE plan. Each entry is a label (any name you like -
# session_2, lab_1, bonus-dataset) mapping to a `when:` datetime and one or more actions.
# The hourly Scheduled release cron fires each entry once its `when` has arrived
# (idempotent - safe to re-run). Sources are always read from the COURSE org;
# destinations always written to THIS cohort org.
# ---------------------------------------------------------------------------
# materials_releases:
#
#   session_2:                          # a normal weekly release (label is just a name)
#     when: 2026-09-15T14:00            # bare date (2026-09-15) -> 00:00 that day
#     deploy:                           # copy one or more paths: course repo -> cohort repo
#       - source_repo: course-materials-f2026    # repo in the COURSE org
#         source_path: lectures/02_intro          # folder or file to copy
#         dest_repo: materials                     # repo in THIS cohort org (default: materials)
#         dest_path: lectures/02_intro             # where to put it (default: same as source_path)
#       - source_repo: course-materials-f2026
#         source_path: readings/02_intro
#         dest_repo: materials
#         dest_path: readings/02_intro
#
#   lab_1:                              # a lab is just another release - no special section
#     when: 2026-09-17T10:00
#     deploy:
#       - source_repo: course-materials-f2026
#         source_path: labs/01_setup
#         dest_repo: materials
#         # dest_path omitted -> mirrors source_path (labs/01_setup)
#
#   bonus-dataset:                      # a one-off that isn't a numbered teaching session
#     when: 2026-10-20T09:30
#     deploy:
#       - source_repo: course-datasets-f2026
#         source_path: week7/housing.csv
#         dest_repo: materials
#         dest_path: datasets/housing.csv
#
#   assignment-1-handout:               # hand an assignment out (provision one repo/student)
#     when: 2026-09-22T09:00
#     assignment: assignment-1-f2026    # the assignment-*-<tag> template repo
#
#   assignment-1-grade:                 # run the autograder after the deadline
#     when: 2026-10-15T00:00
#     grade:
#       template: assignment-1-f2026
#       deadline: 2026-10-13T23:59      # commit cutoff (default: this assignment's due date)
#       group: false                    # true for a group assignment

# ---------------------------------------------------------------------------
# The rest is for DISPLAY (website) and GRADING - not the release plan above.
# ---------------------------------------------------------------------------
# semester_start: 2026-09-07           # YYYY-MM-DD
# semester_end: 2026-12-18
#
# assignments:                          # due dates (keyed by slug, no -fYYYY tag)
#   assignment-1:
#     due: 2026-10-13T23:59            # a bare date -> END of that day (23:59:59)
#     grace_days: 2                     # OPTIONAL: extra days for GRADING only (not shown
#                                       # to students). Autograder pins to due + grace_days.
#   assignment-2:
#     due: 2026-11-10
#
# exams:
#   - name: MidTerm Exam
#     date: 2026-11-03
#   - name: Final Exam
#     date: 2026-12-15
"""

# This cohort's own instructors/TAs (unlike course_admins, declared once at course
# level - see _FACULTY_BLOCK) - most cohorts have different lecturers/TAs, so they're
# declared here instead. Seeded live (not a .sample) and mostly commented, matching
# schedule.yml's uncomment-what-you-want UX.
_PEOPLE_YML = """# This cohort's instructors/TAs - the single source of truth for GitHub push
# access to this cohort's own team AND a course-org instructors-<tag> team (scoped
# to this year's content repos, plus the central .github repo for the central
# dispatch buttons). Course admins are declared at the course-org level instead (see
# that org's .github/dsl-course.yml). Uncomment and fill what you want:
#
# people:
#   instructors:
#     - github_handle: "janedoe"      # required - grants the `instructors` team
#       name: "Prof. Jane Doe"        # optional, display only
#       title: "Professor of ..."
#       photo: "https://.../jane.jpg"
#       url: "https://.../profile/jane"
#       start: "2026-09-01"           # optional - no start = active immediately
#       end: "2027-01-31"             # optional - no end = indefinite
#   teaching_assistants:
#     - github_handle: "anOther"
#       name: "..."                  # optional, display only
#       photo: "https://.../ta.jpg"
#       url: "https://.../profile/ta"
#       start: "2026-09-01"
#       end: "2027-01-31"
"""


def _course_admins_block(admins: list[str] | None) -> str:
    """The `people.course_admins` block for a freshly-seeded dsl-course.yml. With no
    admins given, ships fully commented out (today's default, uncomment-what-you-want
    UX). Given admins (from bootstrap's --admins), seeds them LIVE (uncommented) - so
    they're declared in the SSOT from day one, not just given a one-time direct team
    invite (add_course_admins) that the next sync would otherwise revert for not
    being declared here."""
    if not admins:
        return _FACULTY_BLOCK
    entries = "\n".join(
        f'    - github_handle: "{a}"    # grants the `course-admin` team' for a in admins
    )
    return _PEOPLE_HEADER + ("people:\n" "  course_admins:\n" f"{entries}\n") + _CARD_SCAFFOLD


def _course_metadata(
    org: str,
    org_name: str,
    course_name: str,
    course_code: str,
    admins: list[str] | None = None,
) -> str:
    """dsl-course.yml for the persistent COURSE org: identity + course_admins (the
    single source of truth for course-wide admin access, mirrored into every cohort
    org's own course-admin team by sync_faculty). Instructors/TAs and the schedule
    both stay per-cohort instead (they change year to year and, for instructors/TAs,
    usually the people too)."""
    return (
        f"org: {org}\n"
        f"org_name: {org_name}\n"
        f"course_name: {course_name}\n"
        f"course_code: {course_code or ''}\n"
        "\n"
        "# This is the persistent COURSE org - it spans many cohorts (years). Cohorts are\n"
        "# registered separately in .github/cohort-courses-pages.yml. The schedule changes\n"
        "# year to year, so it's declared PER COHORT in that cohort's own\n"
        "# classroom-config/schedule.yml, not here.\n"
        f"\n{_course_admins_block(admins)}"
    )


def _cohort_metadata(org: str, course: str) -> str:
    """dsl-course.yml for a COHORT org's .github repo: a pointer back to its persistent
    course org. This is the single source the cohort's classroom-config dispatchers
    (dispatch-sync / dispatch-sync-site) read to find where to fire Sync membership /
    Sync site - so without it those auto-triggers can't resolve the course org."""
    return (
        "# This cohort org points back to its persistent course org. Read by the\n"
        "# classroom-config dispatchers (dispatch-sync / dispatch-sync-site) to find where\n"
        "# to fire Sync membership / Sync site. Identity + schedule live elsewhere (the\n"
        "# course org's dsl-course.yml and this cohort's classroom-config/schedule.yml).\n"
        f"course: {course}\n"
        f"org: {org}\n"
    )


def create_profile_repo(
    org: str,
    org_name: str,
    course_name: str,
    course_code: str = "",
    *,
    is_cohort: bool = False,
    admins: list[str] | None = None,
) -> None:
    """Create the .github profile repo with README, and (course orgs only) course
    metadata.

    Also tags the repo with `dsl-course-hub` so `list_orgs.py` can discover it.

    The course org's dsl-course.yml carries identity + the faculty roster. A cohort org
    instead gets a tiny `.github/dsl-course.yml` pointer back to its course org (written
    in main()'s cohort wiring via _cohort_metadata, once --course is known) - the
    classroom-config dispatchers read its `course:` line. Its schedule lives in
    classroom-config/schedule.yml. `admins` (course org only) seeds dsl-course.yml's
    people.course_admins live from the start - see _course_admins_block.
    """
    log_step("Setting up .github profile repo")
    if not create_repo(
        org,
        ".github",
        private=False,
        description="Org profile and configuration",
    ):
        return

    if not is_cohort:
        # Course metadata - canonical machine-readable source for discovery tooling.
        # (The org-overview profile/README.md is generated at the end of bootstrap,
        # once all repos exist, by seed.update_profile_readme - see main.)
        metadata = _course_metadata(org, org_name, course_name, course_code, admins)
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


def _classroom_config_template(rel: str) -> bytes:
    """Read a seeded classroom-config template from templates/classroom-config/."""
    return (
        Path(__file__).resolve().parents[1] / "templates" / "classroom-config" / rel
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
            "schedule.yml",
            _SCHEDULE_YML.encode(),
            "docs: seed schedule.yml (release plan + due dates + exams)",
        )
        put_file(
            org,
            "classroom-config",
            "people.yml",
            _PEOPLE_YML.encode(),
            "docs: seed people.yml (this cohort's instructors/TAs)",
        )
        put_file(
            org,
            "classroom-config",
            ".github/workflows/dispatch-sync.yml",
            _classroom_config_template("dispatch-sync.yml"),
            "ci: seed dispatch-sync workflow",
        )
        put_file(
            org,
            "classroom-config",
            ".github/workflows/dispatch-sync-site.yml",
            _classroom_config_template("dispatch-sync-site.yml"),
            "ci: seed dispatch-sync-site workflow",
        )
        log_ok("classroom-config seeded (roster + README + grades/ + samples)")

    # Public, auto-deployed cohort website (from course-website-template).
    scaffold.scaffold_site(org)


def seed_workflows(org: str) -> None:
    """Seed the org-level workflows into the course org's .github repo. The full set
    (central Release materials/assignment + Sync membership/Bootstrap-cohort/Refresh) is
    rendered by dsl_course.seed (single source of truth)."""
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
        "the course-admin team (admin on .github) so they can run the buttons - and, on "
        "a course-org bootstrap, declared in dsl-course.yml's SSOT so a later sync doesn't "
        "revert it. Each accepts an org invite once. Add instructors/TAs later via the "
        "org's Teams page.",
    )
    args = parser.parse_args()

    org_name = args.org_name or args.org
    course_name = args.course_name or org_name
    admin_logins = _parse_handles(args.admins)

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

    # 3. Profile repo (course org only - identity + faculty roster; a cohort org
    # gets no dsl-course.yml, its config all lives in classroom-config). --admins is
    # seeded into the SSOT here (course org only - see _course_admins_block) as well
    # as given a one-time direct team invite below (add_course_admins), so the next
    # sync doesn't undo that invite.
    create_profile_repo(
        args.org,
        org_name,
        course_name,
        args.course_code,
        is_cohort=args.cohort,
        admins=admin_logins if not args.cohort else None,
    )

    # 3b. Course vs cohort wiring.
    if args.cohort:
        # Cohort: student-facing welcome + roster + tightened perms.
        setup_cohort_extras(args.org)
        if args.course:
            # Pointer back to the course org, in this cohort's .github/dsl-course.yml -
            # the classroom-config dispatchers read its `course:` line to know where to
            # fire Sync membership / Sync site. Without it those auto-triggers fail.
            put_file(
                args.org,
                ".github",
                "dsl-course.yml",
                _cohort_metadata(args.org, args.course).encode(),
                "ci: seed cohort -> course pointer (dispatchers read this)",
            )
            seed.register_cohort(args.course, args.org)
            # Give this cohort the course's current, currently-active faculty roster
            # from day one (instructors/course-admin), rather than waiting for the
            # next push/cron sync. Scoped to just this cohort (cohorts=[args.org]) so
            # bootstrapping one more cohort doesn't re-touch every already-registered one.
            sync_faculty.sync(args.course, cohorts=[args.org])
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

    if admin_logins and not args.cohort:
        admins_step = (
            f"2. Course admins ({', '.join(admin_logins)}) are already declared in the "
            f"`people:` block of {args.org}/.github/dsl-course.yml - nothing to do here. "
            "Add more later by editing that file directly (not the Teams page - "
            "\"Sync membership\" reconciles the `course-admin` team FROM that file, so an "
            "undeclared manual addition gets reverted on the next sync). Instructors/TAs "
            "are declared per cohort instead, in that cohort's own "
            "classroom-config/people.yml (see step 4)."
        )
    else:
        admins_step = (
            f"2. Declare THIS course's course_admins in the `people:` block of "
            f"{args.org}/.github/dsl-course.yml, then push - \"Sync membership\" reconciles "
            "the `course-admin` team automatically (here and into every cohort's own "
            "course-admin team; no manual Teams-page edit needed). Instructors/TAs are "
            "declared per cohort instead, in that cohort's own classroom-config/people.yml "
            "(see step 4)."
        )
    log(f"""
============================================================
Course org bootstrap complete: {args.org}

DONE (automated):
============================================================
- Faculty teams: instructors, course-admin (students + auditors are created per cohort)
- Org settings: 2FA enforcement enabled
- .github profile repo with README
- Workflows in .github: Release materials, Release assignment, Sync membership,
  Bootstrap cohort, Refresh actions
- DSL_BOT_TOKEN secret validated (or set)
- Button access: instructors (write) + course-admin (admin) granted on .github; any
  --admins handles added to course-admin (they accept the org invite once, then the
  buttons appear in their Actions tab) and declared in dsl-course.yml's SSOT

NEXT STEPS (manual):
============================================================

1. Review org settings: https://github.com/{args.org}/settings

{admins_step}

3. Put content in the materials repo (any top-level dir with ordinal-prefixed
   subdirectories, e.g. lectures/00_.../, readings/00_.../) and create
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
            f"(edit https://github.com/{args.org}/classroom-config/blob/HEAD/students.csv with registrar data), "
            f"plus schedule.yml and people.yml (this cohort's calendar/due-dates and "
            f"instructors/TAs - both seeded mostly-commented, uncomment what you want)\n"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
