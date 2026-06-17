"""dsl-course enrol-codes -- generate per-student enrolment codes and email them.

Students enrol by pasting a random, **non-PII** code (not their email) into the welcome
Join issue, so no personal data ever touches the public repo - and because the code is
unguessable, a classmate can't bind your roster row to their account. This one action:

    1. fills blank `enrol_code` cells in classroom-config/students.csv (idempotent), then
    2. emails each not-yet-onboarded student their code over SMTP (preview with --dry-run).

Email reaches the student's UNIVERSITY inbox (the roster `hertie_email`), replacing the
Excel -> Power Automate -> Outlook mail-merge. Reuses dsl_course.mailer.

Usage:
    python3 -m dsl_course.enrol_codes --cohort-org Deep-Learning-EXAMPLE-f2026 --dry-run
    python3 -m dsl_course.enrol_codes --cohort-org Deep-Learning-EXAMPLE-f2026
"""

from __future__ import annotations

import argparse
import secrets
import sys

from . import mailer, roster
from .utils import log, log_ok, log_step, put_file

# No ambiguous characters (0/O, 1/l/I) so a student can read the code off an email.
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def make_code() -> str:
    return "dsl-" + "".join(secrets.choice(_ALPHABET) for _ in range(6))


def assign_codes(students: list[roster.Student], gen=make_code) -> int:
    """Fill enrol_code on rows that lack one (unique). Mutates rows; returns count added."""
    seen = {s.enrol_code for s in students if s.enrol_code}
    added = 0
    for s in students:
        if s.enrol_code:
            continue
        code = gen()
        while code in seen:
            code = gen()
        s.enrol_code = code
        seen.add(code)
        added += 1
    return added


def code_message(student: roster.Student, welcome_url: str) -> mailer.Message:
    """The enrolment-code email for one student: (to, subject, body)."""
    subject = "Your course enrolment code"
    body = (
        f"Hello {student.name or 'there'},\n\n"
        f"To join the course on GitHub, open a 'Join' issue here:\n"
        f"  {welcome_url}\n\n"
        f"and paste this enrolment code when asked:\n\n"
        f"    {student.enrol_code}\n\n"
        f"Whichever GitHub account opens the issue is linked to you automatically - "
        f"you don't need to type any personal details.\n"
    )
    return (student.hertie_email, subject, body)


def run(cohort_org: str, dry_run: bool = False) -> int:
    students = roster.load(cohort_org)
    if not students:
        return 1

    added = assign_codes(students)  # in memory; persisted below unless dry-run
    log_step(
        f"Enrolment codes for {cohort_org}: {added} new code(s), "
        f"emailing not-yet-onboarded students"
    )
    if added and not dry_run:
        body = roster.dump(students)
        if not put_file(
            cohort_org,
            roster.CONFIG_REPO,
            roster.ROSTER_PATH,
            body.encode(),
            f"roster: assign {added} enrolment code(s)",
        ):
            return 1
        log_ok(f"wrote {added} code(s) to {roster.ROSTER_PATH}")

    welcome_url = f"https://github.com/{cohort_org}/welcome/issues/new/choose"
    targets = [
        s for s in students if s.enrol_code and s.hertie_email and not s.onboarded
    ]
    if not targets:
        log_ok("no not-yet-onboarded students with an email to mail.")
        return 0
    messages = [code_message(s, welcome_url) for s in targets]
    sent = mailer.send_bulk(messages, dry_run=dry_run)
    if dry_run:
        log("    (dry-run: codes not written, emails not sent)")
        return 0
    return 0 if sent == len(messages) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-org", required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the codes + emails; write nothing, send nothing.",
    )
    args = parser.parse_args()
    return run(args.cohort_org, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
