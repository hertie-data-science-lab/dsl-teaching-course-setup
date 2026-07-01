"""dsl-course sync-roster -- materialise org + team access from students.csv.

The enrolment "access" half: a single idempotent reconcile that ensures every onboarded
student in the cohort's students.csv is (a) a member of the cohort org and (b) in the
single `students` team (which carries cohort-private read on released materials/solutions).

Students normally grant themselves on Join (templates/welcome/onboard.yml); this is the
faculty true-up - edit students.csv, then re-run to reconcile the whole team to the roster.

With --prune, students no longer on the roster are removed from the team (off-boarding);
off by default here so a standalone/manual run never silently revokes access. The
seeded **Sync membership** button (dsl_course.sync_membership) always calls this with
prune=True - config is meant to be the live truth there; this module's own off-by-default
is only for ad-hoc/CLI use outside that button.

Usage:
    python3 -m dsl_course.sync_roster --cohort-org Deep-Learning-EXAMPLE-f2026
    python3 -m dsl_course.sync_roster --cohort-org Deep-Learning-EXAMPLE-f2026 --prune
"""

from __future__ import annotations

import argparse
import sys

from . import roster
from .utils import (
    add_team_member,
    get_team_members,
    log,
    log_err,
    log_ok,
    log_step,
    remove_team_member,
    set_org_membership,
)

TEAM = "students"


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
        "--prune",
        action="store_true",
        help="Remove team members no longer on the roster.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    errors = sync(args.cohort_org, prune=args.prune, dry_run=args.dry_run)
    if errors:
        log_err(f"{errors} errors during sync")
        return 1
    log_ok("Sync complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
