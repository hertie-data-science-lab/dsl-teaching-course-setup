"""dsl-course scaffold -- create correctly-structured course-materials / assignment repos.

Replaces the old "use this template" repo: the required structure is defined here in
code, so a new repo is always laid out the way the Release actions expect.

    scaffold materials   --org X --tag f2026                 -> course-materials-f2026
    scaffold assignment  --org X --number 1 --tag f2026      -> assignment-1-f2026

Materials repos get `lectures/00_session-1/` + `readings/00_session-1/` skeletons (any
top-level directory with an ordinal-prefixed subdirectory is a releasable section - add
more, e.g. `labs/`, freely) and the run-from-repo Release buttons. Assignment repos get
a starter on `main` (no tests - grading is faculty-side) and a `solution` branch
carrying the model solution, `grading.yml`, and the HIDDEN tests, so generate never
ships any of them to students.
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
    grant_course_team_access,
    grant_tagged_team_access,
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
        description="Course materials (lectures/readings by session)",
    ):
        return 1
    grant_course_team_access(org, repo)
    grant_tagged_team_access(org, repo, tag)
    # README.md is student-facing: Release materials with the README toggle copies THIS
    # file into the cohort's materials repo, where enrolled students read it. So it ships
    # as a replace-me placeholder written for students - the faculty how-this-repo-works
    # reference lives in MAINTAINING.md (a root file that is never released: release only
    # copies section folders, the syllabus, and README.md).
    readme = (
        "<!-- FACULTY: replace the content below with a real, student-facing overview of\n"
        "     your course materials. Release materials with the 'include README' toggle\n"
        "     copies THIS file into the cohort's materials repo, where enrolled students\n"
        "     read it - so write it for them, not as internal notes. How this source repo\n"
        "     is structured (for you, not students) is in MAINTAINING.md. -->\n\n"
        "# Course materials\n\n"
        "> **Replace this placeholder.** This becomes the students' README for the released\n"
        "> materials. Add a short overview of the course, how the materials are organised,\n"
        "> and anything students should read first.\n"
    )
    maintaining = (
        f"# Maintaining `{repo}` (faculty)\n\n"
        "Faculty reference for this materials **source** repo. This file is **not** released "
        "to students - Release materials only copies session folders, the syllabus, and "
        "(when toggled) `README.md`, so keep student-facing wording in `README.md` and "
        "faculty notes here.\n\n"
        "## Structure\n\n"
        "Any top-level directory containing at least one ordinal-prefixed subdirectory "
        "(`00_`, `01_`, `02_`, ...) is a releasable section - no config to declare it:\n\n"
        "- `lectures/00_session-1/` - one folder per session's lecture files\n"
        "- `readings/00_session-1/` - one folder per session's readings\n"
        "- `*syllabus*`, `README.md` (root) - released via the syllabus / README toggles\n\n"
        "Add more sessions by creating `lectures/01_session-2/`, `readings/01_session-2/`, ... "
        "(only the ordinal prefix matters - name the rest whatever you like), or add a whole "
        "new section (e.g. `labs/00_intro/`) - then run **Refresh actions** so the session "
        "dropdown and Release button's section toggles pick it up.\n\n"
        "## Public course website (optional)\n\n"
        "The **Publish course website** action can share this repo's materials on a public "
        "open-courseware site. Lecture files are always hosted; for readings you choose "
        "`reading-list` (text/citation files are shown as a list - keep copyrighted PDFs out "
        "of the list by leaving them as non-text files) or `actual-readings` (every reading "
        "file is hosted and downloadable - you carry the copyright responsibility).\n"
    )
    files = {
        "README.md": readme.encode(),
        "MAINTAINING.md": maintaining.encode(),
        "lectures/00_session-1/.gitkeep": b"",
        "readings/00_session-1/.gitkeep": b"",
        "SYLLABUS.md": f"# {tag} syllabus\n\nReplace with the real syllabus.\n".encode(),
    }
    for path, content in files.items():
        put_file(org, repo, path, content, "init: materials skeleton")
    # Equip the run-from-repo Release buttons (same as Refresh does for content repos).
    cohorts = seed.discover_cohorts(org)
    seed._push_workflows(
        org,
        repo,
        cohorts,
        seed.discover_cohort_repos(cohorts),
        seed.discover_assignments(org),
    )
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
    grant_course_team_access(org, repo)
    grant_tagged_team_access(org, repo, tag)
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


def _latest_deploy_run_id(org: str, site: str) -> str | None:
    """Newest deploy.yml run id for the site repo, or None if there are none yet."""
    code, out = gh(
        "api",
        f"repos/{org}/{site}/actions/workflows/deploy.yml/runs",
        "--jq",
        ".workflow_runs[0].id // empty",
    )
    return out.strip() if code == 0 and out.strip() else None


def _await_run(org: str, site: str, run_id: str, timeout: int = 180) -> str | None:
    """Poll a workflow run to completion; return its conclusion (e.g. 'success',
    'failure') or None on timeout."""
    waited = 0
    while waited < timeout:
        code, out = gh(
            "api", f"repos/{org}/{site}/actions/runs/{run_id}", "--jq", ".status,.conclusion"
        )
        if code == 0:
            parts = out.split()
            if parts and parts[0] == "completed":
                return parts[1] if len(parts) > 1 else ""
        time.sleep(6)
        waited += 6
    return None


def _dispatch_deploy(org: str, site: str) -> str | None:
    """Dispatch deploy.yml and return the id of the run it triggers, or None. The
    workflow takes a few seconds to index after template-generate, so retry the
    dispatch; then wait for a new run (distinct from any prior one) to appear."""
    before = _latest_deploy_run_id(org, site)
    for _ in range(6):
        if gh("workflow", "run", "deploy.yml", "--repo", f"{org}/{site}")[0] == 0:
            break
        time.sleep(5)
    else:
        return None
    for _ in range(10):
        rid = _latest_deploy_run_id(org, site)
        if rid and rid != before:
            return rid
        time.sleep(3)
    return None


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

    # The auto-created github-pages environment restricts which branches may deploy -
    # clear the policy so any branch (the template's default, plus sync-site's pushes)
    # can deploy.
    gh(
        "api",
        "--method",
        "PUT",
        f"repos/{org}/{site}/environments/github-pages",
        "-F",
        "deployment_branch_policy=null",
    )

    # template-generate doesn't fire workflows, so kick the first deploy by hand AND
    # confirm it lands. Enabling Pages with build_type=workflow races the platform's
    # provisioning, so the first deploy often fails transiently ("Deployment failed, try
    # again later"); re-dispatch a couple of times, waiting for each run to finish. A
    # miss is non-fatal - the site deploys on the first content push (your first Release)
    # anyway - but confirming here avoids a freshly-bootstrapped org showing a dead site.
    for attempt in range(1, 4):
        run_id = _dispatch_deploy(org, site)
        if run_id is None:
            continue
        conclusion = _await_run(org, site, run_id)
        if conclusion == "success":
            log_ok(f"site deployed -> https://{org.lower()}.github.io/")
            return 0
        log(f"  (deploy attempt {attempt} did not succeed: {conclusion or 'timed out'})")
        time.sleep(10)
    log(
        "  (site not deployed yet - it will deploy on the next push to the site repo, "
        "e.g. your first Release materials)"
    )
    log_ok(f"site scaffolded -> https://{org.lower()}.github.io/")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    pm = sub.add_parser("materials")
    pm.add_argument("--org", required=True)
    pm.add_argument("--tag", required=True, help="Year tag, e.g. f2026 or s2026")
    pa = sub.add_parser("assignment")
    pa.add_argument("--org", required=True)
    pa.add_argument("--number", required=True)
    pa.add_argument("--tag", required=True, help="Year tag, e.g. f2026 or s2026")
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
