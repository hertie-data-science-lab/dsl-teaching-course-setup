"""dsl-course release-code -- publish a package path (subpackage or module) to a cohort.

Phased disclosure of a growing importable package. Where `release` copies a whole
`lectures/<NN>_.../` folder, this copies a chosen PATH from a source repo into the cohort's
package tree, additively + idempotently:

    source/<repo>/mlpkg/simulation/      (a subpackage folder - the default granularity)
    source/<repo>/mlpkg/training/warmup.py   (a single module - per-module when needed)
            |  copy that path
            v
    cohort/<cohort-repo>/<same path>     (private + students read; accumulates over sessions)

Granularity is just the path you pick. The package must tolerate unreleased modules (no
eager `from . import <future_submodule>` in `__init__`) so a partial release still
imports - release `core/` early to hold the shared base.

Usage:
    python3 -m dsl_course.release_code \\
        --source-org COURSE --source-repo lecture-code \\
        --cohort-org COHORT --cohort-repo materials \\
        --path mlpkg/simulation
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from .release import grant_students_read
from .utils import GIT_ENV, create_repo, gh, git, log_err, log_ok, log_step

_GIT_ENV = GIT_ENV


def release_code(
    source_org: str,
    source_repo: str,
    cohort_org: str,
    cohort_repo: str,
    path: str,
    dest_path: str | None = None,
    sync: bool = True,
) -> int:
    """Copy `path` from the course-org source repo into the cohort-org `cohort_repo`,
    additively + idempotently. `dest_path` places it at a different path in the dest
    (default: mirror `path`). `sync` triggers a website sync afterwards (the scheduler
    passes sync=False and syncs once after all its releases)."""
    path = path.strip("/")
    if not path:
        log_err("--path is empty.")
        return 1
    dest = (dest_path or path).strip("/") or path

    log_step(
        f"Releasing `{path}` from {source_org}/{source_repo} "
        f"-> {cohort_org}/{cohort_repo}/{dest} (cohort-private)"
    )
    create_repo(
        cohort_org,
        cohort_repo,
        private=True,
        description="Released course materials (enrolled students only)",
    )
    grant_students_read(cohort_org, cohort_repo)

    with tempfile.TemporaryDirectory() as work:
        src, out = Path(work) / "src", Path(work) / "out"
        if (
            gh("repo", "clone", f"{source_org}/{source_repo}", str(src), "--", "-q")[0]
            != 0
        ):
            log_err(f"could not clone {source_org}/{source_repo}")
            return 1
        if (
            gh("repo", "clone", f"{cohort_org}/{cohort_repo}", str(out), "--", "-q")[0]
            != 0
        ):
            log_err(f"could not clone {cohort_org}/{cohort_repo}")
            return 1

        srcp = src / path
        if not srcp.exists():
            log_err(
                f"`{path}` not found in {source_org}/{source_repo} - nothing released."
            )
            return 1

        destp = out / dest
        if srcp.is_dir():
            shutil.copytree(srcp, destp, dirs_exist_ok=True)
        else:
            destp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(srcp, destp)
        log_ok(f"+ {dest}")

        git("-C", str(out), *_GIT_ENV, "add", "-A")
        code, _ = git(
            "-C",
            str(out),
            *_GIT_ENV,
            "commit",
            "-q",
            "--no-verify",
            "-m",
            f"release: {dest}",
        )
        if code != 0:
            log_ok("nothing new to release (already published at this path)")
            return 0
        if git("-C", str(out), *_GIT_ENV, "push", "-q", "origin", "HEAD")[0] != 0:
            log_err("push failed")
            return 1
    log_ok("released")
    if sync:
        from . import site

        site.sync_site(source_org, cohort_org)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-org", required=True, help="Course org (source)")
    parser.add_argument(
        "--source-repo", required=True, help="Source repo holding the package"
    )
    parser.add_argument("--cohort-org", required=True, help="Cohort org (target)")
    parser.add_argument(
        "--cohort-repo", required=True, help="Target repo in the cohort org"
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Source path to release (folder or file)",
    )
    parser.add_argument(
        "--dest-path",
        default=None,
        help="Destination path in the cohort repo (default: mirror --path)",
    )
    args = parser.parse_args()

    if (args.source_org, args.source_repo) == (args.cohort_org, args.cohort_repo):
        log_err("source and target must differ.")
        return 1
    return release_code(
        args.source_org,
        args.source_repo,
        args.cohort_org,
        args.cohort_repo,
        args.path,
        dest_path=args.dest_path,
    )


if __name__ == "__main__":
    sys.exit(main())
