"""scheduler pure core: manifest x calendar x today -> ordered action list. This is the
bit that decides what auto-opens, so it's unit-tested; the dispatch to release functions
is gh/git wiring and left live. Plus a renderer guard (the cron has NO check-team gate by
design - scheduled runs have no actor).
"""

from __future__ import annotations

from datetime import date

import yaml

from dsl_course import scheduler, seed

MANIFEST = {
    "weeks": {
        "week-1": {
            "materials": {"source_repo": "cm-f2026", "cohort_repo": "materials"}
        },
        "week-3": {
            "materials": {"source_repo": "cm-f2026", "cohort_repo": "materials"},
            "code": [{"source_repo": "lecture-code", "path": "mlpkg/simulation"}],
        },
        "week-5": {"assignment": "assignment-2-f2026"},
    }
}
CALENDAR = "week,date\nweek-1,2026-09-01\nweek-3,2026-09-15\nweek-5,2026-09-29\n"


def test_parse_calendar_skips_bad_dates():
    cal = scheduler.parse_calendar(
        "week,date\nweek-1,2026-09-01\nweek-2,not-a-date\nweek-3,\n"
    )
    assert cal == {"week-1": date(2026, 9, 1)}


def test_due_weeks_in_calendar_order():
    cal = scheduler.parse_calendar(CALENDAR)
    assert scheduler.due_weeks(cal, date(2026, 9, 16)) == ["week-1", "week-3"]
    assert scheduler.due_weeks(cal, date(2026, 8, 1)) == []
    assert scheduler.due_weeks(cal, date(2026, 12, 1)) == ["week-1", "week-3", "week-5"]


def test_plan_flattens_due_weeks_into_actions():
    actions = scheduler.plan(MANIFEST, ["week-1", "week-3"])
    kinds = [a["kind"] for a in actions]
    assert kinds == ["materials", "materials", "code"]
    # week-3 materials carries the stripped week number for release._week_dir
    assert actions[1]["week"] == "3"
    # code defaults its cohort_repo when omitted
    assert actions[2]["cohort_repo"] == "materials"


def test_plan_includes_assignment_when_due():
    actions = scheduler.plan(MANIFEST, ["week-5"])
    assert actions == [{"kind": "assignment", "template": "assignment-2-f2026"}]


def test_plan_empty_when_nothing_due():
    assert scheduler.plan(MANIFEST, []) == []


def test_scheduler_workflow_valid_yaml_and_ungated():
    doc = yaml.safe_load(seed.render_scheduler())
    assert doc.get("name") == "Scheduled release"
    # cron trigger present (YAML 1.1: `on:` may parse to True)
    trigger = doc.get("on", doc.get(True))
    assert "schedule" in trigger
    # deliberately NOT gated by check-team (no actor on a scheduled run)
    assert "check-team" not in doc["jobs"]
