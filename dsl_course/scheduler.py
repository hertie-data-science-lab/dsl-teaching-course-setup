"""dsl-course scheduler -- datetime-driven auto-release.

The same idempotent release functions as the manual buttons, fired automatically from the
cohort's own `classroom-config/schedule.yml` `materials_releases:` plan (see
`dsl_course.schedule`). Each labelled release carries a `when` datetime and a mix of
actions - `deploy` (copy a source path from a COURSE-org repo into a COHORT-org repo),
`assignment` (provision one student repo per enrolled student from a template), and
`grade` (run the faculty-side autograder). An hourly cron fires every release whose
`when` has arrived. Because every release is idempotent, re-runs are no-ops and there is
no "already released" state to track. Grading is the exception - see AUTOGRADE below.

The same hourly run also drives each assignment's grading deadline (`grading_deadline`, else
`due + grace_days`), whether or not the cohort uses `materials_releases` at all:

1. FREEZE. For every assignment whose grading deadline has gone by and that has no snapshot
   yet, record the commit each submission repo is graded at into
   `classroom-config/snapshots/<slug>.csv` (see `dsl_course.collect`). That timestamp is the
   server's, not the student's, which is the only reason the pin can be trusted.
2. AUTOGRADE, ONCE. Then run the autograder for those same assignments - template
   `<slug>-<tag>` in the course org - so no `grade:` entry has to be written at all. The
   fire-once marker is the `autograde/<slug>/` results directory: present means already
   graded, so never again. Both phases run before the release actions, so a legacy `grade:`
   release firing in the same tick sees the snapshot AND shares the marker (it cannot
   double-fire).

Sources are always read from the course org and destinations always written to the cohort
org - the two orgs come from the invocation (`--course-org` / `--cohort-org`), never from
the schedule, which names repos only.

Usage (the cron passes the course org and iterates its cohorts; --now is for testing):
    python3 -m dsl_course.scheduler --course-org COURSE --all-cohorts
    python3 -m dsl_course.scheduler --course-org COURSE --cohort-org COHORT --dry-run
    python3 -m dsl_course.scheduler --course-org COURSE --cohort-org COHORT --now 2026-09-15T14:00
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from . import schedule
from .schedule import Deploy, Release
from .utils import log, log_err, log_ok, log_step


# --------------------------------------------------------------------------- pure core


def due_releases(releases: list[Release], now: datetime) -> list[Release]:
    """Releases whose `when` has arrived (<= now), in `when` order. `releases` is already
    sorted by `when` (schedule._parse_releases), and `now`/`when` are both tz-aware, so
    the comparison is correct across timezones."""
    return [r for r in releases if r.when <= now]


def due_snapshots(sched: schedule.Schedule, now: datetime) -> list[tuple[str, str]]:
    """(slug, grading-deadline ISO) for every scheduled assignment whose grading deadline
    (`grading_deadline`, else due + grace_days) has passed at `now` - the assignments whose
    submissions are ready to be frozen and then graded. Deadline-ordered, so the run log is
    deterministic. Whether each one has already been snapshotted or graded is a separate,
    I/O question (see `_snapshot_passed_deadlines` / `_autograde_passed_deadlines`)."""
    passed = [
        (slug, at)
        for slug in sched.assignments
        if (at := schedule.grading_deadline_at(sched, slug)) is not None and at <= now
    ]
    return [(slug, at.isoformat()) for slug, at in sorted(passed, key=lambda p: p[1])]


def _dest(d: Deploy) -> str:
    return d.dest_path or d.source_path


def describe(release: Release) -> list[str]:
    """Human one-liners for a release's actions (for dry-run / 'what opens when')."""
    lines: list[str] = []
    for d in release.deploy:
        lines.append(
            f"deploy {d.source_repo}/{d.source_path} -> {d.dest_repo}/{_dest(d)}"
        )
    if release.assignment:
        lines.append(f"assignment {release.assignment}")
    if release.grade:
        lines.append(
            f"grade {release.grade.template} "
            f"(deadline {release.grade.deadline or 'from schedule'})"
        )
    return lines


# ---------------------------------------------------------------------- gh/git wiring


