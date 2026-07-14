"""scheduler pure core: due_releases (datetime, timezone-correct) + _execute()'s dispatch
to the release functions - monkeypatched so a schema<->signature mismatch (the class of bug
that silently broke scheduled releases once) is caught without any real gh/git I/O. Plus a
renderer guard (the cron is hourly and has NO check-team gate - scheduled runs have no actor).
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import yaml

from dsl_course import scheduler, seed
from dsl_course.schedule import Deploy, Grade, Release

BERLIN = ZoneInfo("Europe/Berlin")
WHEN = datetime(2026, 9, 15, 14, 0, tzinfo=BERLIN)


def _r(label: str, when: datetime, **kw) -> Release:
    return Release(label=label, when=when, **kw)


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


# _execute()'s dispatch IS pure wiring (no gh/git of its own), but a schema<->signature
# mismatch there is exactly the class of bug that silently broke scheduled releases -
# monkeypatching the release functions catches it without any real gh/git I/O.


def test_execute_deploy_calls_release_code_with_dest_and_no_sync(monkeypatch):
    calls = []

    def fake_release_code(
        source_org, source_repo, cohort_org, cohort_repo, path, dest_path=None, sync=True
    ):
        calls.append(
            (source_org, source_repo, cohort_org, cohort_repo, path, dest_path, sync)
        )
        return 0

    monkeypatch.setattr("dsl_course.release_code.release_code", fake_release_code)
    r = _r(
        "s",
        WHEN,
        deploy=[Deploy("cm-f2026", "lectures/02_intro", "materials", "lectures/02_intro")],
    )
    assert scheduler._execute("Course-Org", "Cohort-Org", r) == (0, True)
    # scheduler must pass sync=False (it syncs the site once, after all releases)
    assert calls[0] == (
        "Course-Org", "cm-f2026", "Cohort-Org", "materials",
        "lectures/02_intro", "lectures/02_intro", False,
    )


def test_execute_assignment_calls_provision_all(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dsl_course.assign.provision_all",
        lambda master_org, template, cohort_org: calls.append(
            (master_org, template, cohort_org)
        )
        or 0,
    )
    r = _r("s", WHEN, assignment="assignment-2-f2026")
    assert scheduler._execute("Course-Org", "Cohort-Org", r) == (0, False)
    assert calls[0] == ("Course-Org", "assignment-2-f2026", "Cohort-Org")


def test_execute_grade_calls_collect_with_iso_deadline(monkeypatch):
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
    assert scheduler._execute("Course-Org", "Cohort-Org", r) == (0, False)
    org, template, cohort, deadline, group = calls[0]
    assert (org, template, cohort, group) == ("Course-Org", "assignment-2-f2026", "Cohort-Org", True)
    assert deadline.startswith("2026-10-13T23:59")


def test_execute_grade_deadline_none_when_unset(monkeypatch):
    # No deadline in the schedule -> pass None so collect resolves it from the SSOT.
    calls = []
    monkeypatch.setattr(
        "dsl_course.collect.collect",
        lambda m, t, c, deadline, group=False: calls.append(deadline) or 0,
    )
    scheduler._execute("Course-Org", "Cohort-Org", _r("s", WHEN, grade=Grade("assignment-1-f2026")))
    assert calls[0] is None


def test_scheduler_workflow_hourly_and_ungated():
    doc = yaml.safe_load(seed.render_scheduler())
    assert doc.get("name") == "Scheduled release"
    # cron trigger present (YAML 1.1: `on:` may parse to True)
    trigger = doc.get("on", doc.get(True))
    assert "schedule" in trigger
    assert trigger["schedule"][0]["cron"] == "0 * * * *"  # hourly (was daily)
    # deliberately NOT gated by check-team (no actor on a scheduled run)
    assert "check-team" not in doc["jobs"]
