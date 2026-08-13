"""scheduler pure core: due_releases (datetime, timezone-correct) + _execute()'s dispatch
to the release functions - monkeypatched so a schema<->signature mismatch (the class of bug
that silently broke scheduled releases once) is caught without any real gh/git I/O. Plus the
deadline-driven phases (snapshot, then fire-once autograde) and a renderer guard (the cron is
hourly and has NO check-team gate - scheduled runs have no actor).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from dsl_course import collect, deploy, scheduler, seed
from dsl_course.schedule import AssignmentEntry, Deploy, Release, Schedule

BERLIN = ZoneInfo("Europe/Berlin")
WHEN = datetime(2026, 9, 15, 14, 0, tzinfo=BERLIN)


def _r(label: str, when: datetime, **kw) -> Release:
    return Release(label=label, when=when, **kw)


def _sched_with(releases: list[Release]) -> Schedule:
    return Schedule(releases=releases)


def test_due_releases_in_when_order():
    releases = sorted(
        [
            _r("b", datetime(2026, 9, 15, 14, 0, tzinfo=BERLIN), assignment="x"),
            _r("a", datetime(2026, 9, 1, 9, 0, tzinfo=BERLIN), assignment="x"),
            _r("c", datetime(2026, 9, 29, 9, 0, tzinfo=BERLIN), assignment="x"),
        ],
        key=lambda r: r.when,
    )
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    assert [r.label for r in scheduler.due_releases(releases, now)] == ["a", "b"]
    assert scheduler.due_releases(releases, datetime(2026, 8, 1, tzinfo=timezone.utc)) == []
    assert len(scheduler.due_releases(releases, datetime(2026, 12, 1, tzinfo=timezone.utc))) == 3


def test_due_releases_honours_time_of_day_across_timezones():
    # 14:00 Europe/Berlin (CEST) == 12:00 UTC. At 11:00 UTC not yet due; at 13:00 UTC due.
    r = _r("s", datetime(2026, 9, 15, 14, 0, tzinfo=BERLIN), assignment="x")
    assert scheduler.due_releases([r], datetime(2026, 9, 15, 11, 0, tzinfo=timezone.utc)) == []
    assert scheduler.due_releases([r], datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)) == [r]


def test_display_only_entries_are_never_due():
    # An event_datetime with no actions is a site schedule row, not work - the scheduler
    # must never consider it due, no matter how far past its datetime we are.
    r = _r("project-clinic", datetime(2026, 9, 15, 10, 0, tzinfo=BERLIN))
    assert r.is_event_only
    assert scheduler.due_releases([r], datetime(2026, 12, 1, tzinfo=timezone.utc)) == []


def test_deploy_datetime_fires_on_its_own_clock():
    # The class is announced for 10:00 (event_datetime); its materials carry a
    # deploy_datetime an hour earlier. The deploy is due at 09:00, before the entry's
    # own datetime - and a second copy without an override still waits for 10:00.
    early = Deploy(
        "cm-f2026",
        "lectures/02_intro",
        "materials",
        None,
        deploy_datetime=datetime(2026, 9, 15, 9, 0, tzinfo=BERLIN),
    )
    at_class = Deploy("cm-f2026", "readings/02_intro", "materials", None)
    r = _r("session-2", datetime(2026, 9, 15, 10, 0, tzinfo=BERLIN), deploy=[early, at_class])
    between = datetime(2026, 9, 15, 7, 30, tzinfo=timezone.utc)  # 09:30 Berlin
    assert scheduler.due_releases([r], between) == [r]
    assert r.due_deploys(between) == [early]
    after = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)  # 11:00 Berlin
    assert r.due_deploys(after) == [early, at_class]


def test_describe_marks_not_yet_due_actions():
    # Dry-run legibility: an entry due only for its early deploy must not read as if the
    # handout (or a later deploy) were firing now.
    early = Deploy(
        "cm-f2026",
        "lectures/02_intro",
        "materials",
        None,
        deploy_datetime=datetime(2026, 9, 15, 9, 0, tzinfo=BERLIN),
    )
    r = _r(
        "session-2",
        datetime(2026, 9, 15, 10, 0, tzinfo=BERLIN),
        deploy=[early],
        assignment="assignment-1-f2026",
    )
    lines = scheduler.describe(r, datetime(2026, 9, 15, 7, 30, tzinfo=timezone.utc))
    deploy_line = next(ln for ln in lines if ln.startswith("deploy "))
    assert "not yet due" not in deploy_line  # the early deploy IS firing
    assignment_line = next(ln for ln in lines if ln.startswith("assignment "))
    assert "not yet due" in assignment_line


def test_describe_lists_every_action():
    r = _r(
        "s2",
        WHEN,
        deploy=[
            Deploy("cm-f2026", "lectures/02_intro", "materials", None),
            Deploy("data-f2026", "w7/housing.csv", "materials", "datasets/housing.csv"),
        ],
        assignment="assignment-1-f2026",
    )
    lines = scheduler.describe(r)
    assert any("cm-f2026/lectures/02_intro -> materials/lectures/02_intro" in ln for ln in lines)
    assert any("materials/datasets/housing.csv" in ln for ln in lines)
    assert any(ln.startswith("assignment ") for ln in lines)


# _execute_nondeploy() and the deploy batching ARE pure wiring (no gh/git of their own),
# but a schema<->signature mismatch is exactly the class of bug that silently broke
# scheduled releases - monkeypatching the release functions catches it without real I/O.


def test_run_batches_all_deploys_through_deploy_many(monkeypatch):
    # The clone-once win: every due release's deploys go through ONE deploy_many call
    # (which clones each source/dest once), not one call per copy. deploy_many is now the
    # single executor for both paths - the manual Release materials button batches its
    # comma-separated paths through the same call (see test_release.py).
    calls = []
    monkeypatch.setattr(
        "dsl_course.deploy.deploy_many",
        lambda source_org, cohort_org, deploys, sync=True: calls.append(
            (source_org, cohort_org, list(deploys), sync)
        )
        or (0, True),
    )
    monkeypatch.setattr(scheduler.schedule, "load", lambda cohort: _sched_with(
        [
            _r("w1", datetime(2026, 9, 1, tzinfo=BERLIN), deploy=[
                Deploy("cm", "lectures/00_x", "lectures", None),
                Deploy("cm", "labs/00_y", "labs", None),
            ]),
            _r("w2", datetime(2026, 9, 8, tzinfo=BERLIN), deploy=[
                Deploy("cm", "lectures/01_z", "lectures", None),
            ]),
        ]
    ))
    synced = []
    monkeypatch.setattr("dsl_course.site.sync_site", lambda c, o: synced.append((c, o)) or 0)
    now = datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert scheduler.run("Course-Org", "Cohort-Org", now) == 0
    # exactly ONE deploy_many call, carrying all 3 deploys across both releases, sync=False
    assert len(calls) == 1
    source_org, cohort_org, deploys, sync = calls[0]
    assert (source_org, cohort_org, sync) == ("Course-Org", "Cohort-Org", False)
    assert len(deploys) == 3
    # the scheduler syncs the site exactly once, itself (deploy_many was told not to)
    assert synced == [("Course-Org", "Cohort-Org")]


def test_execute_nondeploy_assignment_calls_provision_all(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dsl_course.assign.provision_all",
        lambda master_org, template, cohort_org: calls.append(
            (master_org, template, cohort_org)
        )
        or 0,
    )
    r = _r("s", WHEN, assignment="assignment-2-f2026")
    assert scheduler._execute_nondeploy("Course-Org", "Cohort-Org", r) == 0
    assert calls[0] == ("Course-Org", "assignment-2-f2026", "Cohort-Org")


def test_deploy_many_clones_each_repo_once(monkeypatch):
    # The optimisation: 3 deploys from one source into two dests clone the source ONCE
    # and each dest ONCE (3 clones total), not once per copy (6).
    clones = []

    def fake_gh(*args):
        if args[:2] == ("repo", "clone"):
            spec, dest = args[2], args[3]
            clones.append(spec)
            p = Path(dest)
            p.mkdir(parents=True, exist_ok=True)
            if spec.startswith("Course-Org/"):  # source repo: seed the paths deploys read
                for sp in ("lectures/00_x", "labs/00_y", "lectures/01_z"):
                    d = p / sp
                    d.mkdir(parents=True, exist_ok=True)
                    (d / "f.txt").write_text("x")
            return (0, "")
        return (0, "")

    monkeypatch.setattr(deploy, "gh", fake_gh)
    monkeypatch.setattr(deploy, "git", lambda *a: (0, ""))  # commit + push succeed
    monkeypatch.setattr(deploy, "create_repo", lambda *a, **k: True)
    monkeypatch.setattr(deploy, "grant_read_teams", lambda *a, **k: None)

    deploys = [
        Deploy("cm", "lectures/00_x", "lectures", None),
        Deploy("cm", "labs/00_y", "labs", None),
        Deploy("cm", "lectures/01_z", "lectures", None),
    ]
    errors, changed = deploy.deploy_many("Course-Org", "Cohort-Org", deploys, sync=False)
    assert (errors, changed) == (0, True)
    assert clones.count("Course-Org/cm") == 1  # source cloned once for all 3 copies
    assert clones.count("Cohort-Org/lectures") == 1
    assert clones.count("Cohort-Org/labs") == 1
    assert len(clones) == 3  # 1 source + 2 dests, not 6


def test_deploy_many_missing_source_path_is_an_error_not_silent(monkeypatch):
    # A wrong source_path must be a loud error (return count), never a silent no-op.
    def fake_gh(*args):
        if args[:2] == ("repo", "clone"):
            Path(args[3]).mkdir(parents=True, exist_ok=True)  # empty clones
            return (0, "")
        return (0, "")

    monkeypatch.setattr(deploy, "gh", fake_gh)
    monkeypatch.setattr(deploy, "git", lambda *a: (0, ""))
    monkeypatch.setattr(deploy, "create_repo", lambda *a, **k: True)
    monkeypatch.setattr(deploy, "grant_read_teams", lambda *a, **k: None)

    errors, changed = deploy.deploy_many(
        "Course-Org", "Cohort-Org", [Deploy("cm", "lectures/does-not-exist", "materials", None)], sync=False
    )
    assert errors == 1 and changed is False


def _clone_failing(*failing: str):
    """A fake gh where cloning any repo in `failing` fails; others clone empty."""

    def fake_gh(*args):
        if args[:2] == ("repo", "clone"):
            if args[2] in failing:
                return (1, "boom")
            Path(args[3]).mkdir(parents=True, exist_ok=True)
            return (0, "")
        return (0, "")

    return fake_gh


def _no_io(monkeypatch, fake_gh):
    monkeypatch.setattr(deploy, "gh", fake_gh)
    monkeypatch.setattr(deploy, "git", lambda *a: (0, ""))
    monkeypatch.setattr(deploy, "create_repo", lambda *a, **k: True)
    monkeypatch.setattr(deploy, "grant_read_teams", lambda *a, **k: None)


def test_deploy_many_counts_a_doomed_deploy_once(monkeypatch):
    # Source AND dest clone both fail: that is ONE copy lost, not two errors (a
    # double-count made `deploy` report 2 failures for a single deploy).
    _no_io(monkeypatch, _clone_failing("Course-Org/cm", "Cohort-Org/materials"))
    errors, changed = deploy.deploy_many(
        "Course-Org",
        "Cohort-Org",
        [Deploy("cm", "lectures/00_x", "materials", None)],
        sync=False,
    )
    assert (errors, changed) == (1, False)


def test_deploy_many_counts_each_unrunnable_deploy_once(monkeypatch):
    # 3 deploys: the shared source fails AND one dest fails - still 3 lost copies.
    _no_io(monkeypatch, _clone_failing("Course-Org/cm", "Cohort-Org/labs"))
    deploys = [
        Deploy("cm", "lectures/00_x", "lectures", None),
        Deploy("cm", "labs/00_y", "labs", None),
        Deploy("cm", "lectures/01_z", "lectures", None),
    ]
    assert deploy.deploy_many(
        "Course-Org", "Cohort-Org", deploys, sync=False
    ) == (3, False)


# ------------------------------------------------------------- deadline snapshots
# The hourly cron is what makes the grading pin trustworthy: it freezes each assignment's
# commits at a moment the SERVER chose, because committer dates are client-supplied. So the
# trigger condition (deadline passed, not yet frozen) and its write-once-ness are the logic
# that matters here.


def _assignments(**entries: AssignmentEntry) -> Schedule:
    return Schedule(assignments=dict(entries))


def _due(day: int, grading_day: int | None = None) -> AssignmentEntry:
    return AssignmentEntry(
        due_datetime=datetime(2026, 10, day, 23, 59, 59, tzinfo=BERLIN),
        grading_datetime=(
            datetime(2026, 10, grading_day, 23, 59, 59, tzinfo=BERLIN)
            if grading_day is not None
            else None
        ),
    )


def test_due_snapshots_only_passed_deadlines_in_deadline_order():
    sched = _assignments(
        **{
            "assignment-2": _due(20),
            "assignment-1": _due(13),
            "assignment-3": _due(30),
        }
    )
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    assert [slug for slug, _dl in scheduler.due_snapshots(sched, now)] == [
        "assignment-1",
        "assignment-2",
    ]


def test_due_snapshots_uses_the_explicit_grading_datetime_when_set():
    # grading_datetime wins over due_datetime, and snapshot + autograde must agree on it.
    sched = _assignments(**{"assignment-1": _due(13, grading_day=15)})
    assert scheduler.due_snapshots(sched, datetime(2026, 10, 14, tzinfo=timezone.utc)) == []
    (slug, deadline), = scheduler.due_snapshots(
        sched, datetime(2026, 10, 16, tzinfo=timezone.utc)
    )
    assert slug == "assignment-1"
    assert deadline.startswith("2026-10-15T23:59:59")


def test_due_snapshots_empty_without_assignments():
    assert scheduler.due_snapshots(Schedule(), datetime(2030, 1, 1, tzinfo=timezone.utc)) == []


def _stub_autograde(monkeypatch, marked: bool = True):
    """Neutralise the autograde phase's I/O (it shares due_snapshots with the snapshot
    phase). `marked` = every slug already has its autograde/<slug>/ marker, so nothing
    fires."""
    monkeypatch.setattr(collect, "has_autograde_results", lambda org, slug: marked)
    monkeypatch.setattr(scheduler, "_assignment_template", lambda c, o, slug: None)


def _stub_snapshots(monkeypatch, existing: set[str]):
    """Track snapshot_assignment calls; `existing` are the slugs already frozen."""
    taken: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        collect, "load_snapshots", lambda org, slug: {} if slug in existing else None
    )
    monkeypatch.setattr(
        collect,
        "snapshot_assignment",
        lambda org, slug, deadline: taken.append((org, slug, deadline)) or True,
    )
    _stub_autograde(monkeypatch)
    return taken


def test_run_snapshots_a_passed_deadline_that_has_no_snapshot_yet(monkeypatch):
    taken = _stub_snapshots(monkeypatch, existing=set())
    monkeypatch.setattr(
        scheduler.schedule, "load", lambda cohort: _assignments(**{"assignment-1": _due(13)})
    )
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    assert scheduler.run("Course-Org", "Cohort-Org", now) == 0
    org, slug, deadline = taken[0]
    assert (org, slug) == ("Cohort-Org", "assignment-1")
    assert deadline.startswith("2026-10-13T23:59:59")


def test_run_never_re_snapshots_an_assignment_already_frozen(monkeypatch):
    # Idempotence is the integrity property: re-freezing hourly would let a late push
    # (backdated) replace the commit that was recorded at the deadline.
    taken = _stub_snapshots(monkeypatch, existing={"assignment-1"})
    monkeypatch.setattr(
        scheduler.schedule, "load", lambda cohort: _assignments(**{"assignment-1": _due(13)})
    )
    assert scheduler.run("Course-Org", "Cohort-Org", datetime(2026, 12, 1, tzinfo=timezone.utc)) == 0
    assert taken == []


def test_run_does_not_snapshot_before_the_deadline_passes(monkeypatch):
    taken = _stub_snapshots(monkeypatch, existing=set())
    monkeypatch.setattr(
        scheduler.schedule, "load", lambda cohort: _assignments(**{"assignment-1": _due(13)})
    )
    assert scheduler.run("Course-Org", "Cohort-Org", datetime(2026, 10, 1, tzinfo=timezone.utc)) == 0
    assert taken == []


def test_run_snapshots_even_with_no_releases(monkeypatch):
    # A cohort can pin due dates without using the auto-release plan at all - the old
    # early-return on `not sched.releases` would have skipped its snapshots forever.
    taken = _stub_snapshots(monkeypatch, existing=set())
    monkeypatch.setattr(
        scheduler.schedule, "load", lambda cohort: _assignments(**{"assignment-1": _due(13)})
    )
    assert scheduler.run("Course-Org", "Cohort-Org", datetime(2026, 11, 1, tzinfo=timezone.utc)) == 0
    assert [slug for _org, slug, _dl in taken] == ["assignment-1"]


def test_run_dry_run_snapshots_nothing(monkeypatch):
    taken = _stub_snapshots(monkeypatch, existing=set())
    monkeypatch.setattr(
        scheduler.schedule, "load", lambda cohort: _assignments(**{"assignment-1": _due(13)})
    )
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert scheduler.run("Course-Org", "Cohort-Org", now, dry_run=True) == 0
    assert taken == []


def test_run_reports_a_failed_snapshot(monkeypatch):
    monkeypatch.setattr(collect, "load_snapshots", lambda org, slug: None)
    monkeypatch.setattr(collect, "snapshot_assignment", lambda org, slug, deadline: False)
    _stub_autograde(monkeypatch)
    monkeypatch.setattr(
        scheduler.schedule, "load", lambda cohort: _assignments(**{"assignment-1": _due(13)})
    )
    assert scheduler.run("Course-Org", "Cohort-Org", datetime(2026, 11, 1, tzinfo=timezone.utc)) == 1


# ------------------------------------------------------- fire-once autograding
# Autograding is zero-config: every assignment with a passed grading deadline is graded on
# the next tick, exactly once. The marker is the autograde/<slug>/ results directory - so
# what matters is that a present marker stops the run dead (an hourly re-grade would
# recompute over a marker's hand-edits).


def test_assignment_template_is_slug_plus_the_cohort_tag(monkeypatch):
    monkeypatch.setattr(
        "dsl_course.utils.repo_exists",
        lambda org, repo: repo == "assignment-1-f2026",
    )
    assert (
        scheduler._assignment_template("Course-Org", "DSL-Demo-f2026", "assignment-1")
        == "assignment-1-f2026"
    )
    # no such repo in the course org -> nothing to grade against
    assert scheduler._assignment_template("Course-Org", "DSL-Demo-f2026", "assignment-9") is None
    # an untagged cohort org names no template - skip rather than guess
    assert scheduler._assignment_template("Course-Org", "Cohort-Org", "assignment-1") is None


def _stub_collect(monkeypatch, marked: set[str], templates: set[str], rc: int = 0):
    """Record collect() calls. `marked` = slugs whose autograde/<slug>/ already exists;
    `templates` = the template repos that exist in the course org."""
    graded: list[tuple[str, str, str, str, bool]] = []
    monkeypatch.setattr(collect, "has_autograde_results", lambda org, slug: slug in marked)
    monkeypatch.setattr(
        scheduler,
        "_assignment_template",
        lambda course, cohort, slug: (
            t if (t := f"{slug}-f2026") in templates else None
        ),
    )
    monkeypatch.setattr(
        "dsl_course.collect.collect",
        lambda m, t, c, deadline=None, group=False: graded.append(
            (m, t, c, deadline, group)
        )
        or rc,
    )
    return graded


def _only_snapshots_taken(monkeypatch):
    """Snapshots always succeed and are never the subject of these tests."""
    monkeypatch.setattr(collect, "load_snapshots", lambda org, slug: {})
    monkeypatch.setattr(collect, "snapshot_assignment", lambda org, slug, dl: True)


def test_run_autogrades_a_passed_deadline_with_no_marker(monkeypatch):
    _only_snapshots_taken(monkeypatch)
    graded = _stub_collect(monkeypatch, marked=set(), templates={"assignment-1-f2026"})
    monkeypatch.setattr(
        scheduler.schedule, "load", lambda cohort: _assignments(**{"assignment-1": _due(13)})
    )
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    assert scheduler.run("Course-Org", "Cohort-f2026", now) == 0
    (course, template, cohort, deadline, group), = graded
    assert (course, template, cohort) == ("Course-Org", "assignment-1-f2026", "Cohort-f2026")
    # graded at exactly the instant the snapshot froze, and never guessed as a group run
    assert deadline.startswith("2026-10-13T23:59:59") and group is False


def test_run_never_autogrades_twice_the_marker_is_the_state(monkeypatch):
    _only_snapshots_taken(monkeypatch)
    graded = _stub_collect(
        monkeypatch, marked={"assignment-1"}, templates={"assignment-1-f2026"}
    )
    monkeypatch.setattr(
        scheduler.schedule, "load", lambda cohort: _assignments(**{"assignment-1": _due(13)})
    )
    assert scheduler.run("Course-Org", "Cohort-f2026", datetime(2026, 12, 1, tzinfo=timezone.utc)) == 0
    assert graded == []


def test_run_does_not_autograde_before_the_grading_deadline(monkeypatch):
    _only_snapshots_taken(monkeypatch)
    graded = _stub_collect(monkeypatch, marked=set(), templates={"assignment-1-f2026"})
    monkeypatch.setattr(
        scheduler.schedule,
        "load",
        lambda cohort: _assignments(**{"assignment-1": _due(13, grading_day=15)}),
    )
    assert scheduler.run("Course-Org", "Cohort-f2026", datetime(2026, 10, 14, tzinfo=timezone.utc)) == 0
    assert graded == []


def test_run_skips_an_assignment_with_no_template_repo(monkeypatch):
    # A due date can be pinned for the website alone, with no template behind it - a skip,
    # never a red run.
    _only_snapshots_taken(monkeypatch)
    graded = _stub_collect(monkeypatch, marked=set(), templates=set())
    monkeypatch.setattr(
        scheduler.schedule, "load", lambda cohort: _assignments(**{"reading-week": _due(13)})
    )
    assert scheduler.run("Course-Org", "Cohort-f2026", datetime(2026, 11, 1, tzinfo=timezone.utc)) == 0
    assert graded == []


def test_run_treats_a_non_autogradable_template_as_a_skip(monkeypatch):
    # collect() itself returns 0 for "no solution branch" / `autograde: false` - the
    # scheduler must pass that through as success, not count it as a failed action.
    _only_snapshots_taken(monkeypatch)
    graded = _stub_collect(
        monkeypatch, marked=set(), templates={"assignment-1-f2026"}, rc=0
    )
    monkeypatch.setattr(
        scheduler.schedule, "load", lambda cohort: _assignments(**{"assignment-1": _due(13)})
    )
    assert scheduler.run("Course-Org", "Cohort-f2026", datetime(2026, 11, 1, tzinfo=timezone.utc)) == 0
    assert len(graded) == 1


def test_run_reports_a_failed_autograde(monkeypatch):
    _only_snapshots_taken(monkeypatch)
    _stub_collect(monkeypatch, marked=set(), templates={"assignment-1-f2026"}, rc=1)
    monkeypatch.setattr(
        scheduler.schedule, "load", lambda cohort: _assignments(**{"assignment-1": _due(13)})
    )
    assert scheduler.run("Course-Org", "Cohort-f2026", datetime(2026, 11, 1, tzinfo=timezone.utc)) == 1


def test_run_dry_run_autogrades_nothing(monkeypatch):
    _only_snapshots_taken(monkeypatch)
    graded = _stub_collect(monkeypatch, marked=set(), templates={"assignment-1-f2026"})
    monkeypatch.setattr(
        scheduler.schedule, "load", lambda cohort: _assignments(**{"assignment-1": _due(13)})
    )
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert scheduler.run("Course-Org", "Cohort-f2026", now, dry_run=True) == 0
    assert graded == []


def test_run_autogrades_at_the_explicit_grading_deadline(monkeypatch):
    # `grading_datetime` overrides `due_datetime`, and snapshot + autograde must agree on
    # that one instant.
    _only_snapshots_taken(monkeypatch)
    graded = _stub_collect(monkeypatch, marked=set(), templates={"assignment-1-f2026"})
    entry = AssignmentEntry(
        due_datetime=datetime(2026, 10, 13, 23, 59, 59, tzinfo=BERLIN),
        grading_datetime=datetime(2026, 10, 15, 23, 59, 59, tzinfo=BERLIN),
    )
    monkeypatch.setattr(
        scheduler.schedule, "load", lambda cohort: _assignments(**{"assignment-1": entry})
    )
    # past grading_datetime (10-15) but well before what due_datetime alone would imply
    assert scheduler.run("Course-Org", "Cohort-f2026", datetime(2026, 10, 16, tzinfo=timezone.utc)) == 0
    assert graded[0][3].startswith("2026-10-15T23:59:59")


def test_main_all_cohorts_with_none_registered_is_a_noop(monkeypatch):
    # A freshly bootstrapped course org runs the hourly cron before any cohort is
    # registered - that gap must be a quiet no-op, not a red run (and a failure
    # email to the bot owner) every hour.
    monkeypatch.setattr(seed, "discover_cohorts", lambda org: [])
    monkeypatch.setattr(
        sys, "argv", ["scheduler", "--course-org", "Course-Org", "--all-cohorts"]
    )
    assert scheduler.main() == 0


def test_scheduler_workflow_hourly_and_ungated():
    doc = yaml.safe_load(seed.render_scheduler())
    assert doc.get("name") == "Scheduled release"
    # cron trigger present (YAML 1.1: `on:` may parse to True)
    trigger = doc.get("on", doc.get(True))
    assert "schedule" in trigger
    assert trigger["schedule"][0]["cron"] == "0 * * * *"  # hourly (was daily)
    # deliberately NOT gated by check-team (no actor on a scheduled run)
    assert "check-team" not in doc["jobs"]


def test_handout_releases_synthesised_from_the_assignments_block(monkeypatch):
    # The whole lifecycle lives under assignments.<slug>; a `handout_datetime:` datetime
    # becomes a normal release (template resolved as <slug>-<tag>, like autograding), so
    # it fires through the same due/idempotency/site-sync machinery.
    monkeypatch.setattr(
        scheduler,
        "_assignment_template",
        lambda course, cohort, slug: None if slug == "web-only" else f"{slug}-f2026",
    )
    sched = Schedule(
        assignments={
            "assignment-1": AssignmentEntry(
                due_datetime=datetime(2026, 10, 13, 23, 59, tzinfo=BERLIN),
                handout_datetime=datetime(2026, 9, 22, 9, 0, tzinfo=BERLIN),
            ),
            "web-only": AssignmentEntry(  # pinned for its site date; no template repo
                due_datetime=datetime(2026, 11, 1, 23, 59, tzinfo=BERLIN),
                handout_datetime=datetime(2026, 10, 1, 9, 0, tzinfo=BERLIN),
            ),
            "manual": AssignmentEntry(due_datetime=datetime(2026, 12, 1, 23, 59, tzinfo=BERLIN)),
        }
    )
    (r,) = scheduler._handout_releases("Course-Org", "Cohort-f2026", sched)
    assert r.label == "assignment-1-handout"
    assert r.assignment == "assignment-1-f2026"
    assert r.when == datetime(2026, 9, 22, 9, 0, tzinfo=BERLIN)
    # and it is due like any release once its datetime passes - not a minute before
    assert scheduler.due_releases([r], datetime(2026, 9, 22, 8, 0, tzinfo=BERLIN)) == []
    assert scheduler.due_releases([r], datetime(2026, 9, 22, 10, 0, tzinfo=BERLIN)) == [r]