def _execute_nondeploy(
    course_org: str,
    cohort_org: str,
    release: Release,
    graded: frozenset[str] | set[str] = frozenset(),
) -> int:
    """Run one release's non-deploy actions (assignment / grade). Deploys are batched
    across the whole run (see `run`) so their source/dest repos clone once. Returns the
    error count.

    A legacy `grade:` entry shares the automatic path's fire-once marker: it is skipped once
    `autograde/<slug>/` exists, and `graded` (the slugs this tick already autograded) closes
    the window before that freshly written marker is readable."""
    errors = 0
    if release.assignment:
        from .assign import provision_all

        if provision_all(course_org, release.assignment, cohort_org) != 0:
            errors += 1
    if release.grade:
        from .assign import assignment_slug
        from .collect import autograde_path, collect, has_autograde_results

        slug = assignment_slug(release.grade.template)
        if slug in graded or has_autograde_results(cohort_org, slug):
            log(
                f"  [skip] grade {slug} - {autograde_path(slug)}/ already recorded "
                f"(delete it to re-grade)"
            )
            return errors
        # deadline=None -> collect resolves it from the cohort schedule (SSOT)
        deadline = (
            release.grade.deadline.isoformat() if release.grade.deadline else None
        )
        if (
            collect(
                course_org,
                release.grade.template,
                cohort_org,
                deadline,
                group=release.grade.group,
            )
            != 0
        ):
            errors += 1
    return errors


def _snapshot_passed_deadlines(
    cohort_org: str, sched: schedule.Schedule, now: datetime, dry_run: bool
) -> int:
    """Freeze every passed-deadline assignment that has no snapshot yet. Write-once: an
    assignment already frozen is skipped silently, so this is a no-op on every tick after
    the first. Returns the error count."""
    from .collect import load_snapshots, snapshot_assignment, snapshot_path

    errors = 0
    for slug, deadline in due_snapshots(sched, now):
        if load_snapshots(cohort_org, slug) is not None:
            continue  # already frozen - never re-snapshot, a late push must not move it
        if dry_run:
            log(f"    DRY-RUN  snapshot {snapshot_path(slug)} (deadline {deadline})")
            continue
        log_step(f"  snapshot {slug} (deadline {deadline})")
        if not snapshot_assignment(cohort_org, slug, deadline):
            errors += 1
    return errors


def _assignment_template(course_org: str, cohort_org: str, slug: str) -> str | None:
    """The course-org template repo backing `slug` for this cohort: `<slug>-<tag>`, where
    `<tag>` is the cohort org's own fYYYY/sYYYY suffix. None when the tag can't be read or
    no such repo exists - an assignment can be pinned in `assignments:` for its website date
    alone, with no template behind it, so that is a skip and not an error."""
    from .site import _cohort_tag
    from .utils import repo_exists

    tag = _cohort_tag(cohort_org)
    if tag is None:
        return None
    template = f"{slug}-{tag}"
    return template if repo_exists(course_org, template) else None


def _autograde_passed_deadlines(
    course_org: str,
    cohort_org: str,
    sched: schedule.Schedule,
    now: datetime,
    dry_run: bool,
) -> tuple[int, set[str]]:
    """Autograde every passed-deadline assignment exactly once - zero config, no `grade:`
    entry needed. Returns (error count, the slugs fired this tick).

    Fire-once: `autograde/<slug>/` in classroom-config is the marker. Absent means never
    machine-graded, so grade now; present means graded already, so never again - which is
    what stops an hourly re-run from recomputing scores a marker has since hand-edited. A
    deliberate re-grade = delete that directory (or use the Grade assignment button).

    A missing template repo, a template with no `solution` branch, and `autograde: false`
    are all skips, not failures: plenty of assignments are hand-marked. Group vs individual
    is not guessed here - `collect` reads `type:` from the template's own grading.yml."""
    from .collect import collect, has_autograde_results

    errors, fired = 0, set()
    for slug, deadline in due_snapshots(sched, now):
        if has_autograde_results(cohort_org, slug):
            continue  # already machine-graded - re-grading is a deliberate act
        template = _assignment_template(course_org, cohort_org, slug)
        if template is None:
            log(f"  [skip] autograde {slug} - no template repo for it in {course_org}")
            continue
        if dry_run:
            log(f"    DRY-RUN  autograde {slug} via {template} (deadline {deadline})")
            continue
        log_step(f"  autograde {slug} via {template} (deadline {deadline})")
        fired.add(slug)  # fired, pass or fail - never twice in one tick
        if collect(course_org, template, cohort_org, deadline) != 0:
            errors += 1
    return errors, fired


