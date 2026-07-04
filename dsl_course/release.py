"""dsl-course release -- publish one or more sessions' content from a course repo to
one or more cohort repos.

Run from inside a course content repo (materials-f2026): that repo is the SOURCE.
Each discovered section is routed to a target repo (+ optional subpath within it),
created if it doesn't exist yet (private repo + `students` team read). Only the
released sessions appear, so "each session opens up". Git-clone based so binary PDFs
copy intact.

Source layout: any top-level directory containing at least one ordinal-prefixed
subdirectory is a releasable "section" - no config to declare it, the directory
structure is the only contract:
    <section>/<NN>_<free text>/...      e.g. lectures/00_intro/, labs/03_regression/

Each section is routed with --destinations "section=repo" or "section=repo/subpath"
(repo/subpath nests the section under a folder there, so several sections can share
one repo); any section not named there falls back to --default-repo (nested under a
folder named after the section) unless it's in --exclude. At least one of
--destinations/--default-repo must be given.

    course/<source-repo>   (private)
            |  copy session(s) N from every routed section
            v
    cohort/<repo-a>, cohort/<repo-b>, ...   (private + students read)

Usage:
    python3 -m dsl_course.release \\
        --source-org TEST-HERTIE-COURSE --source-repo materials-f2026 \\
        --cohort-org TEST-HERTIE-COHORT-f2026 \\
        --destinations "lectures=lectures,labs=materials/labs" \\
        --sessions 1,3,5-7
    # --sessions is comma/range (see utils.expand_int_spec) - every (repo, session)
    # combination is released in turn.
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
    expand_int_spec,
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


def parse_destinations(spec: str) -> dict[str, str]:
    """Parse "section=dest,section2=dest2" into {section: dest}. Each dest is a repo
    name (content released at that repo's root) or "repo/subpath" (nested under a
    folder there). Raises ValueError naming the exact bad pair for anything
    malformed."""
    destinations: dict[str, str] = {}
    for pair in spec.replace(",", " ").split():
        section, sep, dest = pair.partition("=")
        if not sep or not section or not dest:
            raise ValueError(f"'{pair}' is not 'section=destination'")
        destinations[section] = dest
    return destinations


def route_sections(
    sections: list[str],
    destinations: dict[str, str],
    default_repo: str | None,
    exclude: set[str],
) -> dict[str, list[tuple[str, str]]]:
    """Group `sections` by target repo: a section named in `destinations` goes exactly
    to its "repo" or "repo/subpath"; any other section falls back to `default_repo`
    (nested under a folder named after the section, so several sections can share one
    repo) unless it's in `exclude`. A section routed to neither is dropped."""
    by_repo: dict[str, list[tuple[str, str]]] = {}
    for section in sections:
        if section in destinations:
            repo, _, subpath = destinations[section].partition("/")
        elif default_repo and section not in exclude:
            repo, subpath = default_repo, section
        else:
            continue
        by_repo.setdefault(repo, []).append((section, subpath))
    return by_repo


