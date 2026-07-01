"""dsl-course sync-faculty -- materialise instructors/course-admin team membership from
the COURSE org's dsl-course.yml `people:` block.

The course org is the single source of truth for who is an instructor/TA/course-admin
(unlike students/auditors, which stay cohort-only in classroom-config/students.csv).
GitHub has no cross-org team permission, so this reconciles the SAME desired state
independently into the course org's own `instructors`/`course-admin` teams AND into
every cohort org registered under it (seed.discover_cohorts) - nothing is copied
between orgs as a config file, each org's team membership is just an application of
the one shared source.

Each person entry requires `github_handle` (the only field that grants access);
`start`/`end` (optional ISO dates) bound when they're active, giving auto-rotation
with no manual removal step. This is a FULL reconcile (add + remove) every run - a
lapsed `end` date or a deleted entry revokes access on the next sync, same as an
edit to students.csv/teams.csv.

Usage:
    python3 -m dsl_course.sync_faculty --course-org Deep-Learning-EXAMPLE
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

import yaml

from . import seed
from .utils import active_today, get_file_content, log_err, log_ok, log_step, reconcile_team_members

ROLE_TEAM = {
    "instructors": "instructors",
    "teaching_assistants": "instructors",
    "course_admins": "course-admin",
}


def parse_faculty(raw: str) -> dict[str, list[dict]]:
    """Parse a course org's dsl-course.yml text for its `people:` block. Entries
    missing `github_handle` are skipped (it's the only required field)."""
    meta = yaml.safe_load(raw) if raw else {}
    people = meta.get("people") if isinstance(meta, dict) else None
    if not isinstance(people, dict):
        return {}
    faculty: dict[str, list[dict]] = {}
    for role in ROLE_TEAM:
        entries = []
        for p in people.get(role) or []:
            if isinstance(p, dict) and p.get("github_handle"):
                entries.append(p)
            else:
                log_err(f"  ! skipping {role} entry with no github_handle: {p!r}")
        faculty[role] = entries
    return faculty


def load_faculty(course_org: str) -> dict[str, list[dict]]:
    """Fetch + parse the course org's `.github/dsl-course.yml` `people:` block."""
    raw = get_file_content(course_org, ".github", "dsl-course.yml") or ""
    return parse_faculty(raw)


def desired_team_members(
    faculty: dict[str, list[dict]], today: str
) -> dict[str, set[str]]:
    """Flatten active entries (per `today`, an ISO date string) via ROLE_TEAM ->
    {'instructors': {handles}, 'course-admin': {handles}}."""
    desired: dict[str, set[str]] = {team: set() for team in set(ROLE_TEAM.values())}
    for role, entries in faculty.items():
        team = ROLE_TEAM[role]
        for p in entries:
            if active_today(p.get("start"), p.get("end"), today):
                desired[team].add(p["github_handle"])
    return desired


def reconcile_org(org: str, desired: dict[str, set[str]], dry_run: bool = False) -> int:
    """Full add+remove reconcile of each team in `desired` to exactly match - no prune
    flag, always full (config is the live truth)."""
    return sum(
        reconcile_team_members(org, team, wanted, prune=True, dry_run=dry_run)
        for team, wanted in desired.items()
    )


def sync(
    course_org: str, cohorts: list[str] | None = None, dry_run: bool = False
) -> int:
    """Reconcile the course org itself + `cohorts` (every registered cohort, if not
    given - pass an explicit single-item list to scope to just one, e.g. a freshly
    bootstrapped cohort, without re-touching every other cohort)."""
    faculty = load_faculty(course_org)
    if not faculty:
        log_ok(f"no people: block declared in {course_org} - nothing to sync.")
        return 0
    today = date.today().isoformat()
    desired = desired_team_members(faculty, today)
    targets = [course_org] + (
        seed.discover_cohorts(course_org) if cohorts is None else cohorts
    )
    log_step(f"Materialising faculty access across {len(targets)} org(s)")
    errors = 0
    for org in targets:
        errors += reconcile_org(org, desired, dry_run=dry_run)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-org", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    errors = sync(args.course_org, dry_run=args.dry_run)
    if errors:
        log_err(f"{errors} errors during sync")
        return 1
    log_ok("Sync complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
