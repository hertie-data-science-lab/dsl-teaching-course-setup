"""dsl-course assign -- bulk-create assignment repos, Classroom-free.

Per ADR 0007 + 0009: DSL skips GitHub Classroom and creates per-student (or
per-team) submission repos directly from a template. The template lives in
the course org; submissions are created in the per-cohort satellite org.

Usage (per-student, Option H):
    python3 -m dsl_course.assign \\
        --course-org Hertie-School-Deep-Learning-E1394 \\
        --satellite-org hertie-dl-f2026 \\
        --semester f2026 \\
        --assignment assignment-1 \\
        --template assignment-1-f2026

Usage (per-team):
    python3 -m dsl_course.assign \\
        --course-org Hertie-School-Deep-Learning-E1394 \\
        --satellite-org hertie-dl-f2026 \\
        --semester f2026 \\
        --assignment assignment-1 \\
        --template assignment-1-f2026 \\
        --teams-file semesters/f2026/teams/assignment-1.yml

Legacy single-org mode (pre-Option-H, still supported):
    python3 -m dsl_course.assign \\
        --org Hertie-School-Example-Course \\
        --semester f2025 \\
        --assignment assignment-1 \\
        --template assignment-1-f2025

Teams file format:
    team-alpha:
      - github_login_a
      - github_login_b

Writes a mapping manifest to:
    {course-org}.github.io/semesters/{semester}/assignments/{assignment}.yml
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import yaml

from .utils import (
    add_collaborator,
    extract_logins,
    generate_from_template,
    get_file_content,
    log,
    log_err,
    log_ok,
    log_step,
    put_file,
    set_repo_topics,
)


def load_roster(org: str, semester: str) -> dict:
    website = f"{org.lower()}.github.io"
    path = f"semesters/{semester}/hertie-semester.yml"
    content = get_file_content(org, website, path)
    if content is None:
        log_err(f"Could not find {path} in {org}/{website}")
        return {}
    return yaml.safe_load(content) or {}


def load_teams_file(org: str, semester: str, teams_path: str) -> dict[str, list[str]]:
    website = f"{org.lower()}.github.io"
    content = get_file_content(org, website, teams_path)
    if content is None:
        log_err(f"Could not find {teams_path} in {org}/{website}")
        return {}
    parsed = yaml.safe_load(content) or {}
    if not isinstance(parsed, dict):
        log_err(f"{teams_path} must be a YAML mapping of team -> [logins]")
        return {}
    return parsed


def slugify(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in value.lower()).strip(
        "-"
    )


def create_submission_repo(
    template_org: str,
    template: str,
    dest_org: str,
    repo_name: str,
    collaborators: list[str],
    course_code: str,
    semester: str,
    assignment: str,
    description: str,
) -> tuple[str, list[str]]:
    """Generate a repo from template in dest_org, add collaborators, apply topics.

    template_org and dest_org may be the same (legacy single-org mode) or
    different (Option H: template in course org, submission in satellite).

    Returns (status, failed_collaborators).
    """
    ok = generate_from_template(
        template_org=template_org,
        template_name=template,
        owner=dest_org,
        name=repo_name,
        private=True,
        description=description,
    )
    if not ok:
        return "failed-create", []

    failed = []
    for login in collaborators:
        if not login:
            continue
        if not add_collaborator(dest_org, repo_name, login, permission="push"):
            failed.append(login)
        else:
            log_ok(f"  + {login}")

    topics = [
        f"cohort-{semester}",
        f"course-{course_code.lower().replace('grad-', '').replace('_', '-')}",
        slugify(assignment),
        "submission",
    ]
    set_repo_topics(dest_org, repo_name, topics)

    return "created" if not failed else "created-with-errors", failed


def write_manifest(
    org: str,
    semester: str,
    assignment: str,
    assignments_map: list[dict],
) -> None:
    website = f"{org.lower()}.github.io"
    path = f"semesters/{semester}/assignments/{assignment}.yml"
    manifest = {
        "semester": semester,
        "assignment": assignment,
        "org": org,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "assigned_to": assignments_map,
    }
    content = yaml.dump(manifest, sort_keys=False, allow_unicode=True)
    put_file(
        org,
        website,
        path,
        content.encode(),
        f"assign: {assignment} / {semester}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--course-org",
        default=None,
        help="Course org where the template + roster live (Option H)",
    )
    parser.add_argument(
        "--satellite-org",
        default=None,
        help="Per-cohort satellite org where submissions are created (Option H)",
    )
    parser.add_argument(
        "--org",
        default=None,
        help="Legacy single-org mode (pre-Option-H). Ignored if --course-org given.",
    )
    parser.add_argument("--semester", required=True)
    parser.add_argument(
        "--assignment", required=True, help="Assignment slug, e.g. assignment-1"
    )
    parser.add_argument(
        "--template",
        required=True,
        help="Template repo name (lives in --course-org under Option H)",
    )
    parser.add_argument(
        "--teams-file",
        default=None,
        help="Optional path in website repo to teams YAML. "
        "If omitted, one repo per student in the roster.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Resolve Option H vs legacy mode
    if args.course_org:
        course_org = args.course_org
        satellite_org = args.satellite_org or args.course_org
    elif args.org:
        course_org = args.org
        satellite_org = args.org
    else:
        log_err("Specify --course-org (with optional --satellite-org) or --org.")
        return 1

    log_step(f"Loading roster for {course_org} / {args.semester}")
    roster = load_roster(course_org, args.semester)
    if not roster:
        return 1
    course_code = roster.get("course_code", "")

    # Build assignment plan: {repo_name: [collaborator_logins]}
    plan: dict[str, list[str]] = {}

    if args.teams_file:
        log_step(f"Loading teams from {args.teams_file}")
        teams = load_teams_file(course_org, args.semester, args.teams_file)
        if not teams:
            return 1
        for team_name, members in teams.items():
            repo_name = f"{args.assignment}-{args.semester}-{slugify(team_name)}"
            plan[repo_name] = [m for m in members if m]
    else:
        students = extract_logins(roster.get("students"))
        if not students:
            log_err(
                "Roster has no students. Either populate `students:` in "
                "hertie-semester.yml or pass --teams-file."
            )
            return 1
        for login in students:
            repo_name = f"{args.assignment}-{args.semester}-{login.lower()}"
            plan[repo_name] = [login]

    log(
        f"  plan: {len(plan)} submission repos -> {satellite_org} "
        f"(template: {course_org}/{args.template})"
    )

    if args.dry_run:
        for repo_name, logins in plan.items():
            log(f"    DRY-RUN  {satellite_org}/{repo_name}  <- {', '.join(logins)}")
        return 0

    # Execute
    results = []
    for repo_name, logins in plan.items():
        log_step(f"{repo_name}")
        status, failed = create_submission_repo(
            template_org=course_org,
            template=args.template,
            dest_org=satellite_org,
            repo_name=repo_name,
            collaborators=logins,
            course_code=course_code,
            semester=args.semester,
            assignment=args.assignment,
            description=f"{args.assignment} submission - {args.semester}",
        )
        results.append(
            {
                "repo": repo_name,
                "collaborators": logins,
                "status": status,
                "failed_collaborators": failed,
            }
        )

    # Write manifest
    log_step(
        f"Writing manifest to semesters/{args.semester}/assignments/{args.assignment}.yml"
    )
    # Manifest lives in the course org's website repo (stable identity)
    write_manifest(course_org, args.semester, args.assignment, results)

    # Summary
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    log_ok(f"Done — {json.dumps(by_status)}")

    any_failed = any(
        r["status"].startswith("failed") or r["failed_collaborators"] for r in results
    )
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
