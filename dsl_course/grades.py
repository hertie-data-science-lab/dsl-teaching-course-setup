"""dsl-course grades -- private per-student gradebook repos (the single home for grades).

Every grade, individual or group, is delivered into a PRIVATE per-student repo
`grades-<handle>` (student = read). Team project repos may be public (showcase /
open-courseware), so grades NEVER touch them: a group result is split into the shared
team grade (duplicated into each member's gradebook) and that member's private
adjustment + final mark, all delivered individually.

Three idempotent stages, each a faculty button:

    sync       cohort/grades-<handle>            (private; student = read) per onboarded student
                     ^
    render     classroom-config/grades/<assignment>.csv   (faculty's table, was Excel)
                     |  build per-student YAML
                     v
               classroom-config/gradebook/<handle>.yml  -- opened as ONE PR (the preview)
                     |  distribute (after the PR merges)
                     v
               cohort/grades-<handle>/grades.yml + an email to the student's university inbox

`classroom-config` keeps the full grade archive (private source of truth); the PR diff is
the all-students-at-once preview that the Power Automate flow never gave.

Usage:
    python3 -m dsl_course.grades sync       --cohort-org Deep-Learning-EXAMPLE-f2026
    python3 -m dsl_course.grades render     --cohort-org Deep-Learning-EXAMPLE-f2026
    python3 -m dsl_course.grades distribute --cohort-org Deep-Learning-EXAMPLE-f2026
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import mailer, roster
from .utils import (
    GIT_ENV,
    add_collaborator,
    create_repo,
    get_default_branch,
    get_file_content,
    gh,
    git,
    log,
    log_err,
    log_ok,
    log_skip,
    log_step,
    put_file,
    repo_exists,
    set_repo_topics,
)

CONFIG_REPO = roster.CONFIG_REPO  # classroom-config
GRADES_DIR = "grades"  # faculty-edited source tables, one CSV per assignment
GRADEBOOK_DIR = "gradebook"  # rendered per-student YAML staged for the preview PR
GRADEBOOK_PREFIX = "grades-"  # per-student repo: grades-<handle>
RENDER_BRANCH = "grades-update"
COHORT_CSV_NAME = "cohort-gradebook.csv"  # generated wide faculty-only glance view

# One assignment CSV row. Individual rows use `auto` (machine score) + `manual` (faculty's
# hand-marked part); group rows carry the shared `team_grade`, that member's private
# `adjustment`, and the shared `team_comments`. `final` is authoritative (stored explicitly so
# faculty own any rounding/combination). `auto`/`manual` are faculty-internal working columns -
# they never appear in the student's gradebook. Values stay strings - a grade may be a letter,
# a percentage, or "+4" - we never coerce.
GRADE_FIELDS = (
    "github_handle",
    "team",
    "auto",
    "manual",
    "team_grade",
    "adjustment",
    "final",
    "comments",
    "team_comments",
)

_STARTER_README = (
    "# Your gradebook\n\n"
    "This private repository is yours alone. Grades and feedback for each piece of "
    "assessment appear in `grades.yml` as the course progresses.\n"
)


@dataclass
class GradeRow:
    github_handle: str = ""
    team: str = ""
    auto: str = ""
    manual: str = ""
    team_grade: str = ""
    adjustment: str = ""
    final: str = ""
    comments: str = ""
    team_comments: str = ""


# --------------------------------------------------------------------------- pure core


def parse_grades(text: str) -> list[GradeRow]:
    """Parse one `grades/<assignment>.csv` into rows (blank/extra columns tolerated)."""
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        rows.append(GradeRow(**{f: (row.get(f) or "").strip() for f in GRADE_FIELDS}))
    return rows


def gradebook_entry(row: GradeRow) -> dict:
    """One assignment's entry for a student. Group fields appear only for group rows; the
    faculty-internal auto/manual columns are never surfaced (the student sees the authoritative
    final, not the machine/manual split); empty fields are dropped so an individual assignment
    reads as just final + comments."""
    entry: dict[str, str] = {}
    if row.team:
        entry["team"] = row.team
        if row.team_grade:
            entry["team_grade"] = row.team_grade
        if row.adjustment:
            entry["adjustment"] = row.adjustment
        if row.team_comments:
            entry["team_comments"] = row.team_comments
    if row.final:
        entry["final"] = row.final
    if row.comments:
        entry["comments"] = row.comments
    return entry


def build_gradebooks(per_assignment: dict[str, list[GradeRow]]) -> dict[str, dict]:
    """Pivot {assignment: [rows]} into {handle: {student, assignments: {assignment: ...}}}.

    Deterministic: assignments are folded in sorted order so the rendered YAML (and thus
    the preview diff) is stable across runs."""
    books: dict[str, dict] = {}
    for assignment in sorted(per_assignment):
        for row in per_assignment[assignment]:
            if not row.github_handle:
                continue
            book = books.setdefault(
                row.github_handle,
                {"student": row.github_handle, "assignments": {}},
            )
            book["assignments"][assignment] = gradebook_entry(row)
    return books


def render_yaml(book: dict) -> str:
    """Serialise one student's gradebook to YAML text (insertion order preserved)."""
    return yaml.safe_dump(book, sort_keys=False, allow_unicode=True)


