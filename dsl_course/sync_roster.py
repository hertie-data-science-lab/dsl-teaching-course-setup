"""dsl-course sync-roster -- materialise org + team access from students.csv.

The enrolment "access" half: ensure every onboarded student in the cohort's
students.csv is (a) a member of the cohort org and (b) in the single `students` team
(which carries cohort-private read on released materials/solutions). Idempotent.

Two modes:
  - whole roster (default): reconcile the `students` team to the roster.
  - single handle (--handle): faculty override / the welcome onboard path - enrol one.

With --prune, students no longer on the roster are removed from the team (off-boarding);
off by default so a stale roster never silently revokes access.

Usage:
    python3 -m dsl_course.sync_roster --cohort-org Deep-Learning-EXAMPLE-f2026
    python3 -m dsl_course.sync_roster --cohort-org Deep-Learning-EXAMPLE-f2026 --handle ada-lovelace
"""

from __future__ import annotations

import argparse
import json
import sys

from . import roster
from .utils import (
    add_team_member,
    gh,
    log,
    log_err,
    log_ok,
    log_step,
    set_org_membership,
)

TEAM = "students"


def get_team_members(org: str, team_slug: str) -> set[str]:
    code, out = gh(
        "api", f"orgs/{org}/teams/{team_slug}/members?per_page=100", "--paginate"
    )
    if code != 0:
        return set()
    try:
        return {m["login"] for m in json.loads(out)}
    except (json.JSONDecodeError, KeyError, TypeError):
        return set()


def remove_team_member(org: str, team_slug: str, login: str) -> bool:
    code, _ = gh(
        "api", "--method", "DELETE", f"orgs/{org}/teams/{team_slug}/memberships/{login}"
    )
    return code == 0


def enroll(org: str, handle: str) -> bool:
    """Grant one handle org membership + students-team membership."""
    ok = set_org_membership(org, handle, role="member")
    if add_team_member(org, TEAM, handle):
        log_ok(f"{handle} -> {TEAM} team")
    else:
        ok = False
    return ok


def sync(cohort_org: str, prune: bool = False, dry_run: bool = False) -> int:
    students = roster.load(cohort_org)
    if not students:
        return 1
    wanted = {s.github_handle for s in students if s.onboarded}
    log_step(
        f"Materialising access for {len(wanted)} onboarded student(s) in {cohort_org}"
    )

    current = get_team_members(cohort_org, TEAM)
    errors = 0

    for handle in sorted(wanted):
        if dry_run:
            log(f"    DRY-RUN enroll: {handle}")
        elif not enroll(cohort_org, handle):
            errors += 1

    if prune:
        for handle in sorted(current - wanted):
            if dry_run:
                log(f"    DRY-RUN remove: {handle}")
            elif remove_team_member(cohort_org, TEAM, handle):
                log_ok(f"removed {handle} from {TEAM}")
            else:
                errors += 1
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-org", required=True)
    parser.add_argument(
        "--handle", default=None, help="Enrol a single handle (faculty override)."
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Remove team members no longer on the roster.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.handle:
        log_step(f"Enrolling @{args.handle} into {args.cohort_org}")
        if args.dry_run:
            log(f"    DRY-RUN enroll: {args.handle}")
            return 0
        return 0 if enroll(args.cohort_org, args.handle) else 1

    errors = sync(args.cohort_org, prune=args.prune, dry_run=args.dry_run)
    if errors:
        log_err(f"{errors} errors during sync")
        return 1
    log_ok("Sync complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
