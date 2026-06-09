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
import sys

from . import roster
from .utils import (
    add_collaborator,
    generate_from_template,
    log,
    log_err,
    log_ok,
    log_skip,
    log_step,
    repo_exists,
    set_repo_topics,
)


def assignment_slug(template: str) -> str:
    """assignment-1-f2026 -> assignment-1 (drop a trailing cohort suffix)."""
    return re.sub(r"-[fs]\d{4}$", "", template)


def provision_one(
    master_org: str, template: str, cohort_org: str, repo: str, handle: str, slug: str
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
    )
    if skipped:
        log(f"  ({skipped} not-yet-onboarded row(s) skipped)")

    if args.dry_run:
        for s in onboarded:
            log(
                f"    DRY-RUN  {args.cohort_org}/{slug}-{s.github_handle}  <- @{s.github_handle}"
            )
        return 0

    results: dict[str, int] = {}
    for s in onboarded:
        repo = f"{slug}-{s.github_handle}"
        log_step(repo)
        status = provision_one(
            args.master_org, args.template, args.cohort_org, repo, s.github_handle, slug
        )
        results[status] = results.get(status, 0) + 1

    log_ok(f"Done - {json.dumps(results)}")
    return 1 if any(k.startswith("failed") for k in results) else 0


if __name__ == "__main__":
    sys.exit(main())