def release(
    source_org: str,
    source_repo: str,
    cohort_org: str,
    session: str,
    destinations: dict[str, str] | None = None,
    default_repo: str | None = None,
    exclude: set[str] | None = None,
    include_syllabus: bool = False,
    include_readme: bool = False,
) -> int:
    """Release one session. Each section discovered in the source repo is routed to a
    target repo (+ optional subpath) via `route_sections`. Sections routed to nowhere
    are simply not released."""
    destinations = destinations or {}
    exclude = exclude or set()
    log_step(f"Releasing session {session} from {source_org}/{source_repo}")

    with tempfile.TemporaryDirectory() as work:
        src = Path(work) / "src"
        if (
            gh("repo", "clone", f"{source_org}/{source_repo}", str(src), "--", "-q")[0]
            != 0
        ):
            log_err(f"could not clone {source_org}/{source_repo}")
            return 1

        by_repo = route_sections(discover_sections(src), destinations, default_repo, exclude)

        # Syllabus/README have no section of their own - if requested, they still go
        # to default_repo (there's nowhere else for a central/blanket release to put
        # them); a per-section destinations-only release has no root repo to pick, so
        # they're skipped rather than guessing which of several repos should get them.
        if default_repo and (include_syllabus or include_readme):
            by_repo.setdefault(default_repo, [])

        if not by_repo:
            log_err("nothing to release - no section (or default-repo) routed to a target repo.")
            return 1

        errors = 0
        released_any = False
        for repo in sorted(by_repo):
            if (source_org, source_repo) == (cohort_org, repo):
                log_err(f"source and target must differ (skipping {repo}).")
                errors += 1
                continue

            create_repo(
                cohort_org,
                repo,
                private=True,
                description="Released course materials (enrolled students only)",
            )
            grant_students_read(cohort_org, repo)

            out = Path(work) / f"out-{repo}"
            if gh("repo", "clone", f"{cohort_org}/{repo}", str(out), "--", "-q")[0] != 0:
                log_err(f"could not clone {cohort_org}/{repo}")
                errors += 1
                continue

            copied = 0
            for section, subpath in by_repo[repo]:
                sdir = find_session_dir(src / section, session)
                if sdir is None:
                    log(f"  (no {section}/{session}_* in source - skipped)")
                    continue
                dest_dir = (out / subpath) if subpath else out
                shutil.copytree(sdir, dest_dir / sdir.name, dirs_exist_ok=True)
                log_ok(f"+ {repo}: {subpath + '/' if subpath else ''}{sdir.name}")
                copied += 1

            if repo == default_repo and include_syllabus:
                for f in _syllabus_files(src):
                    shutil.copy2(f, out / f.name)
                    log_ok(f"+ {repo}: {f.name}")
                    copied += 1
            readme_from_source = False
            if repo == default_repo and include_readme and (src / "README.md").is_file():
                shutil.copy2(src / "README.md", out / "README.md")
                log_ok(f"+ {repo}: README.md (from source)")
                readme_from_source = True
                copied += 1

            if copied == 0:
                log(f"  (nothing matched for {repo} this session - skipped)")
                continue

            if not readme_from_source:
                (out / "README.md").write_text(
                    f"# {repo}\n\n"
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
                log_ok(f"{repo}: nothing new to release (already published)")
                released_any = True
                continue
            if git("-C", str(out), *_GIT_ENV, "push", "-q", "origin", "HEAD")[0] != 0:
                log_err(f"push failed for {repo}")
                errors += 1
                continue
            log_ok(f"released to {repo}")
            released_any = True

    if not released_any:
        log_err(
            f"nothing matched for session {session} in {source_org}/{source_repo} "
            f"(expected e.g. <section>/{session}_.../). Nothing released."
        )
        return 1
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-org", required=True, help="Course org (source)")
    parser.add_argument(
        "--source-repo", required=True, help="Content repo name (source)"
    )
    parser.add_argument("--cohort-org", required=True, help="Cohort org (target)")
    parser.add_argument(
        "--destinations",
        default="",
        help="Comma/space-separated section=destination pairs, e.g. "
        "'lectures=lectures,labs=materials/labs'",
    )
    parser.add_argument(
        "--default-repo",
        default="",
        help="Fallback target repo for any discovered section not named in "
        "--destinations (nested under a folder named after the section)",
    )
    parser.add_argument(
        "--exclude",
        default="",
        help="Space/comma-separated section names to skip when relying on "
        "--default-repo",
    )
    parser.add_argument(
        "--sessions",
        required=True,
        help="Comma/range list of session numbers, e.g. '1,3,5-7'",
    )
    parser.add_argument(
        "--syllabus", action="store_true", help="Also copy root *syllabus* file(s)"
    )
    parser.add_argument(
        "--readme", action="store_true", help="Also copy the source root README.md"
    )
    args = parser.parse_args()

    try:
        destinations = parse_destinations(args.destinations) if args.destinations.strip() else {}
    except ValueError as e:
        log_err(f"--destinations: {e}")
        return 1
    default_repo = args.default_repo.strip() or None
    if not destinations and not default_repo:
        log_err("no target given - pass --destinations and/or --default-repo.")
        return 1
    try:
        sessions = [str(n) for n in expand_int_spec(args.sessions)]
    except ValueError as e:
        log_err(f"--sessions: {e}")
        return 1
    exclude = {s for s in args.exclude.replace(",", " ").split() if s}

    errors = 0
    released = False
    for session in sessions:
        rc = release(
            args.source_org,
            args.source_repo,
            args.cohort_org,
            session,
            destinations=destinations,
            default_repo=default_repo,
            exclude=exclude,
            include_syllabus=args.syllabus,
            include_readme=args.readme,
        )
        if rc == 0:
            released = True
        else:
            errors += 1

    if released:
        from . import site

        site.sync_site(args.source_org, args.cohort_org)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