def dump_grades(rows: list[GradeRow]) -> str:
    """Serialise grade rows back to CSV text (header + one row per GradeRow)."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(GRADE_FIELDS)
    for r in rows:
        writer.writerow([getattr(r, f) for f in GRADE_FIELDS])
    return out.getvalue()


def render_cohort_csv(per: dict[str, list[GradeRow]]) -> str:
    """Pivot every assignment's raw grade rows into one wide CSV - one row per student,
    one column-group per assignment (sorted) - a faculty-only glance view. Generated,
    never hand-edited; the per-assignment CSVs in GRADES_DIR remain the source of
    truth. Unlike gradebook_entry (student-facing, redacted), this keeps auto/manual/
    team_grade/adjustment too - it never leaves classroom-config."""
    fields = tuple(f for f in GRADE_FIELDS if f != "github_handle")
    assignments = sorted(per)
    by_assignment: dict[str, dict[str, GradeRow]] = {}
    handle_set: set[str] = set()
    for a, rows in per.items():
        by_assignment[a] = {r.github_handle: r for r in rows if r.github_handle}
        handle_set.update(by_assignment[a])
    handles = sorted(handle_set)

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["github_handle"] + [f"{a}_{f}" for a in assignments for f in fields]
    )
    for handle in handles:
        row = [handle]
        for a in assignments:
            r = by_assignment[a].get(handle)
            row.extend(getattr(r, f) if r else "" for f in fields)
        writer.writerow(row)
    return out.getvalue()


def merge_auto(text: str, updates: list[tuple[str, dict[str, str]]]) -> str:
    """Upsert machine-graded fields into a grades CSV, returning new CSV text.

    Each update is (github_handle, {field: value}); the handle's row is updated in place
    (preserving every other column a faculty member has already filled) or created and
    appended if absent. Used by the collector to record `auto` (individual) or
    `team`/`team_grade` (group) without disturbing manual marks, comments, or final."""
    rows = parse_grades(text) if text.strip() else []
    order = [r.github_handle for r in rows]
    by_handle = {r.github_handle: r for r in rows}
    for handle, fields in updates:
        row = by_handle.get(handle)
        if row is None:
            row = GradeRow(github_handle=handle)
            by_handle[handle] = row
            order.append(handle)
        for key, value in fields.items():
            setattr(row, key, value)
    return dump_grades([by_handle[h] for h in order])


# ---------------------------------------------------------------------- gh/git wiring


def load_grade_sources(cohort_org: str) -> dict[str, list[GradeRow]]:
    """Read every `grades/<assignment>.csv` from the cohort's classroom-config repo."""
    code, out = gh(
        "api",
        f"repos/{cohort_org}/{CONFIG_REPO}/contents/{GRADES_DIR}",
        "--jq",
        ".[].name",
    )
    if code != 0:
        log_err(
            f"no {GRADES_DIR}/ in {cohort_org}/{CONFIG_REPO} - add a grade CSV first "
            f"(e.g. {GRADES_DIR}/assignment-1.csv)"
        )
        return {}
    per: dict[str, list[GradeRow]] = {}
    for name in sorted(out.splitlines()):
        if not name.endswith(".csv"):
            continue
        content = get_file_content(cohort_org, CONFIG_REPO, f"{GRADES_DIR}/{name}")
        if content is not None:
            per[name[:-4]] = parse_grades(content)
    return per