def _run_releases(
    course_org: str, cohort_org: str, due: list[Release], graded: set[str]
) -> int:
    """Fire every due release's actions, then sync the site once. Returns the error count."""
    errors = 0
    # Batch EVERY due release's deploys through one deploy_many: each unique source and
    # dest repo is cloned once for the whole run, not once per copy.
    all_deploys = [d for release in due for d in release.deploy]
    deploy_errors, changed = 0, False
    if all_deploys:
        from .release_code import deploy_many

        deploy_errors, changed = deploy_many(
            course_org, cohort_org, all_deploys, sync=False
        )
        errors += deploy_errors

    # Assignment / grade actions run per release (they aren't file copies).
    did_assign = False
    for release in due:
        if release.assignment or release.grade:
            log_step(f"  [{release.label}] assignment/grade")
            errors += _execute_nondeploy(course_org, cohort_org, release, graded)
            did_assign = did_assign or bool(release.assignment)

    # One website sync at the end, only if something actually changed.
    if changed or did_assign:
        from . import site

        site.sync_site(course_org, cohort_org)
    return errors


def run(course_org: str, cohort_org: str, now: datetime, dry_run: bool = False) -> int:
    sched = schedule.load(cohort_org)
    due = due_releases(sched.releases, now)
    log_step(
        f"Scheduler {course_org} -> {cohort_org} as of {now.isoformat()}: "
        f"{len(due)}/{len(sched.releases)} release(s) due"
    )

    # Freeze passed deadlines FIRST: server-timed, and before anything grades against the
    # snapshot. Then autograde those same assignments, once each. Both are independent of
    # the release plan - a cohort can pin due dates without scheduling a single release.
    errors = _snapshot_passed_deadlines(cohort_org, sched, now, dry_run)
    autograde_errors, graded = _autograde_passed_deadlines(
        course_org, cohort_org, sched, now, dry_run
    )
    errors += autograde_errors

    if dry_run:
        for release in due:
            for line in describe(release):
                log(f"    DRY-RUN  [{release.label}] {line}")
        return 0

    if not sched.releases:
        log(
            f"  (no materials_releases in {cohort_org}/{schedule.CONFIG_REPO}/"
            f"{schedule.SCHEDULE_PATH} - {cohort_org} not using scheduled release)"
        )
    elif not due:
        log_ok("nothing due.")
    else:
        errors += _run_releases(course_org, cohort_org, due, graded)

    if errors:
        log_err(f"{errors} action(s) failed")
        return 1
    log_ok("scheduler run complete")
    return 0


def _parse_now(raw: str | None) -> datetime:
    """Parse --now (ISO date or datetime) to a tz-aware moment; default is now (UTC). A
    naive value is treated as UTC - release/due datetimes carry their own zones, so the
    comparison stays correct."""
    if not raw:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--course-org", required=True, help="Course org (source of every release)"
    )
    parser.add_argument(
        "--cohort-org", default=None, help="One cohort; omit and use --all-cohorts"
    )
    parser.add_argument(
        "--all-cohorts",
        action="store_true",
        help="Run every cohort registered with the course org (the hourly cron).",
    )
    parser.add_argument(
        "--now", default=None, help="Override 'now' (ISO date/datetime) - for testing."
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    now = _parse_now(args.now)

    if args.all_cohorts:
        from .seed import discover_cohorts

        cohorts = discover_cohorts(args.course_org)
        if not cohorts:
            # A freshly bootstrapped course org has this cron installed before any
            # cohort is registered - that gap is normal, not an hourly failure.
            log(
                f"  [skip] no cohorts registered with {args.course_org}; "
                "nothing to release."
            )
            return 0
        rc = 0
        for cohort in cohorts:
            rc |= run(args.course_org, cohort, now, dry_run=args.dry_run)
        return rc

    if not args.cohort_org:
        log_err("pass --cohort-org or --all-cohorts.")
        return 1
    return run(args.course_org, args.cohort_org, now, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
