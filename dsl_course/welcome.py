"""The SYSTEM-owned cohort-repo seeding, and the template reader it shares.

Split out of bootstrap_course so `seed.refresh` can re-push a live cohort's onboarding
workflows and config samples on its nightly run: bootstrap_course imports seed, so seed
cannot import bootstrap_course back - this module is what both sides may import.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from .roster import CONFIG_REPO
from .utils import delete_file, log_err, log_ok, put_file

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
EXAMPLE_COHORT = ROOT / "example-course" / "cohort-org"

# Every user-editable file in classroom-config ships as a PAIR under one rule: `<file>` is
# a minimal commented scaffold, seeded once and never rewritten; `<file>.sample` is a
# filled, realistic example, always converged.
#
# The SCAFFOLD half - the file faculty fill in. `{tag}`/`{year}`/`{year_next}` are
# rendered for this cohort, so every example in a scaffold is copy-paste-correct.
CLASSROOM_SCAFFOLDS = {
    "students.csv": (
        "classroom-config/students.csv",
        "init: starter roster (fill with registrar data - see students.csv.sample)",
    ),
    "teams.csv": (
        "classroom-config/teams.csv",
        "init: starter teams table (the welcome Join-team issue appends to it)",
    ),
    "schedule.yml": (
        "classroom-config/schedule.yml",
        "docs: seed schedule.yml (release plan + due dates + exams)",
    ),
    "people.yml": (
        "classroom-config/people.yml",
        "docs: seed people.yml (this cohort's instructors/TAs)",
    ),
}

# The SAMPLE half - DERIVED, not enumerated: every regular file in the worked example
# cohort ships as `<its path>.sample`. Deriving is what makes example-course/README.md's
# "every file in cohort-org/ is seeded" claim true by construction; enumerating it once
# silently dropped the team-graded grades table. The samples are therefore not authored
# twice - they ARE the worked example the docs link to, and tests/test_bootstrap_seeding.py
# parses each one with the real parser so none can go schema-stale.
CLASSROOM_SAMPLES = {
    f"{rel}.sample": rel
    for rel in sorted(
        p.relative_to(EXAMPLE_COHORT).as_posix()
        for p in EXAMPLE_COHORT.rglob("*")
        if p.is_file()
    )
    # dotfiles are plumbing (.gitkeep and friends), never reference material
    if not any(part.startswith(".") for part in rel.split("/"))
}


@cache
def template(rel: str) -> str:
    """Read a seeded template file (templates/<rel>) as text.

    Everything under templates/ is content pushed into a course/cohort repo, kept in real
    files rather than Python literals so faculty & instructors can read (and PR) the thing
    they'll actually receive. Most are seeded verbatim; the few that carry `{placeholders}`
    are rendered with str.format (see bootstrap_course._course_metadata)."""
    return (TEMPLATES / rel).read_text(encoding="utf-8")


@cache
def example_cohort_file(rel: str) -> str:
    """Read a file from the worked example cohort (example-course/cohort-org/<rel>).

    Seeded verbatim as a `.sample`: never str.format-rendered, because a worked example is
    a real cohort's file (hertie-dsl-demo-f2026), not a scaffold to fill in."""
    return (EXAMPLE_COHORT / rel).read_text(encoding="utf-8")


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


def refresh_classroom_samples(org: str) -> int:
    """Converge a cohort's classroom-config `*.sample` files on the worked example.

    Samples are machine-owned reference material - the engine never ingests them (only the
    un-suffixed names), and activation is copying rows across - so unlike the scaffolds
    they are written unconditionally rather than seed-if-absent. `put_file` compares blob
    shas, so an already-current sample is a no-op. Called both at bootstrap and on the
    nightly refresh, so a cohort seeded last semester picks up today's examples.

    Returns the number of writes that failed, so seed.refresh can go red rather than
    report an org it never converged."""
    results = [
        put_file(
            org,
            CONFIG_REPO,
            path,
            example_cohort_file(source).encode(),
            f"docs: refresh {path} from the worked example course",
        )
        for path, source in CLASSROOM_SAMPLES.items()
    ]
    failures = results.count(False)
    if failures:
        log_err(f"{failures} classroom-config sample(s) not written in {org}")
    else:
        log_ok("classroom-config samples up to date")
    return failures
