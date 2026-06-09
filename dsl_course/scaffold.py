"""dsl-course scaffold -- create correctly-structured course-materials / assignment repos.

Replaces the old "use this template" repo: the required structure is defined here in
code, so a new repo is always laid out the way the Release actions expect.

    scaffold materials   --org X --tag f2026                 -> course-materials-f2026
    scaffold assignment  --org X --number 1 --tag f2026      -> assignment-1-f2026

Materials repos get `lectures/week-1/` + `readings/week-1/` skeletons and the
run-from-repo Release buttons. Assignment repos get a starter + autograder on `main`
and an (empty) `solution` branch - solutions live there so generate never ships them.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from . import seed
from .utils import (
    create_repo,
    gh,
    git,
    log_err,
    log_ok,
    log_step,
    put_file,
    set_repo_topics,
)

_GIT_ENV = [
    "-c",
    "user.email=bot@dsl.local",
    "-c",
    "user.name=dsl-bot",
    "-c",
    "core.hooksPath=/dev/null",
]

_AUTOGRADE = """name: Autograde

# Dormant autograder (runs on push to main). Wire up Otter/nbgrader -> result.json later.
on:
  push:
    branches: [main]
jobs:
  autograde:
    runs-on: ubuntu-latest
    steps:
      - run: echo "Autograding deferred - submission = this push (${{ github.sha }})."
"""


def scaffold_materials(org: str, tag: str) -> int:
    repo = f"course-materials-{tag}"
    log_step(f"Scaffolding {org}/{repo}")
    if not create_repo(
        org,
        repo,
        private=True,
        description="Course materials (lectures/readings by week)",
    ):
        return 1
    readme = (
        f"# {repo}\n\nCourse materials - the source for the **Release materials** action.\n\n"
        "## Structure\n\n"
        "- `lectures/week-N/` - one folder per week's lecture files\n"
        "- `readings/week-N/` - one folder per week's readings\n"
        "- `*syllabus*`, this `README.md` (root) - released via the syllabus / README toggles\n\n"
        "Add more weeks by creating `lectures/week-2/`, `readings/week-2/`, ... then run "
        "**Refresh actions** so the week dropdown picks them up.\n"
    )
    files = {
        "README.md": readme.encode(),
        "lectures/week-1/.gitkeep": b"",
        "readings/week-1/.gitkeep": b"",
        "SYLLABUS.md": f"# {tag} syllabus\n\nReplace with the real syllabus.\n".encode(),
    }
    for path, content in files.items():
        put_file(org, repo, path, content, "init: materials skeleton")
    # Equip the run-from-repo Release buttons (same as Refresh does for content repos).
    cohorts = seed.discover_cohorts(org)
    seed._push_workflows(org, repo, cohorts, seed.discover_cohort_repos(cohorts))
    log_ok(f"materials repo ready: {org}/{repo}")
    return 0


def scaffold_assignment(org: str, number: str, tag: str) -> int:
    repo = f"assignment-{number}-{tag}"
    log_step(f"Scaffolding {org}/{repo} (template + solution branch)")
    if not create_repo(
        org,
        repo,
        private=True,
        is_template=True,
        description=f"Assignment {number} template",
    ):
        return 1
    # main: starter + autograder (what students receive on generate).
    put_file(
        org,
        repo,
        "README.md",
        f"# Assignment {number}\n\nComplete the TODOs in `starter.py` and push to `main` "
        "(that push is your submission).\n".encode(),
        "init: assignment starter",
    )
    put_file(
        org,
        repo,
        "starter.py",
        f'"""Assignment {number}."""\n\n\ndef solve():\n    raise NotImplementedError  # TODO\n'.encode(),
        "init: starter",
    )
    put_file(
        org,
        repo,
        ".github/workflows/autograde.yml",
        _AUTOGRADE.encode(),
        "ci: autograder",
    )
    set_repo_topics(org, repo, [f"assignment-{number}", "assignment"])

    # solution branch: a solution/ folder, kept OFF main so generate never copies it.
    with tempfile.TemporaryDirectory() as work:
        wd = Path(work) / "r"
        if gh("repo", "clone", f"{org}/{repo}", str(wd), "--", "-q")[0] != 0:
            log_err("  ! could not clone to add the solution branch")
            return 1
        git("-C", str(wd), *_GIT_ENV, "checkout", "-q", "-b", "solution")
        sol = wd / "solution"
        sol.mkdir()
        (sol / "solution.py").write_text(
            f'"""Model solution for assignment {number} (stub)."""\n\n\ndef solve():\n    return 42  # TODO\n'
        )
        (sol / "README.md").write_text(
            f"# Assignment {number} - model solution\n\n"
            "Released to students after the deadline via Release assignment with "
            "**include_solution** ticked.\n"
        )
        git("-C", str(wd), *_GIT_ENV, "add", "-A")
        git(
            "-C",
            str(wd),
            *_GIT_ENV,
            "commit",
            "-q",
            "--no-verify",
            "-m",
            f"solution: assignment {number} (stub)",
        )
        if (
            git("-C", str(wd), *_GIT_ENV, "push", "-q", "-u", "origin", "solution")[0]
            != 0
        ):
            log_err("  ! could not push the solution branch")
            return 1
    log_ok(f"assignment template ready: {org}/{repo} (main + solution)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    pm = sub.add_parser("materials")
    pm.add_argument("--org", required=True)
    pm.add_argument("--tag", required=True, help="Year tag, e.g. f2026")
    pa = sub.add_parser("assignment")
    pa.add_argument("--org", required=True)
    pa.add_argument("--number", required=True)
    pa.add_argument("--tag", required=True, help="Year tag, e.g. f2026")
    args = parser.parse_args()
    if args.cmd == "materials":
        return scaffold_materials(args.org, args.tag)
    return scaffold_assignment(args.org, args.number, args.tag)


if __name__ == "__main__":
    sys.exit(main())
