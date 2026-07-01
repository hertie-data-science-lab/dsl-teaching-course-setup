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
    "sessions": {
        "1": {"materials": {"source_repo": "cm-f2026", "cohort_repo": "materials"}},
        "3": {
            "materials": {
                "source_repo": "cm-f2026",
                "cohort_repo": "materials",
                "exclude": ["readings"],
            },
            "code": [{"source_repo": "lecture-code", "path": "mlpkg/simulation"}],
        },
        "5": {"assignment": "assignment-2-f2026"},
    }
}
CALENDAR = {
    "1": date(2026, 9, 1),
    "3": date(2026, 9, 15),
    "5": date(2026, 9, 29),
}


def test_due_sessions_in_calendar_order():
    assert scheduler.due_sessions(CALENDAR, date(2026, 9, 16)) == ["1", "3"]
    assert scheduler.due_sessions(CALENDAR, date(2026, 8, 1)) == []
    assert scheduler.due_sessions(CALENDAR, date(2026, 12, 1)) == ["1", "3", "5"]


def test_plan_flattens_due_sessions_into_actions():
    actions = scheduler.plan(MANIFEST, ["1", "3"])
    kinds = [a["kind"] for a in actions]
    assert kinds == ["materials", "materials", "code"]
    assert actions[1]["session"] == "3"
    assert actions[1]["exclude"] == {"readings"}
    # code defaults its cohort_repo when omitted
    assert actions[2]["cohort_repo"] == "materials"


def test_plan_manifest_accepts_int_yaml_keys():
    # bare (unquoted) YAML keys like `1:` parse as int, not str - plan() must coerce.
    manifest = {"sessions": {1: {"assignment": "assignment-1-f2026"}}}
    assert scheduler.plan(manifest, ["1"]) == [
        {"kind": "assignment", "template": "assignment-1-f2026"}
    ]


def test_plan_includes_assignment_when_due():
    actions = scheduler.plan(MANIFEST, ["5"])
    assert actions == [{"kind": "assignment", "template": "assignment-2-f2026"}]


def test_plan_empty_when_nothing_due():
    assert scheduler.plan(MANIFEST, []) == []


def test_plan_grade_action_string_and_dict_forms():
    manifest = {
        "sessions": {
            "6": {"grade": "assignment-1-f2026"},
            "7": {
                "grade": {
                    "template": "assignment-2-f2026",
                    "deadline": "2026-10-15",
                    "group": True,
                }
            },
        }
    }
    a6 = scheduler.plan(manifest, ["6"])[0]
    assert a6 == {
        "kind": "grade",
        "template": "assignment-1-f2026",
        "deadline": None,
        "group": False,
    }
    a7 = scheduler.plan(manifest, ["7"])[0]
    assert a7["template"] == "assignment-2-f2026"
    assert a7["deadline"] == "2026-10-15" and a7["group"] is True
    assert scheduler.describe(a7).startswith("grade assignment-2-f2026")


def test_scheduler_workflow_valid_yaml_and_ungated():
    doc = yaml.safe_load(seed.render_scheduler())
    assert doc.get("name") == "Scheduled release"
    # cron trigger present (YAML 1.1: `on:` may parse to True)
    trigger = doc.get("on", doc.get(True))
    assert "schedule" in trigger
    # deliberately NOT gated by check-team (no actor on a scheduled run)
    assert "check-team" not in doc["jobs"]