def provision_one(cohort_org: str, handle: str) -> str:
    """Ensure a private grades-<handle> repo exists with the student as read collaborator."""
    repo = f"{GRADEBOOK_PREFIX}{handle}"
    existed = repo_exists(cohort_org, repo)
    if existed:
        log_skip(f"gradebook {cohort_org}/{repo}")
    else:
        if not create_repo(
            cohort_org,
            repo,
            private=True,
            description=f"Private gradebook for @{handle}",
        ):
            return "failed-create"
        put_file(
            cohort_org, repo, "README.md", _STARTER_README.encode(), "init gradebook"
        )
        set_repo_topics(cohort_org, repo, ["gradebook"])

    if add_collaborator(cohort_org, repo, handle, permission="pull"):
        log_ok(f"  + @{handle} (read)")
        return "skipped" if existed else "ok"
    log_err(f"  ! could not add @{handle} (not a real account?)")
    return "created-no-collaborator"


def sync(cohort_org: str, dry_run: bool = False) -> int:
    """Provision one private gradebook repo per onboarded student. Idempotent."""
    students = roster.load(cohort_org)
    if not students:
        return 1
    onboarded = [s for s in students if s.onboarded]
    skipped = len(students) - len(onboarded)
    log_step(f"Syncing {len(onboarded)} gradebook repo(s) in {cohort_org}")
    if skipped:
        log(f"  ({skipped} not-yet-onboarded row(s) skipped)")

    results: dict[str, int] = {}
    for s in onboarded:
        if dry_run:
            log(f"    DRY-RUN  {cohort_org}/{GRADEBOOK_PREFIX}{s.github_handle}")
            continue
        status = provision_one(cohort_org, s.github_handle)
        results[status] = results.get(status, 0) + 1
    if dry_run:
        return 0
    log_ok(f"Done - {json.dumps(results)}")
    return 1 if any(k.startswith("failed") for k in results) else 0


def render(cohort_org: str) -> int:
    """Build per-student gradebook YAML and open it as ONE preview PR in classroom-config."""
    per = load_grade_sources(cohort_org)
    if not per:
        return 1
    books = build_gradebooks(per)
    if not books:
        log_err("no graded students found across the grade CSVs.")
        return 1
    log_step(
        f"Rendering {len(books)} gradebook(s) from {len(per)} assignment table(s) "
        f"-> preview PR on {cohort_org}/{CONFIG_REPO}"
    )

    base = get_default_branch(cohort_org, CONFIG_REPO)
    with tempfile.TemporaryDirectory() as work:
        wd = Path(work) / "cfg"
        if (
            gh("repo", "clone", f"{cohort_org}/{CONFIG_REPO}", str(wd), "--", "-q")[0]
            != 0
        ):
            log_err(f"could not clone {cohort_org}/{CONFIG_REPO}")
            return 1
        git("-C", str(wd), *GIT_ENV, "checkout", "-q", "-B", RENDER_BRANCH, base)
        gbdir = wd / GRADEBOOK_DIR
        gbdir.mkdir(exist_ok=True)
        for handle in sorted(books):
            (gbdir / f"{handle}.yml").write_text(render_yaml(books[handle]))
            log_ok(f"+ {GRADEBOOK_DIR}/{handle}.yml")
        (wd / COHORT_CSV_NAME).write_text(render_cohort_csv(per))
        log_ok(f"+ {COHORT_CSV_NAME}")

        git("-C", str(wd), *GIT_ENV, "add", "-A")
        code, _ = git(
            "-C",
            str(wd),
            *GIT_ENV,
            "commit",
            "-q",
            "--no-verify",
            "-m",
            "grades: render gradebooks",
        )
        if code != 0:
            log_ok("nothing new to render (gradebooks already match the source).")
            return 0
        if (
            git("-C", str(wd), *GIT_ENV, "push", "-q", "-f", "origin", RENDER_BRANCH)[0]
            != 0
        ):
            log_err("push failed")
            return 1

    # Open the preview PR (or reuse the open one on this branch).
    title = "Grades: review before distribution"
    body = (
        f"Rendered {len(books)} gradebook(s) from `{GRADES_DIR}/`.\n\n"
        f"**This is the preview.** Review every student's grades in the diff below, then "
        f"merge to distribute to each private `grades-<handle>` repo.\n"
    )
    code, out = gh(
        "pr",
        "create",
        "--repo",
        f"{cohort_org}/{CONFIG_REPO}",
        "--base",
        base,
        "--head",
        RENDER_BRANCH,
        "--title",
        title,
        "--body",
        body,
    )
    if code == 0:
        log_ok(f"preview PR opened: {out.strip().splitlines()[-1]}")
    elif "already exists" in out.lower():
        log_ok("preview PR already open for this branch (updated).")
    else:
        log_err(f"could not open PR: {out[:200]}")
        return 1
    return 0


