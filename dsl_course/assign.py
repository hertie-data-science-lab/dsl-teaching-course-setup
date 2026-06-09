"""dsl-course assign -- provision per-student assignment repos from a content folder.

Run from a content repo (the SOURCE). Copies one assignment folder
(`assignments/<assignment>/`) into a fresh PRIVATE repo per onboarded student in the
cohort org, and adds the student as a collaborator (maintain). Students never use a
CLI. Idempotent: existing repos are left alone; collaborator access is re-ensured.

    course/<source-repo>/assignments/<assignment>/   (private)
            │  copy per onboarded student
            ▼
    cohort/<assignment>-<handle>                      (private; student = collaborator)

Usage:
    python3 -m dsl_course.assign \\
        --source-org TEST-HERTIE-COURSE --source-repo content-f2026 \\
        --assignment assignment-1 --cohort-org TEST-HERTIE-COHORT-f2026
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from . import roster
from .utils import (
    add_collaborator,
    create_repo,
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

_GIT_ENV = [
    "-c",
    "user.email=bot@dsl.local",
    "-c",
    "user.name=dsl-bot",
    "-c",
    "core.hooksPath=/dev/null",
]


def _is_empty(org: str, repo: str) -> bool:
    """True if the repo has no commits yet (so seeding it won't clobber any work)."""
    code, out = gh("api", f"repos/{org}/{repo}/branches", "--jq", "length")
    return code == 0 and out.strip() == "0"


def _seed_repo_from_dir(
    src_dir: Path, cohort_org: str, repo: str, assignment: str
) -> bool:
    """Push the contents of src_dir as the initial commit of cohort_org/repo."""
    with tempfile.TemporaryDirectory() as work:
        out = Path(work) / "r"
        if gh("repo", "clone", f"{cohort_org}/{repo}", str(out), "--", "-q")[0] != 0:
            log_err(f"  could not clone {cohort_org}/{repo}")
            return False
        for item in src_dir.iterdir():
            dest = out / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        git("-C", str(out), *_GIT_ENV, "add", "-A")
        code, _ = git(
            "-C",
            str(out),
            *_GIT_ENV,
            "commit",
            "-q",
            "--no-verify",
            "-m",
            f"init: {assignment}",
        )
        if code != 0:
            return True  # nothing to commit (repo already populated)
        return git("-C", str(out), *_GIT_ENV, "push", "-q", "origin", "HEAD")[0] == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-org", required=True, help="Course org (source)")
    parser.add_argument(
        "--source-repo", required=True, help="Content repo name (source)"
    )
    parser.add_argument(
        "--assignment",
        required=True,
        help="Assignment folder under assignments/ (e.g. assignment-1)",
    )
    parser.add_argument("--cohort-org", required=True, help="Cohort org (target)")
    parser.add_argument(
        "--roster",
        default=None,
        help="Local students.csv (default: cohort classroom-config)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.source_org == args.cohort_org:
        log_err("--source-org and --cohort-org must differ.")
        return 1

    students = (
        roster.load_path(args.roster) if args.roster else roster.load(args.cohort_org)
    )
    if not students:
        return 1
    onboarded = [s for s in students if s.onboarded]
    skipped = len(students) - len(onboarded)
    log_step(
        f"Provisioning {args.assignment} for {len(onboarded)} onboarded student(s) "
        f"-> {args.cohort_org} (from {args.source_org}/{args.source_repo})"
    )
    if skipped:
        log(f"  ({skipped} not-yet-onboarded row(s) skipped)")

    if args.dry_run:
        for s in onboarded:
            log(
                f"    DRY-RUN  {args.cohort_org}/{args.assignment}-{s.github_handle}  <- @{s.github_handle}"
            )
        return 0

    with tempfile.TemporaryDirectory() as work:
        src = Path(work) / "src"
        if (
            gh(
                "repo",
                "clone",
                f"{args.source_org}/{args.source_repo}",
                str(src),
                "--",
                "-q",
            )[0]
            != 0
        ):
            log_err(f"could not clone {args.source_org}/{args.source_repo}")
            return 1
        adir = src / "assignments" / args.assignment
        if not adir.is_dir():
            log_err(
                f"no assignments/{args.assignment} folder in {args.source_org}/{args.source_repo}"
            )
            return 1

        results: dict[str, int] = {}
        for s in onboarded:
            repo = f"{args.assignment}-{s.github_handle}"
            log_step(repo)
            existed = repo_exists(args.cohort_org, repo)
            if not existed:
                if not create_repo(
                    args.cohort_org,
                    repo,
                    private=True,
                    description=f"{args.assignment} — submission repo",
                ):
                    results["failed-create"] = results.get("failed-create", 0) + 1
                    continue
                set_repo_topics(args.cohort_org, repo, [args.assignment, "submission"])
            # Seed only a new or still-empty repo — never overwrite a student's work.
            if (not existed) or _is_empty(args.cohort_org, repo):
                if not _seed_repo_from_dir(
                    adir, args.cohort_org, repo, args.assignment
                ):
                    log_err(f"  ! could not seed {repo} from the assignment folder")
            else:
                log_skip(f"repo {args.cohort_org}/{repo}")
            status = "skipped" if existed else "ok"
            if add_collaborator(
                args.cohort_org, repo, s.github_handle, permission="maintain"
            ):
                log_ok(f"  + @{s.github_handle} (maintain)")
            else:
                log_err(f"  ! could not add @{s.github_handle} (not a real account?)")
                status = "created-no-collaborator"
            results[status] = results.get(status, 0) + 1

    log_ok(f"Done — {json.dumps(results)}")
    return 1 if any(k.startswith("failed") for k in results) else 0


if __name__ == "__main__":
    sys.exit(main())
