"""dsl-course release -- publish one session's content from a course repo to a cohort
repo.

Run from inside a course content repo (materials-f2026): that repo is the SOURCE.
Copies one session's content, from every discovered section, into a chosen repo in a
cohort org (private repo + `students` team read). Only the released sessions appear,
so "each session opens up". Git-clone based so binary PDFs copy intact.

Source layout: any top-level directory containing at least one ordinal-prefixed
subdirectory is a releasable "section" - no config to declare it, the directory
structure is the only contract:
    <section>/<NN>_<free text>/...      e.g. lectures/00_intro/, labs/03_regression/

    course/<source-repo>   (private)
            |  copy session N from every discovered section (minus --exclude)
            v
    cohort/<cohort-repo>   (private + students read)

Usage:
    python3 -m dsl_course.release \\
        --source-org TEST-HERTIE-COURSE --source-repo materials-f2026 \\
        --cohort-org TEST-HERTIE-COHORT-f2026 --cohort-repo materials \\
        --session 1
    # add --exclude readings (space/comma separated) to skip one or more sections
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from .utils import (
    GIT_ENV,
    create_repo,
    discover_sections,
    find_session_dir,
    gh,
    git,
    log,
    log_err,
    log_ok,
    log_step,
)

_GIT_ENV = GIT_ENV


def grant_students_read(cohort_org: str, repo: str) -> None:
    code, _ = gh(
        "api",
        "--method",
        "PUT",
        f"orgs/{cohort_org}/teams/students/repos/{cohort_org}/{repo}",
        "--field",
        "permission=pull",
    )
    if code == 0:
        log_ok("students team -> read")
    else:
        log("  (students team not found - create it first)")


def _syllabus_files(root: Path) -> list[Path]:
    """Root-level syllabus file(s), matched case-insensitively so SYLLABUS.md,
    Syllabus.md, syllabus.txt, course-syllabus.pdf, ... all release. Sorted so the
    order is deterministic when more than one matches."""
    if not root.is_dir():
        return []
    return sorted(
        f for f in root.iterdir() if f.is_file() and "syllabus" in f.name.lower()
    )


def release(
    source_org: str,
    source_repo: str,
    cohort_org: str,
    cohort_repo: str,
    session: str,
    exclude: set[str] | None = None,
    include_syllabus: bool = False,
    include_readme: bool = False,
) -> int:
    log_step(
        f"Releasing session {session} from {source_org}/{source_repo} "
        f"-> {cohort_org}/{cohort_repo} (cohort-private)"
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

        wanted = [s for s in discover_sections(src) if s not in (exclude or set())]
        if not (wanted or include_syllabus or include_readme):
            log_err("nothing to release - no sections found, and everything else was switched off.")
            return 1

        copied = 0
        for section in wanted:
            sdir = find_session_dir(src / section, session)
            if sdir is None:
                log(f"  (no {section}/{session}_* in source - skipped)")
                continue
            shutil.copytree(sdir, out / section / sdir.name, dirs_exist_ok=True)
            log_ok(f"+ {section}/{sdir.name}")
            copied += 1

        # Optional root files (default off): syllabus + README, deployed to the cohort
        # root, overwriting whatever is there.
        if include_syllabus:
            for f in _syllabus_files(src):
                shutil.copy2(f, out / f.name)
                log_ok(f"+ {f.name}")
                copied += 1
        readme_from_source = False
        if include_readme and (src / "README.md").is_file():
            shutil.copy2(src / "README.md", out / "README.md")
            log_ok("+ README.md (from source)")
            readme_from_source = True
            copied += 1

        if copied == 0:
            log_err(
                f"nothing matched for session {session} in {source_org}/{source_repo} "
                f"(expected e.g. lectures/{session}_.../). Nothing released."
            )
            return 1

        if not readme_from_source:
            (out / "README.md").write_text(
                f"# {cohort_repo}\n\n"
                f"Released from `{source_org}/{source_repo}` - **enrolled students only**.\n\n"
                f"Sessions open up as the course progresses.\n"
            )

        git("-C", str(out), *_GIT_ENV, "add", "-A")
        code, _ = git(
            "-C",
            str(out),
            *_GIT_ENV,
            "commit",
            "-q",
            "--no-verify",
            "-m",
            f"release: session {session}",
        )
        if code != 0:
            log_ok("nothing new to release (session already published)")
            return 0
        if git("-C", str(out), *_GIT_ENV, "push", "-q", "origin", "HEAD")[0] != 0:
            log_err("push failed")
            return 1
    log_ok("released")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-org", required=True, help="Course org (source)")
    parser.add_argument(
        "--source-repo", required=True, help="Content repo name (source)"
    )
    parser.add_argument("--cohort-org", required=True, help="Cohort org (target)")
    parser.add_argument(
        "--cohort-repo", required=True, help="Target repo in the cohort org"
    )
    parser.add_argument("--session", required=True, help="Session number, e.g. 1")
    parser.add_argument(
        "--exclude",
        default="",
        help="Space/comma-separated section names to skip (e.g. 'readings')",
    )
    parser.add_argument(
        "--syllabus", action="store_true", help="Also copy root *syllabus* file(s)"
    )
    parser.add_argument(
        "--readme", action="store_true", help="Also copy the source root README.md"
    )
    args = parser.parse_args()

    if (args.source_org, args.source_repo) == (args.cohort_org, args.cohort_repo):
        log_err("source and target must differ.")
        return 1
    exclude = {s for s in args.exclude.replace(",", " ").split() if s}
    rc = release(
        args.source_org,
        args.source_repo,
        args.cohort_org,
        args.cohort_repo,
        args.session,
        exclude=exclude,
        include_syllabus=args.syllabus,
        include_readme=args.readme,
    )
    if rc == 0:
        from . import site

        site.sync_site(args.source_org, args.cohort_org)
    return rc


if __name__ == "__main__":
    sys.exit(main())
