"""dsl-course release -- publish one week's content from a course repo to a cohort repo.

Run from inside a course content repo (e.g. content-f2026): that repo is the SOURCE.
Copies one week's lecture and/or reading files into a chosen repo in a cohort org
(private repo + `students` team read). Only the released weeks appear, so "each week
opens up". Git-clone based so binary PDFs copy intact.

Source layout (week N == session N):
    lectures/Session<N>_*            (lecture files)
    readings/required/session-<NN>/  (required readings, zero-padded)

    course/<source-repo>   (private)
            │  copy week N (lectures and/or readings)
            ▼
    cohort/<cohort-repo>   (private + students read)

Usage:
    python3 -m dsl_course.release \\
        --source-org TEST-HERTIE-COURSE --source-repo content-f2026 \\
        --cohort-org TEST-HERTIE-COHORT-f2026 --cohort-repo materials \\
        --week 1
    # add --no-lectures or --no-readings to release only one kind (default: both)
"""

from __future__ import annotations

import argparse
import glob
import shutil
import sys
import tempfile
from pathlib import Path

from .utils import create_repo, gh, git, log, log_err, log_ok, log_step


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


def release(
    source_org: str,
    source_repo: str,
    cohort_org: str,
    cohort_repo: str,
    week: str,
    include_lectures: bool = True,
    include_readings: bool = True,
) -> int:
    if not (include_lectures or include_readings):
        log_err("nothing to release - both --no-lectures and --no-readings were set.")
        return 1

    kinds = ("lectures " if include_lectures else "") + (
        "readings" if include_readings else ""
    )
    log_step(
        f"Releasing week {week} ({kinds.strip()}) from {source_org}/{source_repo} "
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

        copied = 0
        # Lectures: files named lectures/Session<week>_*
        if include_lectures:
            (out / "lectures").mkdir(exist_ok=True)
            for f in glob.glob(str(src / "lectures" / f"Session{week}_*")):
                shutil.copy2(f, out / "lectures")
                log_ok(f"+ lectures/{Path(f).name}")
                copied += 1
        # Readings: dir readings/required/session-<NN> (zero-padded when numeric)
        if include_readings:
            (out / "readings").mkdir(exist_ok=True)
            name = f"session-{int(week):02d}" if week.isdigit() else f"session-{week}"
            reading = src / "readings" / "required" / name
            if reading.is_dir():
                shutil.copytree(reading, out / "readings" / name, dirs_exist_ok=True)
                log_ok(f"+ readings/{name}")
                copied += 1

        # Fail loudly rather than push an empty "release" - usually a naming mismatch.
        if copied == 0:
            log_err(
                f"no files matched week {week} in {source_org}/{source_repo} "
                f"(expected lectures/Session{week}_* or readings/required/session-NN). "
                f"Nothing released - check the source repo's layout."
            )
            return 1

        (out / "README.md").write_text(
            f"# {cohort_repo}\n\n"
            f"Released from `{source_org}/{source_repo}` - **enrolled students only**.\n\n"
            f"Weeks open up as the course progresses.\n"
        )

        env = [
            "-c",
            "user.email=bot@dsl.local",
            "-c",
            "user.name=dsl-bot",
            "-c",
            "core.hooksPath=/dev/null",
        ]
        git("-C", str(out), *env, "add", "-A")
        code, _ = git(
            "-C",
            str(out),
            *env,
            "commit",
            "-q",
            "--no-verify",
            "-m",
            f"release: week {week} ({kinds.strip()}) from {source_repo}",
        )
        if code != 0:
            log_ok("nothing new to release (week already published)")
            return 0
        if git("-C", str(out), *env, "push", "-q", "origin", "HEAD")[0] != 0:
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
    parser.add_argument("--week", required=True, help="Week number, e.g. 1")
    parser.add_argument("--no-lectures", action="store_true", help="Skip lectures")
    parser.add_argument("--no-readings", action="store_true", help="Skip readings")
    args = parser.parse_args()

    if (args.source_org, args.source_repo) == (args.cohort_org, args.cohort_repo):
        log_err("source and target must differ.")
        return 1
    return release(
        args.source_org,
        args.source_repo,
        args.cohort_org,
        args.cohort_repo,
        args.week,
        include_lectures=not args.no_lectures,
        include_readings=not args.no_readings,
    )


if __name__ == "__main__":
    sys.exit(main())
