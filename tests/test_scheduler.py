"""scheduler pure core: due_releases (datetime, timezone-correct) + _execute()'s dispatch
to the release functions - monkeypatched so a schema<->signature mismatch (the class of bug
that silently broke scheduled releases once) is caught without any real gh/git I/O. Plus a
renderer guard (the cron is hourly and has NO check-team gate - scheduled runs have no actor).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from dsl_course import collect, release_code, scheduler, seed
from dsl_course.schedule import AssignmentEntry, Deploy, Grade, Release, Schedule

BERLIN = ZoneInfo("Europe/Berlin")
WHEN = datetime(2026, 9, 15, 14, 0, tzinfo=BERLIN)


def _r(label: str, when: datetime, **kw) -> Release:
    return Release(label=label, when=when, **kw)


def _sched_with(releases: list[Release]) -> Schedule:
    return Schedule(releases=releases)


def test_due_releases_in_when_order():
    releases = sorted(
        [
            _r("b", datetime(2026, 9, 15, 14, 0, tzinfo=BERLIN)),
            _r("a", datetime(2026, 9, 1, 9, 0, tzinfo=BERLIN)),
            _r("c", datetime(2026, 9, 29, 9, 0, tzinfo=BERLIN)),
        ],
        key=lambda r: r.when,
    )
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    assert [r.label for r in scheduler.due_releases(releases, now)] == ["a", "b"]
    assert scheduler.due_releases(releases, datetime(2026, 8, 1, tzinfo=timezone.utc)) == []
    assert len(scheduler.due_releases(releases, datetime(2026, 12, 1, tzinfo=timezone.utc))) == 3


def test_due_releases_honours_time_of_day_across_timezones():
    # 14:00 Europe/Berlin (CEST) == 12:00 UTC. At 11:00 UTC not yet due; at 13:00 UTC due.
    r = _r("s", datetime(2026, 9, 15, 14, 0, tzinfo=BERLIN))
    assert scheduler.due_releases([r], datetime(2026, 9, 15, 11, 0, tzinfo=timezone.utc)) == []
    assert scheduler.due_releases([r], datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)) == [r]


def test_describe_lists_every_action():
    r = _r(
        "s2",
        WHEN,
        deploy=[
            Deploy("cm-f2026", "lectures/02_intro", "materials", None),
            Deploy("data-f2026", "w7/housing.csv", "materials", "datasets/housing.csv"),
        ],
        assignment="assignment-1-f2026",
        grade=Grade("assignment-2-f2026"),
    )
    lines = scheduler.describe(r)
    assert any("cm-f2026/lectures/02_intro -> materials/lectures/02_intro" in ln for ln in lines)
    assert any("materials/datasets/housing.csv" in ln for ln in lines)
    assert any(ln.startswith("assignment ") for ln in lines)
    assert any(ln.startswith("grade ") for ln in lines)


# _execute_nondeploy() and the deploy batching ARE pure wiring (no gh/git of their own),
# but a schema<->signature mismatch is exactly the class of bug that silently broke
# scheduled releases - monkeypatching the release functions catches it without real I/O.


def test_run_batches_all_deploys_through_deploy_many(monkeypatch):
    # The clone-once win: every due release's deploys go through ONE deploy_many call
    # (which clones each source/dest once), not one release_code call per copy.
    calls = []
    monkeypatch.setattr(
        "dsl_course.release_code.deploy_many",
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


def test_execute_nondeploy_grade_calls_collect_with_iso_deadline(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dsl_course.collect.collect",
        lambda master_org, template, cohort_org, deadline, group=False: calls.append(
            (master_org, template, cohort_org, deadline, group)
        )
        or 0,
    )
    r = _r(
        "s",
        WHEN,
        grade=Grade("assignment-2-f2026", datetime(2026, 10, 13, 23, 59, tzinfo=BERLIN), True),
    )
    assert scheduler._execute_nondeploy("Course-Org", "Cohort-Org", r) == 0
    org, template, cohort, deadline, group = calls[0]
    assert (org, template, cohort, group) == ("Course-Org", "assignment-2-f2026", "Cohort-Org", True)
    assert deadline.startswith("2026-10-13T23:59")


def test_execute_nondeploy_grade_deadline_none_when_unset(monkeypatch):
    # No deadline in the schedule -> pass None so collect resolves it from the SSOT.
    calls = []
    monkeypatch.setattr(
        "dsl_course.collect.collect",
        lambda m, t, c, deadline, group=False: calls.append(deadline) or 0,
    )
    scheduler._execute_nondeploy(
        "Course-Org", "Cohort-Org", _r("s", WHEN, grade=Grade("assignment-1-f2026"))
    )
    assert calls[0] is None


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

    monkeypatch.setattr(release_code, "gh", fake_gh)
    monkeypatch.setattr(release_code, "git", lambda *a: (0, ""))  # commit + push succeed
    monkeypatch.setattr(release_code, "create_repo", lambda *a, **k: True)
    monkeypatch.setattr(release_code, "grant_read_teams", lambda *a, **k: None)

    deploys = [
        Deploy("cm", "lectures/00_x", "lectures", None),
        Deploy("cm", "labs/00_y", "labs", None),
        Deploy("cm", "lectures/01_z", "lectures", None),
    ]
    errors, changed = release_code.deploy_many("Course-Org", "Cohort-Org", deploys, sync=False)
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

    monkeypatch.setattr(release_code, "gh", fake_gh)
    monkeypatch.setattr(release_code, "git", lambda *a: (0, ""))
    monkeypatch.setattr(release_code, "create_repo", lambda *a, **k: True)
    monkeypatch.setattr(release_code, "grant_read_teams", lambda *a, **k: None)

    errors, changed = release_code.deploy_many(
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
    monkeypatch.setattr(release_code, "gh", fake_gh)
    monkeypatch.setattr(release_code, "git", lambda *a: (0, ""))
    monkeypatch.setattr(release_code, "create_repo", lambda *a, **k: True)
    monkeypatch.setattr(release_code, "grant_read_teams", lambda *a, **k: None)


def test_deploy_many_counts_a_doomed_deploy_once(monkeypatch):
    # Source AND dest clone both fail: that is ONE copy lost, not two errors (a
    # double-count made `release_code` report 2 failures for a single deploy).
    _no_io(monkeypatch, _clone_failing("Course-Org/cm", "Cohort-Org/materials"))
    errors, changed = release_code.deploy_many(
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
    assert release_code.deploy_many(
        "Course-Org", "Cohort-Org", deploys, sync=False
    ) == (3, False)


# ------------------------------------------------------------- deadline snapshots
# The hourly cron is what makes the grading pin trustworthy: it freezes each assignment's
# commits at a moment the SERVER chose, because committer dates are client-supplied. So the
# trigger condition (deadline passed, not yet frozen) and its write-once-ness are the logic
# that matters here.


def _assignments(**entries: AssignmentEntry) -> Schedule:
    return Schedule(assignments=dict(entries))


def _due(day: int, grace: int = 0) -> AssignmentEntry:
    return AssignmentEntry(
        due=datetime(2026, 10, day, 23, 59, 59, tzinfo=BERLIN), grace_days=grace
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


def test_due_snapshots_waits_out_grace_days_and_carries_the_pin():
    sched = _assignments(**{"assignment-1": _due(13, grace=2)})
    assert scheduler.due_snapshots(sched, datetime(2026, 10, 14, tzinfo=timezone.utc)) == []
    (slug, deadline), = scheduler.due_snapshots(
        sched, datetime(2026, 10, 16, tzinfo=timezone.utc)
    )
    assert slug == "assignment-1"
    assert deadline.startswith("2026-10-15T23:59:59")  # due + grace_days, the grading pin


def test_due_snapshots_empty_without_assignments():
    assert scheduler.due_snapshots(Schedule(), datetime(2030, 1, 1, tzinfo=timezone.utc)) == []


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


def test_run_snapshots_even_with_no_materials_releases(monkeypatch):
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
    monkeypatch.setattr(
        scheduler.schedule, "load", lambda cohort: _assignments(**{"assignment-1": _due(13)})
    )
    assert scheduler.run("Course-Org", "Cohort-Org", datetime(2026, 11, 1, tzinfo=timezone.utc)) == 1


def test_run_snapshots_before_firing_a_grade_release(monkeypatch):
    # Order matters: a grade release firing in the same tick must already see the snapshot.
    order: list[str] = []
    monkeypatch.setattr(collect, "load_snapshots", lambda org, slug: None)
    monkeypatch.setattr(
        collect,
        "snapshot_assignment",
        lambda org, slug, deadline: order.append("snapshot") or True,
    )
    monkeypatch.setattr(
        "dsl_course.collect.collect",
        lambda m, t, c, deadline, group=False: order.append("collect") or 0,
    )
    sched = Schedule(
        assignments={"assignment-1": _due(13)},
        releases=[_r("a1-grade", datetime(2026, 10, 14, tzinfo=BERLIN), grade=Grade("assignment-1-f2026"))],
    )
    monkeypatch.setattr(scheduler.schedule, "load", lambda cohort: sched)
    assert scheduler.run("Course-Org", "Cohort-Org", datetime(2026, 10, 15, tzinfo=timezone.utc)) == 0
    assert order == ["snapshot", "collect"]


def test_scheduler_workflow_hourly_and_ungated():
    doc = yaml.safe_load(seed.render_scheduler())
    assert doc.get("name") == "Scheduled release"
    # cron trigger present (YAML 1.1: `on:` may parse to True)
    trigger = doc.get("on", doc.get(True))
    assert "schedule" in trigger
    assert trigger["schedule"][0]["cron"] == "0 * * * *"  # hourly (was daily)
    # deliberately NOT gated by check-team (no actor on a scheduled run)
    assert "check-team" not in doc["jobs"]
