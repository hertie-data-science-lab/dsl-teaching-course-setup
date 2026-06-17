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

With --group it instead makes ONE repo per team, `cohort/<slug>-<team>`, adding every
member (from classroom-config/teams.csv, keyed on <slug>) as a collaborator - for group
projects. Grades are never written here; they go to each student's private gradebook repo
(see dsl_course.grades), so a possibly-public team repo never carries marks.

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

from . import roster, teams
from .utils import (
    GIT_ENV,
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
_GIT_ENV = GIT_ENV


def assignment_slug(template: str) -> str:
    """assignment-1-f2026 -> assignment-1 (drop a trailing cohort suffix)."""
    return re.sub(r"-[fs]\d{4}$", "", template)


def ensure_cohort_template(
    master_org: str, template: str, cohort_org: str, slug: str
) -> str | None:
    """Stage 1: freeze a cohort-level template repo (named `<slug>`) from the course
    template, so the cohort has its own copy and per-student repos generate from it
    (the role Classroom 50's classroom template used to play). Returns the cohort
    template name, or None on failure. Idempotent."""
    if repo_exists(cohort_org, slug):
        log_skip(f"cohort template {cohort_org}/{slug}")
        return slug
    if not generate_from_template(
        template_org=master_org,
        template_name=template,
        owner=cohort_org,
        name=slug,
        private=True,
        description=f"{slug} - cohort assignment template",
    ):
        return None
    log_ok(f"created cohort template {cohort_org}/{slug}")
    gh(
        "api",
        "--method",
        "PATCH",
        f"repos/{cohort_org}/{slug}",
        "-F",
        "is_template=true",
    )
    set_repo_topics(cohort_org, slug, [slug, "assignment-template"])
    return slug


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
    handles: list[str],
    slug: str,
    sol_dir: Path | None = None,
) -> str:
    """Generate one submission repo and add every `handles` member as a collaborator.

    Individual assignments pass a single-element list (a team of one); group assignments
    pass the whole team, so all members share the one repo."""
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

    added = 0
    for handle in handles:
        if add_collaborator(cohort_org, repo, handle, permission="maintain"):
            log_ok(f"  + @{handle} (maintain)")
            added += 1
        else:
            log_err(f"  ! could not add @{handle} (not a real account?)")
    if added == 0:
        return "created-no-collaborator"
    return "skipped" if existed else "ok"


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
    parser.add_argument(
        "--group",
        action="store_true",
        help="Group assignment: one repo per team (from classroom-config/teams.csv), "
        "all members as collaborators, instead of one per student.",
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

    # A provisioning unit is (repo_name, [member handles]). Individual = one per student
    # (a team of one); group = one per team from teams.csv, keyed on this assignment slug.
    if args.group:
        groups = teams.teams_for(teams.load(args.cohort_org), slug)
        if not groups:
            log_err(
                f"no teams for `{slug}` in {args.cohort_org}/classroom-config/teams.csv - "
                f"students self-select via the welcome 'Join team' issue, or seed the CSV."
            )
            return 1
        units = [
            (f"{slug}-{team}", members) for team, members in sorted(groups.items())
        ]
        what = f"{len(units)} team(s)"
    else:
        units = [(f"{slug}-{s.github_handle}", [s.github_handle]) for s in onboarded]
        what = f"{len(units)} student(s)"

    log_step(
        f"Releasing {slug} to {args.cohort_org}: freeze cohort template, then provision "
        f"{what}{' + solution' if args.solution else ''}"
    )
    if skipped:
        log(f"  ({skipped} not-yet-onboarded row(s) skipped)")

    if args.dry_run:
        log(f"    DRY-RUN  cohort template {args.cohort_org}/{slug}")
        for repo, handles in units:
            log(
                f"    DRY-RUN  {args.cohort_org}/{repo}  <- {', '.join('@' + h for h in handles)}"
            )
        return 0

    # Stage 1: freeze the cohort-level template.
    cohort_template = ensure_cohort_template(
        args.master_org, args.template, args.cohort_org, slug
    )
    if cohort_template is None:
        log_err("could not create the cohort assignment template.")
        return 1

    with tempfile.TemporaryDirectory() as soldir:
        # Solution still comes from the COURSE template's solution branch.
        sol_dir = None
        if args.solution:
            sol_dir = fetch_solution(args.master_org, args.template, Path(soldir) / "t")
            if sol_dir is None:
                return 1

        # Stage 2: fan out one repo per unit (student, or team) FROM the cohort template.
        results: dict[str, int] = {}
        for repo, handles in units:
            log_step(repo)
            status = provision_one(
                args.cohort_org,
                cohort_template,
                args.cohort_org,
                repo,
                handles,
                slug,
                sol_dir,
            )
            results[status] = results.get(status, 0) + 1

    log_ok(f"Done - {json.dumps(results)}")
    from . import site

    site.sync_site(args.master_org, args.cohort_org)
    return 1 if any(k.startswith("failed") for k in results) else 0


if __name__ == "__main__":
    sys.exit(main())
