"""dsl-course release-code -- publish a path (folder or file) from a course-org source
repo into a cohort-org repo, additively + idempotently:

    source/<repo>/<source_path>          (a folder - e.g. lectures/02_intro - or a file)
            |  copy that path
            v
    cohort/<dest_repo>/<dest_path>       (private + students read; accumulates over time)

`deploy_many` is the batch core: it clones each unique source repo and each unique dest
repo ONCE per run and applies every copy against those working trees, so a scheduler run
releasing 27 paths from one source clones it once, not 27 times. `release_code` is the
single-path wrapper the manual "Release code" button uses.

Usage:
    python3 -m dsl_course.release_code \\
        --source-org COURSE --source-repo lecture-code \\
        --cohort-org COHORT --cohort-repo materials \\
        --path mlpkg/simulation [--dest-path pkg/simulation]
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from .release import grant_students_read
from .schedule import Deploy
from .utils import GIT_ENV, create_repo, gh, git, log, log_err, log_ok, log_step

_GIT_ENV = GIT_ENV


def deploy_many(
    source_org: str,
    cohort_org: str,
    deploys: list[Deploy],
    sync: bool = True,
) -> tuple[int, bool]:
    """Apply a batch of Deploy copies, cloning each unique source and dest repo ONCE.

    Every deploy's `source_path` is copied from its (course-org) `source_repo` into its
    (cohort-org) `dest_repo` at `dest_path` (default: mirror `source_path`). Each touched
    dest repo gets a single commit+push covering all its copies; a dest with no net change
    is left alone (idempotent). Returns `(errors, changed)` - `errors` counts copies that
    could not be applied, `changed` is True if anything was actually pushed. `sync` runs a
    single website sync at the end when `changed` (callers batching several release kinds
    pass sync=False and sync once themselves)."""
    deploys = [d for d in deploys if d]
    if not deploys:
        return 0, False

    errors = 0
    changed = False
    with tempfile.TemporaryDirectory() as work:
        root = Path(work)

        # 1. clone each unique source repo once (course org)
        src_dirs: dict[str, Path] = {}
        for repo in sorted({d.source_repo for d in deploys}):
            sd = root / "src" / repo
            if gh("repo", "clone", f"{source_org}/{repo}", str(sd), "--", "-q")[0] != 0:
                log_err(f"could not clone source {source_org}/{repo}")
                # every copy from this source is now impossible
                errors += sum(1 for d in deploys if d.source_repo == repo)
            else:
                src_dirs[repo] = sd

        # 2. clone (create if needed) each unique dest repo once (cohort org)
        dest_dirs: dict[str, Path] = {}
        for repo in sorted({d.dest_repo for d in deploys}):
            create_repo(
                cohort_org,
                repo,
                private=True,
                description="Released course materials (enrolled students only)",
            )
            grant_students_read(cohort_org, repo)
            dd = root / "out" / repo
            if gh("repo", "clone", f"{cohort_org}/{repo}", str(dd), "--", "-q")[0] != 0:
                log_err(f"could not clone dest {cohort_org}/{repo}")
                errors += sum(1 for d in deploys if d.dest_repo == repo)
            else:
                dest_dirs[repo] = dd

        # 3. apply every copy against the already-cloned trees
        touched: set[str] = set()
        for d in deploys:
            if d.source_repo not in src_dirs or d.dest_repo not in dest_dirs:
                continue  # its source/dest failed to clone (already counted)
            src_path = d.source_path.strip("/")
            dest_path = (d.dest_path or d.source_path).strip("/") or src_path
            srcp = src_dirs[d.source_repo] / src_path
            if not srcp.exists():
                log_err(
                    f"`{src_path}` not found in {source_org}/{d.source_repo} - skipped."
                )
                errors += 1
                continue
            destp = dest_dirs[d.dest_repo] / dest_path
            if srcp.is_dir():
                shutil.copytree(srcp, destp, dirs_exist_ok=True)
            else:
                destp.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(srcp, destp)
            log_ok(f"+ {d.dest_repo}/{dest_path}")
            touched.add(d.dest_repo)

        # 4. one commit + push per touched dest (skip if it has no net change)
        for repo in sorted(touched):
            dd = dest_dirs[repo]
            git("-C", str(dd), *_GIT_ENV, "add", "-A")
            code, _ = git(
                "-C", str(dd), *_GIT_ENV, "commit", "-q", "--no-verify",
                "-m", f"release: sync materials into {repo}",
            )
            if code != 0:
                log_ok(f"  {repo}: nothing new to release")
                continue
            if git("-C", str(dd), *_GIT_ENV, "push", "-q", "origin", "HEAD")[0] != 0:
                log_err(f"  {repo}: push failed")
                errors += 1
                continue
            log_ok(f"  {repo}: released")
            changed = True

    if sync and changed:
        from . import site

        site.sync_site(source_org, cohort_org)
    return errors, changed


def release_code(
    source_org: str,
    source_repo: str,
    cohort_org: str,
    cohort_repo: str,
    path: str,
    dest_path: str | None = None,
    sync: bool = True,
) -> int:
    """Single-path deploy (the manual Release code button). Thin wrapper over
    `deploy_many`. `dest_path` defaults to mirror `path`; `sync` runs a website sync
    after (the scheduler batches via `deploy_many(sync=False)` and syncs once itself)."""
    path = path.strip("/")
    if not path:
        log_err("--path is empty.")
        return 1
    log_step(
        f"Releasing `{path}` from {source_org}/{source_repo} -> "
        f"{cohort_org}/{cohort_repo}/{(dest_path or path).strip('/')}"
    )
    errors, _ = deploy_many(
        source_org,
        cohort_org,
        [Deploy(source_repo, path, cohort_repo, dest_path)],
        sync=sync,
    )
    if errors:
        return 1
    log("done")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-org", required=True, help="Course org (source)")
    parser.add_argument(
        "--source-repo", required=True, help="Source repo holding the path"
    )
    parser.add_argument("--cohort-org", required=True, help="Cohort org (target)")
    parser.add_argument(
        "--cohort-repo", required=True, help="Target repo in the cohort org"
    )
    parser.add_argument(
        "--path", required=True, help="Source path to release (folder or file)"
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
