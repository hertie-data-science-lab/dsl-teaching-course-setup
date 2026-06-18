"""dsl-course scaffold -- create correctly-structured course-materials / assignment repos.

Replaces the old "use this template" repo: the required structure is defined here in
code, so a new repo is always laid out the way the Release actions expect.

    scaffold materials   --org X --tag f2026                 -> course-materials-f2026
    scaffold assignment  --org X --number 1 --tag f2026      -> assignment-1-f2026

Materials repos get `lectures/week-1/` + `readings/week-1/` skeletons and the
run-from-repo Release buttons. Assignment repos get a starter on `main` (no tests - grading
is faculty-side) and a `solution` branch carrying the model solution, `grading.yml`, and the
HIDDEN tests, so generate never ships any of them to students.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

from . import seed
from .utils import (
    GIT_ENV,
    create_repo,
    generate_from_template,
    gh,
    git,
    log,
    log_err,
    log_ok,
    log_skip,
    log_step,
    put_file,
    repo_exists,
    set_repo_topics,
)

WEBSITE_TEMPLATE_ORG = "hertie-data-science-lab"
WEBSITE_TEMPLATE = "course-website-template"

_GIT_ENV = GIT_ENV

_GRADING_YML = """\
# How the Grade assignment button autogrades this assignment (faculty-side, after the
# deadline). Delete this file (or set autograde: false) for a purely manually-graded one.
type: individual      # or group
format: py            # or notebook
autograde: true       # false -> skip autograding (all-manual)
max_auto: 0           # points the hidden tests are worth (0 = informational)
tests: tests          # path (on THIS solution branch) holding the hidden tests
"""

_HIDDEN_TEST = """\
# HIDDEN tests - run faculty-side by the Grade assignment button, never shipped to
# students. They import the student's submission (the repo root) and check it. Replace
# this placeholder with the real grading tests.
from starter import solve


def test_solve_runs():
    assert solve() is not None
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
        "**Refresh actions** so the week dropdown picks them up.\n\n"
        "## Public course website (optional)\n\n"
        "The **Publish course website** action can share this repo's materials on a public "
        "open-courseware site. Lecture files are always hosted; for readings you choose "
        "`reading-list` (text/citation files are shown as a list - keep copyrighted PDFs out "
        "of the list by leaving them as non-text files) or `actual-readings` (every reading "
        "file is hosted and downloadable - you carry the copyright responsibility).\n"
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
    # main: starter only (what students receive on generate). No tests, no autograder -
    # grading runs faculty-side from the solution branch (see Grade assignment).
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
    set_repo_topics(org, repo, [f"assignment-{number}", "assignment"])

    # solution branch: the model solution, grading.yml, and the HIDDEN tests - all kept OFF
    # main so generate never copies them into student repos.
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
        # grading.yml + hidden tests for the faculty-side Grade assignment button.
        (wd / "grading.yml").write_text(_GRADING_YML)
        tests = wd / "tests"
        tests.mkdir()
        (tests / "test_solution.py").write_text(_HIDDEN_TEST)
        git("-C", str(wd), *_GIT_ENV, "add", "-A")
        git(
            "-C",
            str(wd),
            *_GIT_ENV,
            "commit",
            "-q",
            "--no-verify",
            "-m",
            f"solution: assignment {number} (model + grading.yml + hidden tests)",
        )
        if (
            git("-C", str(wd), *_GIT_ENV, "push", "-q", "-u", "origin", "solution")[0]
            != 0
        ):
            log_err("  ! could not push the solution branch")
            return 1
    log_ok(f"assignment template ready: {org}/{repo} (main + solution)")
    return 0


def scaffold_site(org: str) -> int:
    """Generate an org's public website (from course-website-template) and enable GitHub
    Pages with the template's deploy-on-push workflow. Used for both the per-cohort
    student-facing site and the opt-in public course site - the org is whatever's passed.

    The repo is named `<org>.github.io` so it serves at the org root. It must be PUBLIC
    on the Free plan (Pages requires it); on GitHub Enterprise Cloud / Campus it can be
    made private with Pages access control. The site redeploys on every push."""
    site = f"{org.lower()}.github.io"
    log_step(f"Scaffolding website {org}/{site}")
    if repo_exists(org, site):
        log_skip(f"repo {org}/{site}")
    elif not generate_from_template(
        template_org=WEBSITE_TEMPLATE_ORG,
        template_name=WEBSITE_TEMPLATE,
        owner=org,
        name=site,
        private=False,
        description="Course website (auto-deployed on push)",
    ):
        log_err(
            f"  ! could not generate the site from {WEBSITE_TEMPLATE_ORG}/{WEBSITE_TEMPLATE}"
        )
        return 1

    # Enable Pages with the GitHub Actions ("workflow") build, so the template's
    # deploy.yml publishes the site. Ignore "already enabled".
    code, out = gh(
        "api",
        "--method",
        "POST",
        f"repos/{org}/{site}/pages",
        "-f",
        "build_type=workflow",
    )
    if code != 0 and "409" not in out and "already" not in out.lower():
        gh(
            "api",
            "--method",
            "PUT",
            f"repos/{org}/{site}/pages",
            "-f",
            "build_type=workflow",
        )

    # The auto-created github-pages environment restricts which branches may deploy, and
    # the template's default branch (master) is not on that list - clear the policy so
    # any branch can deploy.
    gh(
        "api",
        "--method",
        "PUT",
        f"repos/{org}/{site}/environments/github-pages",
        "-F",
        "deployment_branch_policy=null",
    )

    # template-generate doesn't fire workflows, so kick the first deploy by hand. The
    # workflow takes a few seconds to index after generate, so retry the dispatch.
    for _ in range(6):
        if gh("workflow", "run", "deploy.yml", "--repo", f"{org}/{site}")[0] == 0:
            break
        time.sleep(5)
    else:
        log(
            "  (deploy not dispatched yet - it will deploy on the next push to the site repo)"
        )
    log_ok(f"site deploying -> https://{org.lower()}.github.io/")
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
    ps = sub.add_parser("site")
    ps.add_argument("--org", required=True)
    args = parser.parse_args()
    if args.cmd == "materials":
        return scaffold_materials(args.org, args.tag)
    if args.cmd == "site":
        return scaffold_site(args.org)
    return scaffold_assignment(args.org, args.number, args.tag)


if __name__ == "__main__":
    sys.exit(main())
