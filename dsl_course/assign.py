"""dsl-course assign -- bot-push assignment provisioner.

Generates ONE private submission repo per onboarded student, from a PRIVATE master
template, into the cohort org. The bot copies the template (the student never reads
it), so the template — and the assignment questions in it — stay private and reusable
across years. Students never use a CLI.

    master org   Hertie-School-{Course}-{Code}   PRIVATE  {assignment}-template
                          │  generate (bot)
                          ▼
    cohort org   {Course}-f{YYYY}                 PRIVATE  {assignment}-{handle}  + student as collaborator

Reads the roster from the cohort's PRIVATE classroom-config/students.csv. Rows without
a github_handle yet (enrolled-but-not-onboarded) are skipped. Idempotent: existing
repos are left alone.

Usage:
    python3 -m dsl_course.assign \\
        --master-org Hertie-School-Deep-Learning-EXAMPLE \\
        --cohort-org Deep-Learning-EXAMPLE-f2026 \\
        --assignment assignment-1 \\
        --template assignment-1-template
"""

from __future__ import annotations

import argparse
import json
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


def slugify(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in value.lower()).strip(
        "-"
    )


def provision_one(
    master_org: str,
    template: str,
    cohort_org: str,
    repo_name: str,
    handle: str,
    assignment: str,
) -> str:
    """Generate repo_name in the cohort org from the master template + add the student.

    Returns a status string.
    """
    if repo_exists(cohort_org, repo_name):
        log_skip(f"repo {cohort_org}/{repo_name}")
    elif not generate_from_template(
        template_org=master_org,
        template_name=template,
        owner=cohort_org,
        name=repo_name,
        private=True,
        description=f"{assignment} — submission repo",
    ):
        return "failed-create"
    else:
        log_ok(f"created {cohort_org}/{repo_name}")

    set_repo_topics(cohort_org, repo_name, [slugify(assignment), "submission"])

    # Student gets `maintain` on their own repo (can manage settings, not delete).
    if add_collaborator(cohort_org, repo_name, handle, permission="maintain"):
        log_ok(f"  + @{handle} (maintain)")
        return "ok"
    log_err(f"  ! could not add @{handle} (not a real account?)")
    return "created-no-collaborator"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--master-org", required=True, help="Master org (template source)"
    )
    parser.add_argument("--cohort-org", required=True, help="Cohort org (target)")
    parser.add_argument(
        "--assignment", required=True, help="Assignment slug, e.g. assignment-1"
    )
    parser.add_argument(
        "--template", required=True, help="Template repo name in the master org"
    )
    parser.add_argument(
        "--roster",
        default=None,
        help="Local students.csv (default: read from cohort classroom-config)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    students = (
        roster.load_path(args.roster) if args.roster else roster.load(args.cohort_org)
    )
    if not students:
        return 1

    onboarded = [s for s in students if s.onboarded]
    skipped = len(students) - len(onboarded)
    log_step(
        f"Provisioning {args.assignment} for {len(onboarded)} onboarded student(s) "
        f"-> {args.cohort_org} (template {args.master_org}/{args.template})"
    )
    if skipped:
        log(f"  ({skipped} not-yet-onboarded row(s) skipped)")

    if args.dry_run:
        for s in onboarded:
            log(
                f"    DRY-RUN  {args.cohort_org}/{args.assignment}-{s.github_handle}  <- @{s.github_handle}"
            )
        return 0

    results: dict[str, int] = {}
    for s in onboarded:
        repo_name = f"{args.assignment}-{s.github_handle}"
        log_step(repo_name)
        status = provision_one(
            args.master_org,
            args.template,
            args.cohort_org,
            repo_name,
            s.github_handle,
            args.assignment,
        )
        results[status] = results.get(status, 0) + 1

    log_ok(f"Done — {json.dumps(results)}")
    return 1 if any(k.startswith("failed") for k in results) else 0


if __name__ == "__main__":
    sys.exit(main())
