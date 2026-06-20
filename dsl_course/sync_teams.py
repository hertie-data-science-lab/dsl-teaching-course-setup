"""dsl-course sync-teams -- materialise per-(assignment, team) GitHub Teams from teams.csv.

The group "access" half, mirroring sync_roster for enrolment. `teams.csv` (in the cohort's
private classroom-config) is the single source of truth for who is in which project team for
which assignment; this reconciles a GitHub Team `<assignment>-<team>` from each row so the
team's repo access + @mentions track the CSV. Idempotent.

The Teams are a DOWNSTREAM PROJECTION of the CSV, never authoritative, so they can't drift -
a re-sync overwrites them to match. Provisioning a group assignment grants the matching team
on the group's repo (so post-sync membership edits propagate to access automatically).

With --prune, members no longer in the CSV are removed from their team (off-boarding); off by
default so a stale CSV never silently revokes access. Emptied teams are left in place.

Usage:
    python3 -m dsl_course.sync_teams --cohort-org Deep-Learning-EXAMPLE-f2026
    python3 -m dsl_course.sync_teams --cohort-org Deep-Learning-EXAMPLE-f2026 --prune
"""

from __future__ import annotations

import argparse
import sys

from . import teams
from .sync_roster import get_team_members, remove_team_member
from .utils import add_team_member, create_team, log, log_err, log_ok, log_step


def team_slug(assignment: str, team: str) -> str:
    """The GitHub Team name/slug materialised for one (assignment, team) pair.

    Assignment-prefixed so a team name reused across assignments (e.g. `wizards` in two
    projects) maps to distinct org-unique teams. Lower-cased to match the slug GitHub
    derives from the team name."""
    return f"{assignment}-{team}".lower()


def desired_teams(per: dict[str, dict[str, list[str]]]) -> dict[str, set[str]]:
    """Flatten parsed teams.csv {assignment: {team: [handles]}} to {team_slug: {handles}}."""
    wanted: dict[str, set[str]] = {}
    for assignment, groups in per.items():
        for team, members in groups.items():
            wanted[team_slug(assignment, team)] = set(members)
    return wanted


def ensure_team(org: str, slug: str, members: set[str], prune: bool) -> bool:
    """Create the team (idempotent) and reconcile its membership to `members`."""
    ok = create_team(
        org, slug, description="Project team (auto-managed from teams.csv)"
    )
    if not ok:
        return False
    current = get_team_members(org, slug)
    for handle in sorted(members - current):
        if add_team_member(org, slug, handle):
            log_ok(f"{handle} -> {slug}")
        else:
            ok = False
    if prune:
        for handle in sorted(current - members):
            if remove_team_member(org, slug, handle):
                log_ok(f"removed {handle} from {slug}")
            else:
                ok = False
    return ok


def sync(cohort_org: str, prune: bool = False, dry_run: bool = False) -> int:
    wanted = desired_teams(teams.load(cohort_org))
    if not wanted:
        log_ok("no project teams defined yet - nothing to sync.")
        return 0
    log_step(f"Materialising {len(wanted)} project team(s) in {cohort_org}")
    errors = 0
    for slug in sorted(wanted):
        members = wanted[slug]
        if dry_run:
            log(
                f"    DRY-RUN team {slug}: {', '.join('@' + m for m in sorted(members))}"
            )
        elif not ensure_team(cohort_org, slug, members, prune):
            errors += 1
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-org", required=True)
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Remove team members no longer in teams.csv.",
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
