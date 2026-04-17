"""dsl-course sync-roster -- sync hertie-semester.yml -> GitHub teams.

Reads semesters/{semester}/hertie-semester.yml from the course website
repo, reconciles GitHub team membership to match. Idempotent.

Designed to run inside a GitHub Action (weekly cron + on push).

Usage:
    python3 -m dsl_course.sync_roster \\
        --org Hertie-School-Deep-Learning-E1394 \\
        --semester f2025 \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys

import yaml

from .utils import (
    add_team_member,
    extract_logins,
    get_file_content,
    gh,
    log,
    log_err,
    log_ok,
    log_skip,
    log_step,
)


def get_team_members(org: str, team_slug: str) -> set[str]:
    code, out = gh(
        "api",
        f"orgs/{org}/teams/{team_slug}/members?per_page=100",
        "--paginate",
    )
    if code != 0:
        return set()
    try:
        return {m["login"] for m in json.loads(out)}
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log_err(f"could not parse team members for {team_slug}: {e}")
        return set()


def remove_team_member(org: str, team_slug: str, login: str) -> bool:
    code, _ = gh(
        "api",
        "--method",
        "DELETE",
        f"orgs/{org}/teams/{team_slug}/memberships/{login}",
    )
    return code == 0


def list_org_team_slugs(org: str) -> set[str]:
    """Fetch all team slugs in an org in one paginated call."""
    code, out = gh(
        "api",
        f"orgs/{org}/teams?per_page=100",
        "--paginate",
        "--jq",
        "[.[].slug]",
    )
    if code != 0:
        return set()
    try:
        return set(json.loads(out))
    except json.JSONDecodeError:
        return set()


def load_roster(org: str, semester: str) -> dict:
    """Fetch semesters/{semester}/hertie-semester.yml from the website repo.

    One roster per cohort - all preserved historically. The sync Action
    receives the semester as input and reads that cohort's file.
    """
    website_repo = f"{org.lower()}.github.io"
    path = f"semesters/{semester}/hertie-semester.yml"
    content = get_file_content(org, website_repo, path)
    if content is None:
        log_err(
            f"Could not find {path} in {org}/{website_repo} - "
            f"run new-semester first to bootstrap this cohort."
        )
        return {}
    return yaml.safe_load(content) or {}


def sync(org: str, semester: str, dry_run: bool = False) -> int:
    log_step(f"Syncing roster for {org} / {semester}")
    roster = load_roster(org, semester)
    if not roster:
        return 1

    desired = {
        f"instructors-{semester}": set(
            extract_logins(roster.get("instructors"))
            + extract_logins(roster.get("teaching_assistants"))
        ),
        f"students-{semester}": set(extract_logins(roster.get("students"))),
        f"auditors-{semester}": set(extract_logins(roster.get("auditors"))),
    }

    existing_team_slugs = list_org_team_slugs(org)
    errors = 0

    for team_slug, wanted_logins in desired.items():
        if team_slug not in existing_team_slugs:
            log_skip(
                f"team {team_slug} does not exist - skipping (run new-semester first)"
            )
            continue

        current = get_team_members(org, team_slug)
        to_add = wanted_logins - current
        to_remove = current - wanted_logins

        log(f"\n  {team_slug}:")
        log(
            f"    current: {len(current)}  wanted: {len(wanted_logins)}  "
            f"add: {len(to_add)}  remove: {len(to_remove)}"
        )

        for login in sorted(to_add):
            if dry_run:
                log(f"    DRY-RUN add: {login}")
            elif add_team_member(org, team_slug, login):
                log_ok(f"    added {login}")
            else:
                errors += 1

        for login in sorted(to_remove):
            if dry_run:
                log(f"    DRY-RUN remove: {login}")
            elif remove_team_member(org, team_slug, login):
                log_ok(f"    removed {login}")
            else:
                errors += 1

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True)
    parser.add_argument("--semester", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    errors = sync(args.org, args.semester, dry_run=args.dry_run)
    if errors:
        log_err(f"{errors} errors during sync")
        return 1
    log_ok("Sync complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
