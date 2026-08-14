"""The SYSTEM-owned welcome-repo seeding, and the template reader it shares.

Split out of bootstrap_course so `seed.refresh` can re-push a live cohort's onboarding
workflows on its nightly run: bootstrap_course imports seed, so seed cannot import
bootstrap_course back - this module is what both sides may import.
"""

from __future__ import annotations

from pathlib import Path

from .utils import delete_file, log_err, log_ok, put_file

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def template(rel: str) -> str:
    """Read a seeded template file (templates/<rel>) as text.

    Everything under templates/ is content pushed into a course/cohort repo, kept in real
    files rather than Python literals so faculty & instructors can read (and PR) the thing
    they'll actually receive. Most are seeded verbatim; the few that carry `{placeholders}`
    are rendered with str.format (see bootstrap_course._course_metadata)."""
    return (TEMPLATES / rel).read_text(encoding="utf-8")


def refresh_welcome_workflows(org: str) -> int:
    """Re-push a cohort's welcome-repo machinery (onboarding workflows + the issue forms
    they parse) from the current templates. Called both at bootstrap and on every refresh,
    so a fix reaches running cohorts; put_file skips whatever is already identical.

    Returns the number of writes that failed, so a caller (seed.refresh) can go red
    rather than report an onboarding repo it never managed to converge."""
    # Everything under .github/ here is SYSTEM-owned: the onboarding workflows and the
    # issue forms they parse (field ids must stay in lockstep with the workflow), so
    # these refresh on every run.
    results = [
        put_file(
            org,
            "welcome",
            ".github/workflows/onboard.yml",
            template("welcome/onboard.yml").encode(),
            "ci: seed onboard workflow",
        ),
        put_file(
            org,
            "welcome",
            ".github/ISSUE_TEMPLATE/01-join-course.yml",
            template("welcome/ISSUE_TEMPLATE/01-join-course.yml").encode(),
            "ci: seed Join course issue form",
        ),
        put_file(
            org,
            "welcome",
            ".github/workflows/team-formation.yml",
            template("welcome/team-formation.yml").encode(),
            "ci: seed team-formation workflow",
        ),
        put_file(
            org,
            "welcome",
            ".github/ISSUE_TEMPLATE/02-join-team.yml",
            template("welcome/ISSUE_TEMPLATE/02-join-team.yml").encode(),
            "ci: seed Join team issue form",
        ),
    ]
    # The forms were renamed to control the issue-chooser ordering (01-/02- prefix);
    # retire the old filenames on live cohorts or the chooser shows both generations.
    results += [
        delete_file(org, "welcome", stale, "ci: retire renamed issue form")
        for stale in (
            ".github/ISSUE_TEMPLATE/join.yml",
            ".github/ISSUE_TEMPLATE/join-team.yml",
        )
    ]
    failures = results.count(False)
    if failures:
        log_err(f"{failures} welcome-repo file(s) not written in {org}")
    else:
        log_ok("welcome repo workflows + Join forms up to date")
    return failures
