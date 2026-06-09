"""dsl-course release -- drip materials from the master into the cohort.

Copies selected sessions' lecture + required-reading files from the PRIVATE master
content repo into a COHORT-PRIVATE `materials` repo (private repo + `students` team
read). Run per release / weekly — only the released sessions appear, so "each week
opens up". The master is the source of truth; the cohort gets a projection.

Git-clone based (not the Contents API) so binary PDFs copy intact.

    master content   Hertie-School-{Course}-{Code}/content-*   (private)
            │  copy released sessions
            ▼
    cohort           {Course}-f{YYYY}/materials                 (private + students read)

Usage:
    python3 -m dsl_course.release \\
        --master-org Hertie-School-Deep-Learning-EXAMPLE \\
        --content-repo content-f2025 \\
        --cohort-org Deep-Learning-EXAMPLE-f2026 \\
        --sessions 1 2 3
"""

from __future__ import annotations

import argparse
import glob
import shutil
import sys
import tempfile
from pathlib import Path

from .utils import create_repo, gh, git, log, log_err, log_ok, log_step

MATERIALS = "materials"


def grant_students_read(cohort_org: str) -> None:
    code, _ = gh(
        "api",
        "--method",
        "PUT",
        f"orgs/{cohort_org}/teams/students/repos/{cohort_org}/{MATERIALS}",
        "--field",
        "permission=pull",
    )
    if code == 0:
        log_ok("students team -> read")
    else:
        log("  (students team not found — create it first)")


def release(
    master_org: str, content_repo: str, cohort_org: str, sessions: list[str]
) -> int:
    log_step(
        f"Releasing sessions {sessions} from {master_org}/{content_repo} "
        f"-> {cohort_org}/{MATERIALS} (cohort-private)"
    )
    create_repo(
        cohort_org,
        MATERIALS,
        private=True,
        description="Released course materials (enrolled students only)",
    )
    grant_students_read(cohort_org)

    with tempfile.TemporaryDirectory() as work:
        src, out = Path(work) / "src", Path(work) / "out"
        if (
            gh("repo", "clone", f"{master_org}/{content_repo}", str(src), "--", "-q")[0]
            != 0
        ):
            log_err(f"could not clone {master_org}/{content_repo}")
            return 1
        if (
            gh("repo", "clone", f"{cohort_org}/{MATERIALS}", str(out), "--", "-q")[0]
            != 0
        ):
            log_err(f"could not clone {cohort_org}/{MATERIALS}")
            return 1

        (out / "lectures").mkdir(exist_ok=True)
        (out / "readings").mkdir(exist_ok=True)
        for s in sessions:
            for f in glob.glob(str(src / "lectures" / f"Session{s}_*")):
                shutil.copy2(f, out / "lectures")
                log_ok(f"+ lectures/Session{s}")
            reading = src / "readings" / "required" / f"session-{int(s):02d}"
            if reading.is_dir():
                shutil.copytree(
                    reading, out / "readings" / reading.name, dirs_exist_ok=True
                )
                log_ok(f"+ readings/{reading.name}")

        (out / "README.md").write_text(
            f"# Materials — released\n\n"
            f"Released from the master (`{master_org}/{content_repo}`) — "
            f"**enrolled students only**.\n\n"
            f"Released sessions: **{' '.join(sessions)}**. More open up each week.\n"
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
            f"release: sessions {' '.join(sessions)}",
        )
        if code != 0:
            log_ok("nothing new to release")
            return 0
        if git("-C", str(out), "push", "-q", "origin", "HEAD")[0] != 0:
            log_err("push failed")
            return 1
    log_ok("released")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-org", required=True)
    parser.add_argument(
        "--content-repo", required=True, help="Content repo name in the master org"
    )
    parser.add_argument("--cohort-org", required=True)
    parser.add_argument(
        "--sessions", required=True, nargs="+", help="Session numbers, e.g. 1 2 3"
    )
    args = parser.parse_args()
    return release(args.master_org, args.content_repo, args.cohort_org, args.sessions)


if __name__ == "__main__":
    sys.exit(main())
