"""dsl-course collect -- faculty-side autograding (hidden tests, after the deadline).

Runs entirely in a faculty-controlled job (course-org Actions, bot token). For each
submission repo it checks out the last commit dated on or before the deadline, overlays
the assignment's HIDDEN tests (kept on the course template's `solution` branch, never
shipped to students), runs them, and records a machine score into the PRIVATE grades CSV.
Faculty then add manual marks and the existing grades pipeline emails the result - so a
student never sees a score in their own repo.

  course/<template> @ solution branch  ->  grading.yml + hidden tests
                |
  cohort/<slug>-<handle>  (individual)   clone @ deadline, overlay tests, run
  cohort/<slug>-<team>    (group)              |
                v
  classroom-config/autograde/<slug>/<key>.json   (per-test detail, private archive)
  classroom-config/grades/<slug>.csv             (auto / team_grade columns filled)

Student code is run in a subprocess with the GitHub token stripped from the environment.

grading.yml (on the template's solution branch):
    type: individual        # or group
    format: py              # or notebook
    autograde: true         # false -> skip (all-manual)
    max_auto: 10
    tests: tests            # path on the solution branch holding the hidden tests

Usage:
    python3 -m dsl_course.collect \\
        --master-org COURSE --template assignment-1-f2026 \\
        --cohort-org COHORT --deadline 2026-10-15 [--group] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import yaml

from . import grades, roster, teams
from .assign import SOLUTION_BRANCH, assignment_slug
from .utils import (
    GIT_ENV,
    get_file_content,
    gh,
    git,
    log,
    log_err,
    log_ok,
    log_step,
    put_file,
)

CONFIG_REPO = roster.CONFIG_REPO  # classroom-config
AUTOGRADE_DIR = "autograde"  # classroom-config/autograde/<slug>/<key>.json
GRADING_FILE = "grading.yml"  # on the template's solution branch
RUN_TIMEOUT = 300  # seconds per submission

_DEFAULT_SPEC = {
    "type": "individual",
    "format": "py",
    "autograde": True,
    "max_auto": None,
    "tests": "tests",
}


# --------------------------------------------------------------------------- pure core


def parse_grading_spec(text: str) -> dict:
    """Parse a grading.yml (missing keys fall back to defaults; extras ignored)."""
    data = yaml.safe_load(text) if text.strip() else {}
    if not isinstance(data, dict):
        data = {}
    spec = dict(_DEFAULT_SPEC)
    spec.update({k: data[k] for k in _DEFAULT_SPEC if k in data})
    return spec


def score_from_junit(xml_text: str) -> dict:
    """Turn a pytest junit XML report into the result.json contract {score, max, tests}.

    A case passes only if it has neither failure, error, nor skipped child element."""
    root = ET.fromstring(xml_text)
    if root.tag == "testsuite":
        suite = root
    else:
        nested = root.find("testsuite")
        suite = nested if nested is not None else root
    cases = [
        {
            "name": tc.get("name"),
            "passed": tc.find("failure") is None
            and tc.find("error") is None
            and tc.find("skipped") is None,
        }
        for tc in suite.findall("testcase")
    ]
    return {
        "score": sum(1 for c in cases if c["passed"]),
        "max": len(cases),
        "tests": cases,
    }


def summary_lines(result: dict) -> list[str]:
    """Human-readable per-target summary (plain tick/cross glyphs, never emoji)."""
    lines = [f"  Score: {result['score']}/{result['max']}"]
    if result.get("note"):
        lines.append(f"  ({result['note']})")
    lines += [f"    {'✓' if c['passed'] else '✗'} {c['name']}" for c in result["tests"]]
    return lines


# ---------------------------------------------------------------------- gh/git wiring


def _sanitised_env() -> dict:
    """A copy of the environment with every GitHub token stripped - student code must
    never run with the bot token in scope."""
    env = dict(os.environ)
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_API_TOKEN", "GH_ENTERPRISE_TOKEN"):
        env.pop(key, None)
    return env


def _pin_commit(repo_dir: Path, deadline: str) -> str | None:
    """Check out the last commit dated on or before end-of-day `deadline` (ISO date).
    Returns the sha, or None if there is no such commit (no submission by the deadline)."""
    code, out = git(
        "-C", str(repo_dir), "rev-list", "-1", f"--before={deadline} 23:59:59", "HEAD"
    )
    sha = out.strip()
    if code != 0 or not sha:
        return None
    git("-C", str(repo_dir), *GIT_ENV, "checkout", "-q", sha)
    return sha


def _run_tests(workdir: Path, fmt: str, tests_src: Path) -> dict | None:
    """Overlay the hidden tests into the checked-out submission and run them token-free.
    Returns the result.json dict, or None if grading could not run."""
    env = _sanitised_env()
    env["PYTHONPATH"] = str(workdir) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        if fmt == "notebook":
            # Convert each notebook to an importable script first (Otter can slot in here).
            for nb in workdir.rglob("*.ipynb"):
                subprocess.run(
                    [sys.executable, "-m", "jupyter", "nbconvert", "--to", "script", str(nb)],
                    cwd=workdir, env=env, timeout=RUN_TIMEOUT, capture_output=True,
                )
        dest = workdir / "_grading_tests"
        shutil.copytree(tests_src, dest, dirs_exist_ok=True)
        report = workdir / "report.xml"
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(dest), f"--junitxml={report}"],
            cwd=workdir, env=env, timeout=RUN_TIMEOUT, capture_output=True,
        )
    except subprocess.TimeoutExpired:
        log_err(f"  ! grading timed out after {RUN_TIMEOUT}s")
        return None
    if not report.exists():
        return None
    return score_from_junit(report.read_text())


def _grade_target(cohort_org: str, repo: str, spec: dict, tests_src: Path, deadline: str) -> dict | None:
    """Clone one submission, pin to the deadline, run the hidden tests. Always returns a
    result dict (a zero with a note for non-submissions / failures), or None if unclonable."""
    max_auto = spec.get("max_auto") or 0
    with tempfile.TemporaryDirectory() as work:
        wd = Path(work) / "sub"
        if gh("repo", "clone", f"{cohort_org}/{repo}", str(wd), "--", "-q")[0] != 0:
            log_err(f"  ! could not clone {cohort_org}/{repo} (not generated yet?)")
            return None
        sha = _pin_commit(wd, deadline)
        if sha is None:
            return {"score": 0, "max": max_auto, "tests": [], "note": f"no submission on/before {deadline}"}
        result = _run_tests(wd, spec["format"], tests_src)
        if result is None:
            return {"score": 0, "max": max_auto, "tests": [], "note": "grading failed to run"}
        result["commit"] = sha
        return result


def collect(
    master_org: str,
    template: str,
    cohort_org: str,
    deadline: str,
    group: bool = False,
    dry_run: bool = False,
) -> int:
    """Autograde every submission for `template` as of `deadline`, archiving result.json and
    recording the machine score into the cohort's private grades CSV. Idempotent."""
    if master_org == cohort_org:
        log_err("master-org and cohort-org must differ.")
        return 1
    slug = assignment_slug(template)

    with tempfile.TemporaryDirectory() as sd:
        soldir = Path(sd) / "sol"
        if (
            gh("repo", "clone", f"{master_org}/{template}", str(soldir), "--", "-q",
               "-b", SOLUTION_BRANCH)[0] != 0
        ):
            log_err(
                f"no `{SOLUTION_BRANCH}` branch on {master_org}/{template} - no hidden "
                f"tests to run; nothing to collect."
            )
            return 0
        spec_path = soldir / GRADING_FILE
        spec = parse_grading_spec(spec_path.read_text() if spec_path.is_file() else "")
        if not spec["autograde"]:
            log_ok(f"{slug}: autograde disabled in {GRADING_FILE} - all-manual, nothing to collect.")
            return 0
        is_group = group or spec["type"] == "group"
        tests_src = soldir / str(spec["tests"])
        if not tests_src.is_dir():
            log_err(f"{slug}: tests path `{spec['tests']}` not found on the solution branch.")
            return 1

        # Targets: one per team (group) or one per onboarded student (individual).
        if is_group:
            groups = teams.teams_for(teams.load(cohort_org), slug)
            if not groups:
                log_err(f"no teams for `{slug}` in {cohort_org}/{CONFIG_REPO}/teams.csv.")
                return 1
            targets = [(f"{slug}-{team}", team, members) for team, members in sorted(groups.items())]
        else:
            onboarded = [s for s in roster.load(cohort_org) if s.onboarded]
            targets = [(f"{slug}-{s.github_handle}", s.github_handle, [s.github_handle]) for s in onboarded]
            if not targets:
                log_err(f"no onboarded students in {cohort_org} to grade.")
                return 1

        log_step(
            f"Collecting {slug} in {cohort_org}: {len(targets)} "
            f"{'team(s)' if is_group else 'student(s)'} as of {deadline}"
        )

        updates: list[tuple[str, dict[str, str]]] = []
        for repo, key, members in targets:
            log_step(repo)
            if dry_run:
                log(f"    DRY-RUN would grade {cohort_org}/{repo} (pin to <= {deadline})")
                continue
            result = _grade_target(cohort_org, repo, spec, tests_src, deadline)
            if result is None:
                continue
            for line in summary_lines(result):
                log(line)
            put_file(
                cohort_org, CONFIG_REPO, f"{AUTOGRADE_DIR}/{slug}/{key}.json",
                json.dumps(result, indent=2).encode(), f"autograde: {slug}/{key}",
            )
            score = str(result["score"])
            if is_group:
                updates += [(m, {"team": key, "team_grade": score}) for m in members]
            else:
                updates.append((key, {"auto": score}))

        if dry_run:
            return 0
        if not updates:
            log_err("nothing graded.")
            return 1

        path = f"{grades.GRADES_DIR}/{slug}.csv"
        existing = get_file_content(cohort_org, CONFIG_REPO, path) or ""
        new_csv = grades.merge_auto(existing, updates)
        if not put_file(
            cohort_org, CONFIG_REPO, path, new_csv.encode(),
            f"autograde: record auto scores for {slug}",
        ):
            log_err(f"could not write {path}")
            return 1
    log_ok(f"recorded {len(updates)} auto score(s) -> {path} (faculty add manual marks, then render)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-org", required=True, help="Course org (template source)")
    parser.add_argument("--template", required=True, help="Assignment template (e.g. assignment-1-f2026)")
    parser.add_argument("--cohort-org", required=True, help="Cohort org (submissions)")
    parser.add_argument(
        "--deadline", default=None, help="ISO date; grade the last commit on/before it (default: today)"
    )
    parser.add_argument("--group", action="store_true", help="Group assignment (one repo per team)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    deadline = args.deadline or date.today().isoformat()
    return collect(
        args.master_org, args.template, args.cohort_org, deadline,
        group=args.group, dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