def distribute(cohort_org: str, notify: bool = True, dry_run: bool = False) -> int:
    """Fan the merged gradebook/<handle>.yml files out into each private grades-<handle>,
    then (unless silenced) email each student a notification to their university inbox.

    Clone classroom-config once and read the files locally (rather than an API GET per
    student); the only per-student call left is the unavoidable write to each repo.

    dry_run pushes nothing and only previews the email notifications (the grade values
    themselves were already previewed in the render PR)."""
    with tempfile.TemporaryDirectory() as work:
        wd = Path(work) / "cfg"
        if (
            gh("repo", "clone", f"{cohort_org}/{CONFIG_REPO}", str(wd), "--", "-q")[0]
            != 0
        ):
            log_err(f"could not clone {cohort_org}/{CONFIG_REPO}")
            return 1
        gbdir = wd / GRADEBOOK_DIR
        files = sorted(gbdir.glob("*.yml")) if gbdir.is_dir() else []
        if not files:
            log_err(
                f"no {GRADEBOOK_DIR}/ in {cohort_org}/{CONFIG_REPO} - run `render` first."
            )
            return 1
        log_step(f"Distributing {len(files)} gradebook(s) in {cohort_org}")

        results: dict[str, int] = {}
        pushed: list[str] = []
        for f in files:
            if dry_run:
                log(f"    DRY-RUN  would update {GRADEBOOK_PREFIX}{f.stem}/grades.yml")
                pushed.append(f.stem)
                continue
            status = _push_gradebook(cohort_org, f.stem, f.read_text())
            results[status] = results.get(status, 0) + 1
            if status == "ok":
                pushed.append(f.stem)
    if dry_run:
        log_ok(f"DRY-RUN previewed {len(pushed)} gradebook update(s) - nothing pushed")
    else:
        log_ok(f"Done - {json.dumps(results)}")

    if notify and pushed:
        _email_updates(cohort_org, pushed, dry_run=dry_run)
    return 0 if dry_run else (1 if any(k.startswith("failed") for k in results) else 0)


def _push_gradebook(cohort_org: str, handle: str, content: str) -> str:
    """Write grades.yml into grades-<handle>. A missing repo (sync not run) -> failed-push."""
    repo = f"{GRADEBOOK_PREFIX}{handle}"
    if not put_file(cohort_org, repo, "grades.yml", content.encode(), "grades: update"):
        return "failed-push"
    log_ok(f"+ {repo}/grades.yml")
    return "ok"


def _email_updates(cohort_org: str, handles: list[str], dry_run: bool = False) -> None:
    """Email each student a 'grades updated' notification to their university inbox,
    linking to their private gradebook repo (the grade's source of truth)."""
    by_handle = {s.github_handle: s for s in roster.load(cohort_org) if s.github_handle}
    messages = []
    for handle in handles:
        student = by_handle.get(handle)
        if not student or not student.hertie_email:
            continue
        url = f"https://github.com/{cohort_org}/{GRADEBOOK_PREFIX}{handle}"
        body = (
            f"Hello {student.name or 'there'},\n\n"
            f"Your grades have been updated. View them in your private gradebook:\n"
            f"  {url}\n"
        )
        messages.append((student.hertie_email, "Your grades have been updated", body))
    if messages:
        mailer.send_bulk(messages, dry_run=dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("sync", "render", "distribute"):
        p = sub.add_parser(name)
        p.add_argument("--cohort-org", required=True)
        if name == "sync":
            p.add_argument("--dry-run", action="store_true")
        if name == "distribute":
            p.add_argument(
                "--no-notify",
                action="store_true",
                help="Skip the email notification (just push the grades).",
            )
            p.add_argument(
                "--dry-run",
                action="store_true",
                help="Preview the grade emails; push nothing, send nothing.",
            )
    args = parser.parse_args()

    if args.action == "sync":
        return sync(args.cohort_org, dry_run=args.dry_run)
    if args.action == "render":
        return render(args.cohort_org)
    return distribute(args.cohort_org, notify=not args.no_notify, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
