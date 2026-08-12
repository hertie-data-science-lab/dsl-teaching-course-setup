"""dsl-course scheduler -- datetime-driven auto-release.

The same idempotent release functions as the manual buttons, fired automatically from the
cohort's own `classroom-config/schedule.yml` `materials_releases:` plan (see
`dsl_course.schedule`). Each labelled release carries a `when` datetime and a mix of
actions - `deploy` (copy a source path from a COURSE-org repo into a COHORT-org repo),
`assignment` (provision one student repo per enrolled student from a template), and
`grade` (run the faculty-side autograder). An hourly cron fires every release whose
`when` has arrived. Because every release is idempotent, re-runs are no-ops and there is
no "already released" state to track. Grading is the exception - see AUTOGRADE below.

Assignment handouts are declared with the rest of the assignment's lifecycle -
`assignments.<slug>.handout_datetime` - and synthesised into releases here
(_handout_releases), so they fire through the exact machinery a deploy does.

The same hourly run also drives each assignment's grading deadline (`grading_datetime`,
else `due_datetime`), whether or not the cohort uses `materials_releases` at all:

1. FREEZE. For every assignment whose grading deadline has gone by and that has no snapshot
   yet, record the commit each submission repo is graded at into
   `classroom-config/snapshots/<slug>.csv` (see `dsl_course.collect`). That timestamp is the
   server's, not the student's, which is the only reason the pin can be trusted.
2. AUTOGRADE, ONCE. Then run the autograder for those same assignments - template
   `<slug>-<tag>` in the course org. The fire-once marker is the `autograde/<slug>/`
   results directory: present means already graded, so never again.

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
    """Entries with something to DO at `now`, in event_datetime order. An assignment
    handout fires at the entry's event_datetime; each deploy at its own deploy_datetime
    (else the event_datetime) - so an entry is due as soon as any one of its actions is.
    Display-only entries (no actions) never fire and are never due. `releases` is already
    sorted (schedule._parse_releases), and every datetime is tz-aware, so the comparisons
    are correct across timezones."""
    return [
        r
        for r in releases
        if r.due_deploys(now)
        or (r.assignment and r.when is not None and r.when <= now)
    ]


def due_snapshots(sched: schedule.Schedule, now: datetime) -> list[tuple[str, str]]:
    """(slug, grading-deadline ISO) for every scheduled assignment whose grading deadline
    (`grading_datetime`, else `due_datetime`) has passed at `now` - the assignments whose
    submissions are ready to be frozen and then graded. Deadline-ordered, so the run log is
    deterministic. Whether each one has already been snapshotted or graded is a separate,
    I/O question (see `_snapshot_passed_deadlines` / `_autograde_passed_deadlines`)."""
    passed = [
        (slug, at)
        for slug in sched.assignments
        if (at := schedule.grading_datetime_at(sched, slug)) is not None and at <= now
    ]
    return [(slug, at.isoformat()) for slug, at in sorted(passed, key=lambda p: p[1])]


def _dest(d: Deploy) -> str:
    return d.dest_path or d.source_path


def describe(release: Release, now: datetime | None = None) -> list[str]:
    """Human one-liners for a release's actions (for dry-run / 'what opens when'). With
    `now`, deploys not yet due (a deploy_datetime after the entry's event_datetime) are
    marked rather than listed as firing."""
    if release.is_event_only:
        return ["calendar event only (site schedule row) - nothing to release"]
    lines: list[str] = []
    for d in release.deploy:
        fire_at = d.deploy_datetime or release.when
        pending = now is not None and (fire_at is None or fire_at > now)
        suffix = (
            f"  (not yet due - deploys {d.deploy_datetime.isoformat()})"
            if pending and d.deploy_datetime
            else ""
        )
        lines.append(
            f"deploy {d.source_repo}/{d.source_path} -> {d.dest_repo}/{_dest(d)}{suffix}"
        )
    actions_pending = now is not None and (release.when is None or release.when > now)
    actions_suffix = (
        f"  (not yet due - fires {release.when.isoformat() if release.when else 'TBC'})"
        if actions_pending
        else ""
    )
    if release.assignment:
        lines.append(f"assignment {release.assignment}{actions_suffix}")
    return lines


# ---------------------------------------------------------------------- gh/git wiring


def _execute_nondeploy(course_org: str, cohort_org: str, release: Release) -> int:
    """Run one release's non-deploy action (an assignment handout). Deploys are batched
    across the whole run (see `run`) so their source/dest repos clone once. Returns the
    error count."""
    errors = 0
    if release.assignment:
        from .assign import provision_all

        # provision_all's default (group=None) resolves group-vs-individual from the
        # cohort schedule / the template's grading.yml - so a scheduled group handout
        # provisions per TEAM, not one repo per student.
        if provision_all(course_org, release.assignment, cohort_org) != 0:
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
    """Autograde every passed-deadline assignment exactly once - zero config. Returns
    (error count, the slugs fired this tick).

    Fire-once: `autograde/<slug>/` in classroom-config is the marker. Absent means never
    machine-graded, so grade now; present means graded already, so never again - which is
    what stops an hourly re-run from recomputing scores a marker has since hand-edited. A
    deliberate re-grade = delete that directory (or use the Grade assignment button).

    A missing template repo, a template with no `solution` branch, and `autograde: false`
    are all skips, not failures: plenty of assignments are hand-marked. Group vs individual
    is not guessed here - `collect` resolves it from the cohort schedule / grading.yml."""
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
    course_org: str, cohort_org: str, due: list[Release], now: datetime
) -> int:
    """Fire every due release's due actions, then sync the site once. Returns the error
    count. `now` gates each action individually: a deploy with its own deploy_datetime
    fires on its own clock, an entry's handout at its event_datetime - an entry can be
    due for one and not (yet) the other."""
    errors = 0
    # Batch EVERY due release's due deploys through one deploy_many: each unique source
    # and dest repo is cloned once for the whole run, not once per copy.
    all_deploys = [d for release in due for d in release.due_deploys(now)]
    deploy_errors, changed = 0, False
    if all_deploys:
        from .release_code import deploy_many

        deploy_errors, changed = deploy_many(
            course_org, cohort_org, all_deploys, sync=False
        )
        errors += deploy_errors

    # Assignment handouts run per release (they aren't file copies).
    did_assign = False
    for release in due:
        if release.assignment and release.when is not None and release.when <= now:
            log_step(f"  [{release.label}] assignment handout")
            errors += _execute_nondeploy(course_org, cohort_org, release)
            did_assign = True

    # One website sync at the end, only if something actually changed.
    if changed or did_assign:
        from . import site

        site.sync_site(course_org, cohort_org)
    return errors


def _handout_releases(
    course_org: str, cohort_org: str, sched: schedule.Schedule
) -> list[Release]:
    """Synthetic releases for `assignments.<slug>.handout_datetime` - the whole assignment
    lifecycle (handout_datetime/due_datetime/grading_datetime/max_team_size) is declared in
    ONE block, and the handout still fires through the exact machinery a
    `materials_releases` entry would: due at its datetime, re-checked every tick
    (idempotent - a late onboarder gets their repo on the next one), per-team when the
    template's grading.yml says so. An assignment with no `<slug>-<tag>` template repo is
    skipped - it may be pinned for its website date alone."""
    out = []
    for slug, entry in sched.assignments.items():
        if entry.handout_datetime is None:
            continue
        template = _assignment_template(course_org, cohort_org, slug)
        if template is None:
            log(f"  [skip] handout {slug} - no template repo for it in {course_org}")
            continue
        out.append(
            Release(
                label=f"{slug}-handout", when=entry.handout_datetime, assignment=template
            )
        )
    return out


def run(course_org: str, cohort_org: str, now: datetime, dry_run: bool = False) -> int:
    sched = schedule.load(cohort_org)
    releases = sched.releases + _handout_releases(course_org, cohort_org, sched)
    due = due_releases(releases, now)
    log_step(
        f"Scheduler {course_org} -> {cohort_org} as of {now.isoformat()}: "
        f"{len(due)}/{len(releases)} release(s) due"
    )

    # Freeze passed deadlines FIRST: server-timed, and before anything grades against the
    # snapshot. Then autograde those same assignments, once each. Both are independent of
    # the release plan - a cohort can pin due dates without scheduling a single release.
    errors = _snapshot_passed_deadlines(cohort_org, sched, now, dry_run)
    autograde_errors, _fired = _autograde_passed_deadlines(
        course_org, cohort_org, sched, now, dry_run
    )
    errors += autograde_errors

    if dry_run:
        for release in due:
            for line in describe(release, now):
                log(f"    DRY-RUN  [{release.label}] {line}")
        return 0

    if not releases:
        log(
            f"  (no materials_releases or assignment handouts in {cohort_org}/"
            f"{schedule.CONFIG_REPO}/{schedule.SCHEDULE_PATH} - {cohort_org} not using "
            f"scheduled release)"
        )
    elif not due:
        log_ok("nothing due.")
    else:
        errors += _run_releases(course_org, cohort_org, due, now)

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
