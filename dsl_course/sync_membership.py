"""dsl-course sync-membership -- consolidated roster + teams + faculty sync.

One entrypoint replacing three separate buttons' worth of orchestration:

- course_admins (from the course org's declared `people:` block) ALWAYS reconciles
  everywhere - the course org itself + every cohort registered under it
  (sync_faculty.sync_course_admins) - regardless of which cohort (if any) triggered
  this sync, since admin access is course-wide by design.
- Roster (students.csv), project teams (teams.csv), and each cohort's own
  instructors/TAs (classroom-config/people.yml, via
  sync_faculty.sync_cohort_instructors) additionally reconcile for whichever
  cohort(s) are in scope: one named cohort (--cohort-org, e.g. a push to that
  cohort's classroom-config), or every registered cohort (--all-cohorts, e.g. the
  daily cron - a full resync with no single cohort in context).

Every reconcile here is FULL (add + remove) - there is no --prune flag at this level;
config is the live truth, so a deleted roster row or a lapsed faculty `end` date
revokes access on the very next sync.

Usage:
    python3 -m dsl_course.sync_membership --course-org Deep-Learning-EXAMPLE
    python3 -m dsl_course.sync_membership --course-org Deep-Learning-EXAMPLE --cohort-org Deep-Learning-EXAMPLE-f2026
    python3 -m dsl_course.sync_membership --course-org Deep-Learning-EXAMPLE --all-cohorts
"""

from __future__ import annotations

import argparse
import sys

from . import seed, sync_faculty, sync_roster, sync_teams
from .utils import log_err, log_ok


def sync(
    course_org: str,
    cohort_org: str | None = None,
    all_cohorts: bool = False,
    dry_run: bool = False,
) -> int:
    # course_admins always reconciles everywhere, independent of which cohort (if
    # any) triggered this sync.
    all_registered = seed.discover_cohorts(course_org)
    errors = sync_faculty.sync_course_admins(course_org, all_registered, dry_run=dry_run)

    # Roster/teams/instructors reconcile only for whichever cohort(s) are in scope -
    # not fanned out to every other, unrelated cohort.
    targets = list(all_registered) if all_cohorts else ([cohort_org] if cohort_org else [])
    content_repos = seed.discover_content_repos(course_org) if targets else []
    assignments = seed.discover_assignments(course_org) if targets else []
    for org in targets:
        errors += sync_roster.sync(org, prune=True, dry_run=dry_run)
        errors += sync_teams.sync(org, prune=True, dry_run=dry_run)
        errors += sync_faculty.sync_cohort_instructors(
            course_org, org, content_repos, assignments, dry_run=dry_run
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-org", required=True)
    parser.add_argument("--cohort-org", default=None)
    parser.add_argument(
        "--all-cohorts",
        action="store_true",
        help="Also reconcile roster/teams for every registered cohort (not just --cohort-org).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    errors = sync(
        args.course_org,
        cohort_org=args.cohort_org,
        all_cohorts=args.all_cohorts,
        dry_run=args.dry_run,
    )
    if errors:
        log_err(f"{errors} errors during sync")
        return 1
    log_ok("Sync complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
