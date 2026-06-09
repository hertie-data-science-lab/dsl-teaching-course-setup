"""dsl-course assign -- provision per-student assignment repos from a template repo.

Generates ONE private repo per onboarded student from an assignment TEMPLATE repo
(e.g. assignment-1-f2026) in the course org, using GitHub's native template-generate,
then adds the student as a collaborator (maintain). The template carries its own
starter code + autograder workflow, which every generated repo inherits. Students
never use a CLI. Idempotent: existing repos are left alone.

    course/<template>  (private, is_template)
            |  generate (native)
            v
    cohort/<slug>-<handle>   (private; student = collaborator)
    where <slug> is the template name minus a trailing -fYYYY / -sYYYY.

Usage:
    python3 -m dsl_course.assign \\
        --master-org TEST-HERTIE-COURSE --template assignment-1-f2026 \\
        --cohort-org TEST-HERTIE-COHORT-f2026
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from . import roster
from .utils import (
    add_collaborator,
    generate_from_template,
    gh,
    git,
    log,
    log_err,
    log_ok,
    log_skip,
    log_step,
    repo_exists,
    set_repo_topics,
)

SOLUTION_BRANCH = "solution"
SOLUTION_DIR = "solution"
_GIT_ENV = [
    "-c",
    "user.email=bot@dsl.local",
    "-c",
    "user.name=dsl-bot",
    "-c",
    "core.hooksPath=/dev/null",
]


def assignment_slug(template: str) -> str:
    """assignment-1-f2026 -> assignment-1 (drop a trailing cohort suffix)."""
    return re.sub(r"-[fs]\d{4}$", "", template)


def fetch_solution(master_org: str, template: str, dest: Path) -> Path | None:
    """Clone the template's `solution` branch and return its solution/ dir, or None.

    Solutions live on a non-default branch so native template-generate (default branch
    only) never copies them into student repos - they're pushed separately, on demand."""
    code, _ = gh(
        "repo",
        "clone",
        f"{master_org}/{template}",
        str(dest),
        "--",
        "-q",
        "-b",
        SOLUTION_BRANCH,
    )
    if code != 0:
        log_err(
            f"  ! no `{SOLUTION_BRANCH}` branch on {master_org}/{template} - "
            f"nothing to push (add the solution there first)"
        )
        return None
    sol = dest / SOLUTION_DIR
    return sol if sol.is_dir() else None


def push_solution(cohort_org: str, repo: str, sol_dir: Path) -> bool:
    """Push the solution/ folder into an existing student repo (idempotent overwrite)."""
    with tempfile.TemporaryDirectory() as work:
        wd = Path(work) / "r"
        if gh("repo", "clone", f"{cohort_org}/{repo}", str(wd), "--", "-q")[0] != 0:
            return False
        shutil.copytree(sol_dir, wd / SOLUTION_DIR, dirs_exist_ok=True)
        git("-C", str(wd), *_GIT_ENV, "add", "-A")
        code, _ = git(
            "-C",
            str(wd),
            *_GIT_ENV,
            "commit",
            "-q",
            "--no-verify",
            "-m",
            "add solution",
        )
        if code != 0:
            return True  # already present, nothing new
        return git("-C", str(wd), *_GIT_ENV, "push", "-q", "origin", "HEAD")[0] == 0


def provision_one(
    master_org: str,
    template: str,
    cohort_org: str,
    repo: str,
    handle: str,
    slug: str,
    sol_dir: Path | None = None,
) -> str:
    existed = repo_exists(cohort_org, repo)
    if existed:
        log_skip(f"repo {cohort_org}/{repo}")
    elif not generate_from_template(
        template_org=master_org,
        template_name=template,
        owner=cohort_org,
        name=repo,
        private=True,
        description=f"{slug} - submission repo",
    ):
        return "failed-create"
    else:
        log_ok(f"created {cohort_org}/{repo}")
        set_repo_topics(cohort_org, repo, [slug, "submission"])

    if sol_dir is not None:
        if push_solution(cohort_org, repo, sol_dir):
            log_ok("  + solution pushed")
        else:
            log_err("  ! could not push solution")

    if add_collaborator(cohort_org, repo, handle, permission="maintain"):
        log_ok(f"  + @{handle} (maintain)")
        return "skipped" if existed else "ok"
    log_err(f"  ! could not add @{handle} (not a real account?)")
    return "created-no-collaborator"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--master-org", required=True, help="Course org (template source)"
    )
    parser.add_argument(
        "--template",
        required=True,
        help="Assignment template repo (e.g. assignment-1-f2026)",
    )
    parser.add_argument("--cohort-org", required=True, help="Cohort org (target)")
    parser.add_argument(
        "--roster",
        default=None,
        help="Local students.csv (default: cohort classroom-config)",
    )
    parser.add_argument(
        "--solution",
        action="store_true",
        help="Also push the solution (template's `solution` branch) into each student repo",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.master_org == args.cohort_org:
        log_err("--master-org and --cohort-org must differ.")
        return 1

    students = (
        roster.load_path(args.roster) if args.roster else roster.load(args.cohort_org)
    )
    if not students:
        return 1
    onboarded = [s for s in students if s.onboarded]
    skipped = len(students) - len(onboarded)
    slug = assignment_slug(args.template)
    log_step(
        f"Provisioning {slug} for {len(onboarded)} onboarded student(s) -> "
        f"{args.cohort_org} (template {args.master_org}/{args.template})"
        f"{' + solution' if args.solution else ''}"
    )
    if skipped:
        log(f"  ({skipped} not-yet-onboarded row(s) skipped)")

    if args.dry_run:
        for s in onboarded:
            log(
                f"    DRY-RUN  {args.cohort_org}/{slug}-{s.github_handle}  <- @{s.github_handle}"
            )
        return 0

    with tempfile.TemporaryDirectory() as soldir:
        sol_dir = None
        if args.solution:
            sol_dir = fetch_solution(args.master_org, args.template, Path(soldir) / "t")
            if sol_dir is None:
                return 1

        results: dict[str, int] = {}
        for s in onboarded:
            repo = f"{slug}-{s.github_handle}"
            log_step(repo)
            status = provision_one(
                args.master_org,
                args.template,
                args.cohort_org,
                repo,
                s.github_handle,
                slug,
                sol_dir,
            )
            results[status] = results.get(status, 0) + 1

    log_ok(f"Done - {json.dumps(results)}")
    return 1 if any(k.startswith("failed") for k in results) else 0


if __name__ == "__main__":
    sys.exit(main())
