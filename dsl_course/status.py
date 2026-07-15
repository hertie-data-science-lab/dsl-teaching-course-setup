"""dsl-course status -- a per-cohort checklist of every faculty & instructors input location.

Faculty & instructors currently touch several distinct files across 2 orgs to run a cohort: course
identity, course admins, and classroom-config's roster/teams/grades/schedule.yml (which
now carries the release plan too)/people.yml. This module answers one glance-able question -
what's configured, what's still missing, and where do I go to fix it - by reusing
each source's existing loader rather than re-deriving anything. Read-only; it
changes no state.

Row IDs mirror docs/faculty-and-instructors/required-input-schema.md's B/C numbering, so the status view
and that doc's table stay in lockstep.

Usage:
    python3 -m dsl_course.status --course-org COURSE --cohort-org COHORT
    python3 -m dsl_course.status --course-org COURSE --cohort-org COHORT --format json
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from datetime import date

import yaml

from . import grades, roster, schedule, sync_faculty, teams
from .utils import get_default_branch, get_file_content

ITEMS = ("B1", "B6", "C2", "C3", "C4", "C5", "C6", "C7")
# Mandatory per docs/faculty-and-instructors/required-input-schema.md; everything else is optional
# (synthesised/skipped when absent), so an absent optional item is "optional", not
# "missing" - the status view shouldn't cry wolf over things that never block the pipeline.
REQUIRED = {"B1", "C2"}


# --------------------------------------------------------------------------- pure core


def _edit_url(org: str, repo: str, path: str, branch: str, exists: bool) -> str:
    if exists:
        return f"https://github.com/{org}/{repo}/edit/{branch}/{path}"
    return f"https://github.com/{org}/{repo}/new/{branch}?filename={path}"


def _row(
    item_id: str, label: str, org: str, repo: str, path: str, branch: str,
    present: bool, detail: str,
) -> dict:
    status = "ok" if present else ("missing" if item_id in REQUIRED else "optional")
    return {
        "label": label,
        "org": org,
        "repo": repo,
        "path": path,
        "status": status,
        "detail": detail,
        "edit_url": _edit_url(org, repo, path, branch, present),
    }


def render_markdown(course_org: str, cohort_org: str, data: dict[str, dict]) -> str:
    """One markdown table, in `docs/faculty-and-instructors/required-input-schema.md`'s B/C order, each
    row linking straight to the file to fix if something's missing."""
    icon = {"ok": "OK", "missing": "MISSING", "optional": "not set (optional)"}
    lines = [
        f"## Status: {cohort_org} (course: {course_org})",
        "",
        "| Item | Status | Detail | |",
        "| --- | --- | --- | --- |",
    ]
    for item_id in ITEMS:
        row = data[item_id]
        link_text = "edit" if row["status"] == "ok" else "add"
        lines.append(
            f"| {row['label']} | {icon[row['status']]} | {row['detail'] or '-'} "
            f"| [{link_text}]({row['edit_url']}) |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------- gh/git wiring


def collect(course_org: str, cohort_org: str) -> dict[str, dict]:
    """One status row per faculty & instructors input location for `cohort_org`. Read-only."""
    course_raw = get_file_content(course_org, ".github", "dsl-course.yml")
    course_meta = (yaml.safe_load(course_raw) or {}) if course_raw else {}

    # Every course-org row lives in .github; every cohort row lives in
    # classroom-config - resolve each default branch once, not once per row.
    course_branch = get_default_branch(course_org, ".github")
    cohort_branch = get_default_branch(cohort_org, schedule.CONFIG_REPO)

    data: dict[str, dict] = {}

    course_name = course_meta.get("course_name") or course_meta.get("org_name") or ""
    data["B1"] = _row(
        "B1", "Course identity", course_org, ".github", "dsl-course.yml", course_branch,
        bool(course_name), course_name,
    )

    # Access is granted by github_handle alone (sync_faculty's actual criterion) -
    # site._people_from_meta requires a display `name` too (it's for website cards),
    # so it undercounts here. Reuse the already-fetched course_raw. course-admin only
    # - a course-level `instructors`/`teaching_assistants` entry is a legitimate,
    # display-only website card (see the People section in
    # docs/faculty-and-instructors/required-input-schema.md), not access, so it must not inflate
    # this count.
    has_people_block = isinstance(course_meta.get("people"), dict)
    course_faculty = sync_faculty.parse_faculty(course_raw or "")
    course_desired = sync_faculty.desired_team_members(
        course_faculty, date.today().isoformat()
    )
    n_admins = len(course_desired.get("course-admin", set()))
    data["B6"] = _row(
        "B6", "Course admins", course_org, ".github", "dsl-course.yml", course_branch,
        has_people_block, f"{n_admins} active" if has_people_block else "falls back to GitHub teams",
    )

    students = roster.load(cohort_org)
    onboarded = sum(s.onboarded for s in students)
    data["C2"] = _row(
        "C2", "Roster", cohort_org, roster.CONFIG_REPO, roster.ROSTER_PATH, cohort_branch,
        bool(students), f"{len(students)} student(s), {onboarded} onboarded" if students else "",
    )

    grade_sources = grades.load_grade_sources(cohort_org)
    data["C3"] = _row(
        "C3", "Grades", cohort_org, grades.CONFIG_REPO, grades.GRADES_DIR, cohort_branch,
        bool(grade_sources), f"{len(grade_sources)} assignment(s)" if grade_sources else "",
    )

    team_data = teams.load(cohort_org)
    n_teams = sum(len(t) for t in team_data.values())
    data["C4"] = _row(
        "C4", "Teams", cohort_org, teams.CONFIG_REPO, teams.TEAMS_PATH, cohort_branch,
        bool(team_data),
        f"{n_teams} team(s) across {len(team_data)} assignment(s)" if team_data else "",
    )

    sched = schedule.load(cohort_org)

    n_actions = sum(
        len(r.deploy) + bool(r.assignment) + bool(r.grade) for r in sched.releases
    )
    data["C5"] = _row(
        "C5", f"Release plan ({schedule.SCHEDULE_PATH} -> materials_releases)",
        cohort_org, schedule.CONFIG_REPO, schedule.SCHEDULE_PATH, cohort_branch,
        bool(sched.releases),
        f"{len(sched.releases)} scheduled release(s), {n_actions} action(s)"
        if sched.releases else "",
    )

    has_due_dates = bool(sched.semester_start or sched.assignments or sched.exams)
    data["C6"] = _row(
        "C6", f"Due dates & exams ({schedule.SCHEDULE_PATH})",
        cohort_org, schedule.CONFIG_REPO, schedule.SCHEDULE_PATH, cohort_branch,
        has_due_dates,
        f"start={sched.semester_start}, {len(sched.assignments)} due date(s), "
        f"{len(sched.exams)} exam(s)" if has_due_dates else "",
    )

    cohort_faculty = sync_faculty.load_cohort_faculty(cohort_org)
    cohort_desired = sync_faculty.desired_team_members(
        cohort_faculty, date.today().isoformat()
    )
    n_instructors = len(cohort_desired.get("instructors", set()))
    data["C7"] = _row(
        "C7", f"Instructors/TAs ({sync_faculty.COHORT_PEOPLE_PATH})",
        cohort_org, sync_faculty.COHORT_CONFIG_REPO, sync_faculty.COHORT_PEOPLE_PATH,
        cohort_branch,
        bool(n_instructors), f"{n_instructors} active" if n_instructors else "",
    )

    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-org", required=True)
    parser.add_argument("--cohort-org", required=True)
    parser.add_argument("--format", choices=["md", "json"], default="md")
    args = parser.parse_args()
    if args.format == "json":
        # collect()'s dependencies (schedule.load, roster.load, ...) log informational
        # lines to stdout - fine for the human-facing markdown mode, but --format json
        # promises clean, parseable output, so keep those off stdout here.
        with contextlib.redirect_stdout(io.StringIO()):
            data = collect(args.course_org, args.cohort_org)
        print(json.dumps(data, indent=2))
    else:
        data = collect(args.course_org, args.cohort_org)
        print(render_markdown(args.course_org, args.cohort_org, data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
