"""dsl-course sync-teams -- materialise per-(assignment, team) GitHub Teams from teams.csv.

The group "access" half, mirroring sync_roster for enrolment. `teams.csv` (in the cohort's
private classroom-config) is the single source of truth for who is in which project team for
which assignment; this reconciles a GitHub Team `<assignment>-<team>` from each row so the
team's repo access + @mentions track the CSV. Idempotent.

The Teams are a DOWNSTREAM PROJECTION of the CSV, never authoritative, so they can't drift -
a re-sync overwrites them to match. Provisioning a group assignment grants the matching team
on the group's repo (so post-sync membership edits propagate to access automatically).

With --prune, members no longer in the CSV are removed from their team (off-boarding) - never
an org Owner or the acting login (see utils.reconcile_team_members); off by default here so a
standalone/manual run never silently revokes access. Emptied teams are left in place. The seeded **Sync membership** button (dsl_course.sync_membership) always calls this
with prune=True - config is meant to be the live truth there; this module's own off-by-default
is only for ad-hoc/CLI use outside that button.

Usage:
    python3 -m dsl_course.sync_teams --cohort-org Deep-Learning-EXAMPLE-f2026
    python3 -m dsl_course.sync_teams --cohort-org Deep-Learning-EXAMPLE-f2026 --prune
"""

from __future__ import annotations

import argparse
import sys

from . import roster, teams
from .utils import (
    create_team,
    log,
    log_err,
    log_ok,
    log_step,
    reconcile_team_members,
)


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
    """Create the team (idempotent) and reconcile its membership to `members`.

    Reconciliation goes through utils.reconcile_team_members so pruning inherits its
    guard: an org Owner - or the acting login, which GitHub auto-adds as a member of
    whatever team it creates - is never removed. Without it, a maintainer or the bot
    sitting in a project team would be evicted on the next pruning sync."""
    ok = create_team(
        org, slug, description="Project team (auto-managed from teams.csv)"
    )
    if not ok:
        return False
    return reconcile_team_members(org, slug, members, prune=prune) == 0


def known_handles(students: list[roster.Student] | None) -> set[str]:
    """The onboarded roster handles - the only accounts teams.csv may add.

    Adding a handle to a GitHub Team also INVITES it to the org if it isn't a member
    yet, so an unvetted teams.csv handle (a typo, or a placeholder name that happens
    to collide with a real GitHub account) would invite an arbitrary stranger. The
    roster is the SSOT of who belongs to the cohort; teams.csv only groups them."""
    return {s.github_handle for s in students or [] if s.onboarded}


def sync(cohort_org: str, prune: bool = False, dry_run: bool = False) -> int:
    wanted = desired_teams(teams.load(cohort_org))
    if not wanted:
        log_ok("no project teams defined yet - nothing to sync.")
        return 0
    log_step(f"Materialising {len(wanted)} project team(s) in {cohort_org}")
    allowed = known_handles(roster.load(cohort_org))
    errors = 0
    for slug in sorted(wanted):
        members = wanted[slug]
        for unknown in sorted(members - allowed):
            log_err(
                f"{unknown} in teams.csv is not an onboarded roster handle - "
                f"not adding to {slug} (would invite an arbitrary GitHub account)"
            )
            errors += 1
        members = members & allowed
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
