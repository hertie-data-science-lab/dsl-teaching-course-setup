"""dsl-course scheduler -- date-driven auto-release (manifest x calendar).

The same idempotent release functions as the manual buttons, fired automatically. A
**per-cohort release manifest** (what opens each session) lives course-side in the
`.github` repo as `manifests/<cohort-org>.yml` (one per cohort - source repos are
year-tagged); each cohort's **calendar** (session -> date) lives in its
`classroom-config/schedule.yml` (see `dsl_course.schedule`). A daily cron joins them:
every session whose date has arrived is (re-)released. Because every release is
idempotent, re-runs are no-ops and there is no "already released" state to track.

Manifest (`manifests/<cohort-org>.yml` in `<course>/.github`) - keys are the ordinal
session number (matching each section's `<NN>_<slug>/` directories, see release.py):
    sessions:
      "1":
        materials: {source_repo: course-materials-f2026, cohort_repo: materials}
      "3":
        materials: {source_repo: course-materials-f2026, cohort_repo: materials, exclude: [readings]}
        code:
          - {source_repo: lecture-code, path: mlpkg/simulation, cohort_repo: materials}
      "5":
        assignment: assignment-2-f2026
      "7":
        grade:
          template: assignment-2-f2026
          deadline: 2026-10-15   # grade the last commit on/before this date

Calendar - the `sessions:` map in `<cohort>/classroom-config/schedule.yml`:
    sessions:
      "1": 2026-09-01
      "3": 2026-09-15

Usage (the cron passes the cohort; --today is for testing):
    python3 -m dsl_course.scheduler --course-org COURSE --cohort-org COHORT
    python3 -m dsl_course.scheduler --course-org COURSE --cohort-org COHORT --dry-run
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

import yaml

from . import schedule
from .utils import get_file_content, log, log_err, log_ok, log_step

MANIFEST_REPO = ".github"  # the course org's .github repo
MANIFEST_DIR = "manifests"  # one manifest per cohort: manifests/<cohort-org>.yml


# --------------------------------------------------------------------------- pure core


def due_sessions(calendar: dict[str, date], today: date) -> list[str]:
    """Sessions whose scheduled date has arrived (<= today), in calendar order."""
    return [s for s, d in sorted(calendar.items(), key=lambda kv: kv[1]) if d <= today]


def plan(manifest: dict, sessions: list[str]) -> list[dict]:
    """Flatten the manifest's due sessions into an ordered list of release actions.

    Pure: no I/O. Each action is a dict with a `kind` the executor dispatches on. Unknown
    keys under a session are ignored so the manifest can carry comments/extras."""
    sessions_map = {
        str(k): v for k, v in ((manifest or {}).get("sessions") or {}).items()
    }
    actions: list[dict] = []
    for session in sessions:
        entry = sessions_map.get(session) or {}
        if "materials" in entry:
            m = entry["materials"] or {}
            actions.append(
                {
                    "kind": "materials",
                    "session": session,
                    "source_repo": m.get("source_repo"),
                    "cohort_repo": m.get("cohort_repo", "materials"),
                    "exclude": set(m.get("exclude") or []),
                }
            )
        for c in entry.get("code") or []:
            actions.append(
                {
                    "kind": "code",
                    "source_repo": c.get("source_repo"),
                    "path": c.get("path"),
                    "cohort_repo": c.get("cohort_repo", "materials"),
                }
            )
        if entry.get("assignment"):
            actions.append({"kind": "assignment", "template": entry["assignment"]})
        if entry.get("grade"):
            # accept either `grade: <template>` or `grade: {template, deadline, group}`
            g = (
                {"template": entry["grade"]}
                if isinstance(entry["grade"], str)
                else entry["grade"]
            )
            actions.append(
                {
                    "kind": "grade",
                    "template": g.get("template"),
                    "deadline": g.get("deadline"),
                    "group": bool(g.get("group", False)),
                }
            )
    return actions


def describe(action: dict) -> str:
    """One-line human description of an action (for dry-run / 'what opens when')."""
    k = action["kind"]
    if k == "materials":
        return f"materials session {action['session']} from {action['source_repo']} -> {action['cohort_repo']}"
    if k == "code":
        return f"code {action['path']} from {action['source_repo']} -> {action['cohort_repo']}"
    if k == "grade":
        return f"grade {action['template']} (deadline {action['deadline'] or 'from schedule'})"
    return f"assignment {action['template']}"


def manifest_path(cohort_org: str) -> str:
    """This cohort's manifest path within the course org's MANIFEST_REPO."""
    return f"{MANIFEST_DIR}/{cohort_org}.yml"


# ---------------------------------------------------------------------- gh/git wiring


def _load_manifest(course_org: str, cohort_org: str) -> dict:
    """Load this cohort's manifest from the course org's .github repo. Each cohort has its
    own file (source repos are year-tagged), so a missing one just means 'not scheduled'."""
    path = manifest_path(cohort_org)
    content = get_file_content(course_org, MANIFEST_REPO, path)
    if content is None:
        log(
            f"  (no {path} in {course_org}/{MANIFEST_REPO} - {cohort_org} not scheduled)"
        )
        return {}
    return yaml.safe_load(content) or {}


def _execute(course_org: str, cohort_org: str, action: dict) -> int:
    """Dispatch one action to the matching idempotent release function."""
    kind = action["kind"]
    if kind == "materials":
        from .release import release

        return release(
            course_org,
            action["source_repo"],
            cohort_org,
            action["cohort_repo"],
            action["session"],
            exclude=action["exclude"],
        )
    if kind == "code":
        from .release_code import release_code

        return release_code(
            course_org,
            action["source_repo"],
            cohort_org,
            action["cohort_repo"],
            action["path"],
        )
    if kind == "assignment":
        from .assign import provision_all

        return provision_all(course_org, action["template"], cohort_org)
    if kind == "grade":
        from .collect import collect

        # deadline=None -> collect resolves it from the cohort schedule (SSOT)
        return collect(
            course_org,
            action["template"],
            cohort_org,
            action["deadline"],
            group=action["group"],
        )
    log_err(f"unknown action kind: {kind}")
    return 1


def run(course_org: str, cohort_org: str, today: date, dry_run: bool = False) -> int:
    manifest = _load_manifest(course_org, cohort_org)
    if not manifest:
        return 0  # cohort not using scheduled release - nothing to do
    sched = schedule.load(cohort_org)
    if not sched.sessions:
        log_err(
            f"no sessions in {cohort_org}/{schedule.CONFIG_REPO}/{schedule.SCHEDULE_PATH} "
            "- no dates set."
        )
        return 1  # has a manifest but no dates - a misconfiguration (already logged)
    sessions = due_sessions(sched.sessions, today)
    actions = plan(manifest, sessions)
    log_step(
        f"Scheduler {course_org} -> {cohort_org} as of {today}: "
        f"{len(sessions)} due session(s), {len(actions)} release action(s)"
    )
    if not actions:
        log_ok("nothing due.")
        return 0

    errors = 0
    for action in actions:
        if dry_run:
            log(f"    DRY-RUN  {describe(action)}")
            continue
        if _execute(course_org, cohort_org, action) != 0:
            errors += 1
    if dry_run:
        return 0
    if errors:
        log_err(f"{errors} action(s) failed")
        return 1
    log_ok("scheduler run complete")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--course-org", required=True, help="Course org (manifest source)"
    )
    parser.add_argument(
        "--cohort-org", default=None, help="One cohort; omit and use --all-cohorts"
    )
    parser.add_argument(
        "--all-cohorts",
        action="store_true",
        help="Run every cohort registered with the course org (the daily cron).",
    )
    parser.add_argument(
        "--today", default=None, help="Override today (ISO date) - for testing."
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    today = date.fromisoformat(args.today) if args.today else date.today()

    if args.all_cohorts:
        from .seed import discover_cohorts

        cohorts = discover_cohorts(args.course_org)
        if not cohorts:
            log_err(f"no cohorts registered with {args.course_org}.")
            return 1
        rc = 0
        for cohort in cohorts:
            rc |= run(args.course_org, cohort, today, dry_run=args.dry_run)
        return rc

    if not args.cohort_org:
        log_err("pass --cohort-org or --all-cohorts.")
        return 1
    return run(args.course_org, args.cohort_org, today, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
