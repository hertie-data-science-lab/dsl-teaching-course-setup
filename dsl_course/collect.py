"""dsl-course collect -- faculty-side autograding (hidden tests, after the deadline).

Runs entirely in a faculty-controlled job (course-org Actions, bot token). For each
submission repo it checks out the commit that repo was frozen at (see SNAPSHOTS below),
overlays the assignment's HIDDEN tests (kept on the course template's `solution` branch,
never shipped to students), runs them, and records a machine score into the PRIVATE grades
CSV. Faculty & instructors then add manual marks and the existing grades pipeline emails
the result - so a student never sees a score in their own repo.

  course/<template> @ solution branch  ->  grading.yml + hidden tests
                |
  cohort/<slug>-<handle>  (individual)   clone @ snapshot, overlay tests, run
  cohort/<slug>-<team>    (group)              |
                v
  classroom-config/autograde/<slug>/<key>.json   (per-test detail, private archive)
  classroom-config/grades/<slug>.csv             (auto / team_grade columns filled)

Student code is run in a subprocess with the GitHub token stripped from the environment.

SNAPSHOTS (server-timed deadlines).  Which commit gets graded cannot be decided from
commit dates alone: a git committer date is entirely client-supplied (`GIT_COMMITTER_DATE`),
so late work backdated to before the deadline would pass a `rev-list --before` pin. Instead
the hourly scheduler freezes each assignment shortly after its grading deadline passes,
writing one row per submission repo into

    classroom-config/snapshots/<slug>.csv     repo,sha,recorded_at

recorded at a time the SERVER chose, and never rewritten once written (`snapshot_assignment`
refuses to overwrite). Grading then pins to the recorded sha; an empty sha means "nothing
had been pushed by the deadline" and scores zero. Only if no snapshot exists at all does
grading fall back to the old date-based pin, with a loud warning.

Honest limitation: a commit pushed AFTER the deadline but BEFORE the next hourly cron tick,
carrying a spoofed pre-deadline committer date, is still picked up by that first snapshot.
The window for backdating shrinks from unlimited to <=1h; it does not close. Shortening the
cron interval shortens it further. (To deliberately re-freeze - e.g. an assignment whose
repos were provisioned late - delete the snapshot CSV and let the next tick rebuild it.)

FIRE-ONCE.  The hourly scheduler autogrades each assignment exactly once, just after its
grading deadline. The marker is the `autograde/<slug>/` directory this module writes: while
it is absent the assignment has never been machine-graded, and once it exists it is never
graded again automatically. A DECISION not to grade (no `solution` branch, `autograde:
false`, nothing gradable) writes the marker too - as `<slug>/_skipped.json`, saying why -
because a skip that leaves it absent is re-decided, at the cost of a template clone, every
hour for ever. Machine-written grade cells are write-once too (see
`grades.merge_auto`), so a marker's hand-edit is never clobbered. To re-grade deliberately,
delete `autograde/<slug>/` (the next tick regrades) or press the Grade assignment button -
and clear the `auto`/`team_grade` cells you want recomputed.

grading.yml (on the template's solution branch):
    type: individual        # or group
    format: py              # or notebook
    autograde: true         # false -> skip (all-manual)
    max_auto: 10
    tests: tests            # path on the solution branch holding the hidden tests

Usage:
    python3 -m dsl_course.collect \\
        --master-org COURSE --template assignment-1-f2026 \\
        --cohort-org COHORT --deadline 2026-10-15 [--group] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import grades, roster, schedule, teams
from .assign import SOLUTION_BRANCH, assignment_slug
from .utils import (
    GIT_ENV,
    get_file_content,
    gh,
    git,
    log,
    log_err,
    log_ok,
    log_skip,
    log_step,
    put_file,
)

CONFIG_REPO = roster.CONFIG_REPO  # classroom-config
AUTOGRADE_DIR = "autograde"  # classroom-config/autograde/<slug>/<key>.json
SKIP_RECORD = "_skipped.json"  # the same marker, for an assignment nothing grades
SNAPSHOT_DIR = "snapshots"  # classroom-config/snapshots/<slug>.csv
SNAPSHOT_FIELDS = ("repo", "sha", "recorded_at")
GRADING_FILE = "grading.yml"  # on the template's solution branch
RUN_TIMEOUT = 300  # seconds per submission

_DEFAULT_SPEC = {
    "type": "individual",
    "format": "py",
    "autograde": True,
    "max_auto": None,
    "tests": "tests",
}


# --------------------------------------------------------------------------- pure core


def parse_grading_spec(text: str) -> dict:
    """Parse a grading.yml (missing keys fall back to defaults; extras ignored)."""
    data = yaml.safe_load(text) if text.strip() else {}
    if not isinstance(data, dict):
        data = {}
    spec = dict(_DEFAULT_SPEC)
    spec.update({k: data[k] for k in _DEFAULT_SPEC if k in data})
    return spec


def template_is_group(master_org: str, template: str) -> bool:
    """Whether an assignment template declares itself group-provisioned: `type: group` in
    the grading.yml on its solution branch (written by the New assignment scaffold). No
    solution branch / no grading.yml means individual (the parse's default)."""
    text = get_file_content(master_org, template, GRADING_FILE, ref=SOLUTION_BRANCH)
    return parse_grading_spec(text or "")["type"] == "group"


def assignment_is_group(master_org: str, cohort_org: str, template: str) -> bool:
    """The one resolution of group-vs-individual every consumer (handout, grading) uses.

    Precedence: the COHORT's own declaration - `assignments.<slug>.type` in
    classroom-config/schedule.yml - wins; else the template's design-time grading.yml
    `type:` (solution branch, written by the New assignment scaffold); else individual.
    Read-side only: the cohort setting never writes back into the course org's
    grading.yml - sources are read course-ward, state written cohort-ward."""
    found = schedule.entry_for_repo(schedule.load(cohort_org), template)
    entry = found[1] if found else None
    if entry is not None and entry.type is not None:
        return entry.type == "group"
    return template_is_group(master_org, template)


def score_from_junit(xml_text: str) -> dict:
    """Turn a pytest junit XML report into the result.json contract {score, max, tests}.

    A case passes only if it has neither failure, error, nor skipped child element."""
    root = ET.fromstring(xml_text)
    if root.tag == "testsuite":
        suite = root
    else:
        nested = root.find("testsuite")
        suite = nested if nested is not None else root
    cases = [
        {
            "name": tc.get("name"),
            "passed": tc.find("failure") is None
            and tc.find("error") is None
            and tc.find("skipped") is None,
        }
        for tc in suite.findall("testcase")
    ]
    return {
        "score": sum(1 for c in cases if c["passed"]),
        "max": len(cases),
        "tests": cases,
    }


def summary_lines(result: dict) -> list[str]:
    """Human-readable per-target summary (plain tick/cross glyphs, never emoji)."""
    lines = [f"  Score: {result['score']}/{result['max']}"]
    if result.get("note"):
        lines.append(f"  ({result['note']})")
    lines += [f"    {'✓' if c['passed'] else '✗'} {c['name']}" for c in result["tests"]]
    return lines


def _zero_result(max_auto: int, note: str) -> dict:
    """A zero score carrying an explanatory note (non-submission / grading failure)."""
    return {"score": 0, "max": max_auto, "tests": [], "note": note}


def snapshot_path(slug: str) -> str:
    """Where this assignment's deadline snapshot lives in `classroom-config`."""
    return f"{SNAPSHOT_DIR}/{slug}.csv"


def autograde_path(slug: str) -> str:
    """Where this assignment's per-target result archive lives in `classroom-config`."""
    return f"{AUTOGRADE_DIR}/{slug}"


def dump_snapshots(rows: list[tuple[str, str, str]]) -> str:
    """Serialise (repo, sha, recorded_at) rows to snapshot CSV text, repo-sorted so the
    file is stable and diffable."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(SNAPSHOT_FIELDS)
    for row in sorted(rows):
        writer.writerow(row)
    return out.getvalue()


def parse_snapshots(text: str) -> dict[str, str]:
    """Parse snapshot CSV text into {repo: sha}. A blank sha is meaningful - it records
    "nothing had been pushed to this repo by the deadline" - so it is kept, not dropped."""
    return {
        repo: (row.get("sha") or "").strip()
        for row in csv.DictReader(io.StringIO(text))
        if (repo := (row.get("repo") or "").strip())
    }


# ---------------------------------------------------------------------- gh/git wiring


def _sanitised_env() -> dict:
    """A copy of the environment with every GitHub token stripped - student code must
    never run with the bot token in scope."""
    env = dict(os.environ)
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_API_TOKEN", "GH_ENTERPRISE_TOKEN"):
        env.pop(key, None)
    return env


def submission_targets(
    cohort_org: str, slug: str, is_group: bool | None = None
) -> list[tuple[str, str, list[str]]]:
    """The submission units for `slug` as (repo, key, members): one per team for a group
    assignment, one per onboarded student otherwise. Empty - with the reason logged - when
    there is nothing to grade.

    `is_group=None` infers it: teams.csv rows keyed on this slug mean a group assignment.
    That lets the scheduler's snapshot step find the repos without reading grading.yml,
    which lives on the course template's `solution` branch (a clone away, in the other org).
    """
    groups = (
        teams.teams_for(teams.load(cohort_org), slug) if is_group is not False else {}
    )
    if is_group or (is_group is None and groups):
        if not groups:
            log_err(f"no teams for `{slug}` in {cohort_org}/{CONFIG_REPO}/teams.csv.")
            return []
        return [
            (f"{slug}-{team}", team, members)
            for team, members in sorted(groups.items())
        ]
    targets = [
        (f"{slug}-{s.github_handle}", s.github_handle, [s.github_handle])
        for s in roster.load(cohort_org) or []
        if s.onboarded
    ]
    if not targets:
        log_err(f"no onboarded students in {cohort_org} to grade.")
    return targets


def _until_param(deadline: str) -> str:
    """`deadline` (ISO date or datetime, with or without an offset) as a UTC `...Z` stamp -
    the form the commits API's `until=` takes. A bare date means end of that day, matching
    the date-pin fallback; a naive datetime is read as UTC (every schedule-derived deadline
    is already offset-carrying)."""
    raw = deadline if ("T" in deadline or ":" in deadline) else f"{deadline}T23:59:59"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _snapshot_sha(cohort_org: str, repo: str, deadline: str) -> str | None:
    """The sha to freeze `repo` at: its last commit on or before `deadline`, read from the
    API (no clone - this runs for every repo of every assignment, hourly).

    Returns "" when there is nothing to grade: no commit that early, an empty repo, or no
    such repo at all (an on-time submission cannot live in a repo that does not exist).
    Returns None when the API call itself failed - the caller then abandons the whole
    snapshot so the next cron tick retries, rather than baking a transient error into a
    record that is never rewritten."""
    code, out = gh(
        "api",
        "-X",
        "GET",
        f"repos/{cohort_org}/{repo}/commits",
        "-f",
        f"until={_until_param(deadline)}",
        "-f",
        "per_page=1",
        "--jq",
        '.[0].sha // ""',
    )
    if code == 0:
        return out.strip()
    if any(m in out for m in ("HTTP 404", "Not Found", "HTTP 409", "empty")):
        return ""
    log_err(f"  ! could not read commits for {cohort_org}/{repo}: {out[:160]}")
    return None


def has_autograde_results(cohort_org: str, slug: str) -> bool:
    """Whether `autograde/<slug>/` already exists in the cohort's classroom-config.

    This directory is the autograder's FIRE-ONCE marker: the scheduler grades an assignment
    only while it is absent, so a machine score is written once and never silently refreshed
    under a marker's hand-edits. A deliberate re-grade means deleting the directory (the next
    hourly tick then regrades) or pressing the Grade assignment button."""
    code, _ = gh(
        "api", f"repos/{cohort_org}/{CONFIG_REPO}/contents/{autograde_path(slug)}"
    )
    return code == 0


def mark_not_autograded(cohort_org: str, slug: str, why: str) -> bool:
    """Record that this assignment will never be machine-graded, and why.

    `autograde/<slug>/` IS the fire-once marker (see `has_autograde_results`), so a skip
    that leaves it absent is not a skip at all: the scheduler re-clones the template and
    re-decides the same skip on every hourly tick, for ever. The note is what tells a
    marker reading the archive that the empty result set was deliberate."""
    return put_file(
        cohort_org,
        CONFIG_REPO,
        f"{autograde_path(slug)}/{SKIP_RECORD}",
        json.dumps(
            {
                "skipped": why,
                "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            indent=2,
        ).encode(),
        f"autograde: {slug} not machine-graded ({why})",
    )


def load_snapshots(cohort_org: str, slug: str) -> dict[str, str] | None:
    """{repo: sha} from this assignment's snapshot CSV, or None if no snapshot was ever
    taken (the two are different: a recorded blank sha means "no submission", while no
    file at all means grading has to fall back to client-supplied commit dates)."""
    content = get_file_content(cohort_org, CONFIG_REPO, snapshot_path(slug))
    return parse_snapshots(content) if content is not None else None


def snapshot_assignment(cohort_org: str, slug: str, deadline: str) -> bool:
    """Freeze, at a server-chosen moment, the commit each of `slug`'s submission repos will
    be graded at. Write-once: an existing snapshot is never re-taken or overwritten, so a
    late push can never move the pin. Returns False if the snapshot could not be completed
    (nothing is written - the next cron tick tries again).

    An assignment with no submission units yet is a no-op, not a failure: nothing is frozen
    and nothing is written, so a later handout still gets its own snapshot."""
    if load_snapshots(cohort_org, slug) is not None:
        log_skip(f"snapshot {snapshot_path(slug)}")
        return True
    targets = submission_targets(cohort_org, slug)
    if not targets:
        # Nobody onboarded, or no teams for a group assignment - which is also what an
        # assignment not handed out yet looks like from here. The snapshot is write-once,
        # so freezing an empty one would pin the assignment to "nothing submitted" for
        # ever; write nothing and let a later tick take it. Green, because the alternative
        # is a red hourly run for every assignment whose cohort has yet to fill up.
        # `submission_targets` has already logged which of the two it was.
        log(
            f"  [skip] snapshot {snapshot_path(slug)} - nothing to freeze yet; "
            f"a later tick takes it"
        )
        return True
    recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: list[tuple[str, str, str]] = []
    for repo, _key, _members in targets:
        sha = _snapshot_sha(cohort_org, repo, deadline)
        if sha is None:
            log_err(f"  ! abandoning the {slug} snapshot - will retry on the next run")
            return False
        rows.append((repo, sha, recorded_at))
    if not put_file(
        cohort_org,
        CONFIG_REPO,
        snapshot_path(slug),
        dump_snapshots(rows).encode(),
        f"snapshot: {slug} pinned commits as of {deadline}",
    ):
        return False
    pinned = sum(1 for _repo, sha, _at in rows if sha)
    log_ok(
        f"snapshot {snapshot_path(slug)}: {pinned}/{len(rows)} repo(s) with a commit "
        f"on/before {deadline}"
    )
    return True


def _pin_commit(
    repo_dir: Path, deadline: str, snapshot: str | None = None
) -> str | None:
    """Check out the commit this repo is graded at and return its sha (None = nothing to
    grade).

    `snapshot` is this repo's server-timed snapshot entry: a sha to grade, or "" for "no
    commit existed by the deadline". None means no snapshot covers this repo, so we fall
    back to `rev-list --before` - which filters on the COMMITTER date, a value the student
    supplies, so it can be backdated. `deadline` is an ISO date or datetime; a bare date
    (no time) is treated as end-of-day."""
    if snapshot is not None:
        if not snapshot:
            return None  # snapshot recorded no submission on/before the deadline
        if git("-C", str(repo_dir), "cat-file", "-e", f"{snapshot}^{{commit}}")[0] == 0:
            git("-C", str(repo_dir), *GIT_ENV, "checkout", "-q", snapshot)
            return snapshot
        log_err(
            f"  ! snapshot commit {snapshot[:8]} is not in the clone (history rewritten?) "
            f"- falling back to the commit-date pin"
        )
    before = (
        deadline if ("T" in deadline or ":" in deadline) else f"{deadline} 23:59:59"
    )
    code, out = git("-C", str(repo_dir), "rev-list", "-1", f"--before={before}", "HEAD")
    sha = out.strip()
    if code != 0 or not sha:
        return None
    git("-C", str(repo_dir), *GIT_ENV, "checkout", "-q", sha)
    return sha


def _stray_conversion(nb: Path) -> Path | None:
    """The file `jupyter nbconvert --to script` actually wrote for `nb`, when that is not
    the expected `<stem>.py`.

    nbconvert names its output from the notebook's `metadata.language_info.file_extension`,
    so a notebook whose metadata is empty, carries only a `kernelspec`, or omits
    `file_extension` (all common in student submissions, and what a fresh `{}`-metadata
    notebook looks like) converts to `<stem>.txt` - or to a bare `<stem>` if
    `file_extension` is present but empty. The hidden tests then `from starter import ...`
    against a file that does not exist and every submission scores zero, so the output is
    renamed back to `.py` rather than trusted."""
    for candidate in (nb.with_suffix(".txt"), nb.with_suffix("")):
        if candidate.is_file():
            return candidate
    return None


def _run_tests(workdir: Path, fmt: str, tests_src: Path) -> dict | None:
    """Overlay the hidden tests into the checked-out submission and run them token-free.
    Returns the result.json dict, or None if grading could not run."""
    env = _sanitised_env()
    env["PYTHONPATH"] = str(workdir) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        if fmt == "notebook":
            # Convert each notebook to an importable script first (Otter can slot in here).
            for nb in workdir.rglob("*.ipynb"):
                subprocess.run(  # noqa: PLW1510 - a failed convert is tolerated per notebook
                    [
                        sys.executable,
                        "-m",
                        "jupyter",
                        "nbconvert",
                        "--to",
                        "script",
                        str(nb),
                    ],
                    cwd=workdir,
                    env=env,
                    timeout=RUN_TIMEOUT,
                    capture_output=True,
                )
                script = nb.with_suffix(".py")
                if not script.exists() and (stray := _stray_conversion(nb)):
                    stray.rename(script)
                    log(
                        f"    ({nb.name} declares no python file_extension - "
                        f"{stray.name} -> {script.name})"
                    )
        dest = workdir / "_grading_tests"
        shutil.copytree(tests_src, dest, dirs_exist_ok=True)
        report = workdir / "report.xml"
        subprocess.run(  # noqa: PLW1510 - a non-zero pytest run IS the grading result
            [sys.executable, "-m", "pytest", "-q", str(dest), f"--junitxml={report}"],
            cwd=workdir,
            env=env,
            timeout=RUN_TIMEOUT,
            capture_output=True,
        )
    except subprocess.TimeoutExpired:
        log_err(f"  ! grading timed out after {RUN_TIMEOUT}s")
        return None
    if not report.exists():
        return None
    return score_from_junit(report.read_text())


def _grade_target(
    cohort_org: str,
    repo: str,
    spec: dict,
    tests_src: Path,
    deadline: str,
    snapshot: str | None = None,
) -> dict | None:
    """Clone one submission, pin it to its snapshot (else the deadline), run the hidden
    tests. Always returns a result dict (a zero with a note for non-submissions /
    failures), or None if unclonable."""
    max_auto = spec.get("max_auto") or 0
    with tempfile.TemporaryDirectory() as work:
        wd = Path(work) / "sub"
        if gh("repo", "clone", f"{cohort_org}/{repo}", str(wd), "--", "-q")[0] != 0:
            log_err(f"  ! could not clone {cohort_org}/{repo} (not generated yet?)")
            return None
        sha = _pin_commit(wd, deadline, snapshot)
        if sha is None:
            return _zero_result(max_auto, f"no submission on/before {deadline}")
        result = _run_tests(wd, spec["format"], tests_src)
        if result is None:
            return _zero_result(max_auto, "grading failed to run")
        result["commit"] = sha
        return result


def _today_in_cohort_tz(sched: schedule.Schedule) -> str:
    """Today's date in the COHORT's timezone (schedule.yml `timezone`, default
    Europe/Berlin) - the last-resort grading pin for an unscheduled assignment. The
    Actions runner is UTC, so its own `date.today()` can be a day behind Berlin
    (00:00-02:00 local) and pin the grading to the wrong day."""
    return datetime.now(schedule._tz(sched.timezone)).date().isoformat()


def collect(
    master_org: str,
    template: str,
    cohort_org: str,
    deadline: str | None = None,
    group: bool = False,
    dry_run: bool = False,
) -> int:
    """Autograde every submission for `template` as of `deadline`, archiving result.json and
    recording the machine score into the cohort's private grades CSV. Idempotent."""
    if master_org == cohort_org:
        log_err("master-org and cohort-org must differ.")
        return 1
    # The cohort-side identity is the SCHEDULE key when the assignment is scheduled
    # (the slug is a free label since course_source_repo), else the repo name minus its
    # tag. Everything cohort-side keys on it - snapshots, autograde markers, grades - and
    # the scheduler's fire-once marker uses the schedule key, so the two must agree or a
    # passed deadline re-grades every tick.
    sched = schedule.load(cohort_org)
    found = schedule.entry_for_repo(sched, template)
    key = found[0] if found else assignment_slug(template)
    slug = schedule.cohort_name(*found) if found else key
    # SSOT: default the grading pin to the cohort schedule's grading deadline (explicit
    # `grading_datetime`, else `due_datetime`); an explicit `deadline` (CLI override)
    # wins; fall back to today - in the cohort's own timezone, like every other date here -
    # only if unscheduled.
    deadline = (
        deadline
        or schedule.grading_datetime_iso(sched, key)
        or _today_in_cohort_tz(sched)
    )

    with tempfile.TemporaryDirectory() as sd:
        soldir = Path(sd) / "sol"
        if (
            gh(
                "repo",
                "clone",
                f"{master_org}/{template}",
                str(soldir),
                "--",
                "-q",
                "-b",
                SOLUTION_BRANCH,
            )[0]
            != 0
        ):
            log_err(
                f"no `{SOLUTION_BRANCH}` branch on {master_org}/{template} - no hidden "
                f"tests to run; nothing to collect."
            )
            # Hand-marked, then: say so once in the archive rather than re-deciding it on
            # every hourly tick (see FIRE-ONCE above).
            if not dry_run:
                mark_not_autograded(
                    cohort_org,
                    slug,
                    f"no `{SOLUTION_BRANCH}` branch on {master_org}/{template}",
                )
            return 0
        spec_path = soldir / GRADING_FILE
        spec = parse_grading_spec(spec_path.read_text() if spec_path.is_file() else "")
        if not spec["autograde"]:
            log_ok(
                f"{slug}: autograde disabled in {GRADING_FILE} - all-manual, nothing to collect."
            )
            if not dry_run:
                mark_not_autograded(
                    cohort_org, slug, f"`autograde: false` in {GRADING_FILE}"
                )
            return 0
        # group-vs-individual precedence: an explicit force (the button's checkbox) wins;
        # else the COHORT's declaration (schedule.yml assignments.<slug>.type); else the
        # template's design-time grading.yml `type:`. The entry is the one found above by
        # course_source_repo - `slug` is the cohort-side NAME, which is `cohort_dest_repo`
        # when that is set and so is not a key into `sched.assignments` at all.
        entry = found[1] if found else None
        cohort_kind = entry.type if entry else None
        if group:
            is_group = True
        elif cohort_kind is not None:
            is_group = cohort_kind == "group"
        else:
            is_group = spec["type"] == "group"
        tests_src = soldir / str(spec["tests"])
        if not tests_src.is_dir():
            log_err(
                f"{slug}: tests path `{spec['tests']}` not found on the solution branch."
            )
            return 1

        # Targets: one per team (group) or one per onboarded student (individual).
        targets = submission_targets(cohort_org, slug, is_group)
        if not targets:
            return 1

        # Which commit each repo is graded at was frozen server-side just after the
        # deadline (see the module docstring). Without that file we can only trust the
        # student-supplied committer dates - say so loudly rather than silently.
        snapshots = load_snapshots(cohort_org, slug)
        if snapshots is None:
            log_err(
                f"  ! no {snapshot_path(slug)} for {slug} - pinning on committer dates, "
                f"which students control; late work backdated before {deadline} will pass"
            )

        log_step(
            f"Collecting {slug} in {cohort_org}: {len(targets)} "
            f"{'team(s)' if is_group else 'student(s)'} as of {deadline}"
        )

        updates: list[tuple[str, dict[str, str]]] = []
        # `_grade_target` returns None for one reason only: the submission repo could not be
        # cloned. That is the line between "examined, and there was nothing to grade" (a
        # recorded non-submission still comes back as a zero result) and "never examined" -
        # and the fire-once record below must never be written on the strength of the latter.
        unreachable: list[str] = []
        for repo, target_key, members in targets:
            log_step(repo)
            if dry_run:
                pin = (
                    f"<= {deadline}"
                    if snapshots is None
                    else f"snapshot {(snapshots.get(repo) or 'none')[:8]}"
                )
                log(f"    DRY-RUN would grade {cohort_org}/{repo} (pin {pin})")
                continue
            result = _grade_target(
                cohort_org,
                repo,
                spec,
                tests_src,
                deadline,
                snapshot=None if snapshots is None else snapshots.get(repo),
            )
            if result is None:
                unreachable.append(repo)
                continue
            for line in summary_lines(result):
                log(line)
            put_file(
                cohort_org,
                CONFIG_REPO,
                f"{autograde_path(slug)}/{target_key}.json",
                json.dumps(result, indent=2).encode(),
                f"autograde: {slug}/{target_key}",
            )
            score = str(result["score"])
            if is_group:
                updates += [
                    (m, {"team": target_key, "team_grade": score}) for m in members
                ]
            else:
                updates.append((target_key, {"auto": score}))

        if dry_run:
            return 0
        if not updates and unreachable:
            # Nothing graded because nothing could be READ - a repo that is not there yet,
            # or an API having a bad afternoon. The run is genuinely unfinished, so it goes
            # red and no record is written: the next tick must be free to try again, and
            # one outage must never mark an assignment as permanently not-machine-graded.
            log_err(
                f"{slug}: none of the {len(unreachable)} submission repo(s) could be read "
                f"(named above) - nothing graded, and nothing recorded; the next run retries"
            )
            return 1
        if not updates:
            # Every target WAS examined and none of them yielded a grade. Not a failure: the
            # snapshot is frozen, so an hourly retry would see exactly what this run saw and
            # go red for ever. Record the skip and stay green - a deliberate re-grade is
            # still a delete of autograde/<slug>/ away.
            log_ok(
                f"{slug}: nothing gradable across {len(targets)} target(s) - recording "
                f"the skip rather than retrying every hour."
            )
            mark_not_autograded(
                cohort_org,
                slug,
                f"nothing gradable across {len(targets)} target(s) as of {deadline}",
            )
            return 0

        path = f"{grades.GRADES_DIR}/{slug}.csv"
        existing = get_file_content(cohort_org, CONFIG_REPO, path) or ""
        new_csv = grades.merge_auto(existing, updates)
        if not put_file(
            cohort_org,
            CONFIG_REPO,
            path,
            new_csv.encode(),
            f"autograde: record auto scores for {slug}",
        ):
            log_err(f"could not write {path}")
            return 1
    log_ok(
        f"recorded {len(updates)} auto score(s) -> {path} (faculty & instructors add manual marks, then render)"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--master-org", required=True, help="Course org (template source)"
    )
    parser.add_argument(
        "--course-source-repo",
        dest="template",
        required=True,
        help="Assignment template (e.g. assignment-1-f2026)",
    )
    parser.add_argument("--cohort-org", required=True, help="Cohort org (submissions)")
    parser.add_argument(
        "--deadline",
        default=None,
        help="ISO date override; default = the cohort schedule's grading deadline, else today",
    )
    parser.add_argument(
        "--group", action="store_true", help="Group assignment (one repo per team)"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return collect(
        args.master_org,
        args.template,
        args.cohort_org,
        args.deadline,
        group=args.group,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
