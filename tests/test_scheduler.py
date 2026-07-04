"""scheduler pure core: manifest x calendar x today -> ordered action list, plus
_execute()'s dispatch to the release functions - monkeypatched so a manifest-shape <->
function-signature mismatch (the class of bug that silently broke scheduled materials
releases once) is caught without any real gh/git I/O. Plus a renderer guard (the cron
has NO check-team gate by design - scheduled runs have no actor).
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


# _execute()'s dispatch to the release functions IS pure wiring (no gh/git calls of its
# own), but a manifest-shape <-> function-signature mismatch there is exactly the class
# of bug that silently broke scheduled materials releases when release()'s signature
# changed elsewhere - monkeypatching the release functions catches that without any
# real gh/git I/O.


def test_execute_materials_calls_release_with_current_signature(monkeypatch):
    calls = []

    def fake_release(source_org, source_repo, cohort_org, sessions, **kwargs):
        calls.append((source_org, source_repo, cohort_org, sessions, kwargs))
        return 0

    monkeypatch.setattr("dsl_course.release.release", fake_release)
    action = {
        "kind": "materials",
        "session": "3",
        "source_repo": "cm-f2026",
        "cohort_repo": "materials",
        "exclude": {"readings"},
    }
    assert scheduler._execute("Course-Org", "Cohort-Org", action) == 0
    org, repo, cohort, sessions, kwargs = calls[0]
    assert (org, repo, cohort, sessions) == ("Course-Org", "cm-f2026", "Cohort-Org", ["3"])
    assert kwargs["default_repo"] == "materials"
    assert kwargs["exclude"] == {"readings"}


def test_execute_code_calls_release_code_with_current_signature(monkeypatch):
    calls = []

    def fake_release_code(source_org, source_repo, cohort_org, cohort_repo, path):
        calls.append((source_org, source_repo, cohort_org, cohort_repo, path))
        return 0

    monkeypatch.setattr("dsl_course.release_code.release_code", fake_release_code)
    action = {
        "kind": "code",
        "source_repo": "lecture-code",
        "path": "mlpkg/simulation",
        "cohort_repo": "materials",
    }
    assert scheduler._execute("Course-Org", "Cohort-Org", action) == 0
    assert calls[0] == (
        "Course-Org",
        "lecture-code",
        "Cohort-Org",
        "materials",
        "mlpkg/simulation",
    )


def test_execute_assignment_calls_provision_all_with_current_signature(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dsl_course.assign.provision_all",
        lambda master_org, template, cohort_org: calls.append(
            (master_org, template, cohort_org)
        )
        or 0,
    )
    action = {"kind": "assignment", "template": "assignment-2-f2026"}
    assert scheduler._execute("Course-Org", "Cohort-Org", action) == 0
    assert calls[0] == ("Course-Org", "assignment-2-f2026", "Cohort-Org")


def test_execute_grade_calls_collect_with_current_signature(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "dsl_course.collect.collect",
        lambda master_org, template, cohort_org, deadline, group=False: calls.append(
            (master_org, template, cohort_org, deadline, group)
        )
        or 0,
    )
    action = {
        "kind": "grade",
        "template": "assignment-2-f2026",
        "deadline": "2026-10-15",
        "group": True,
    }
    assert scheduler._execute("Course-Org", "Cohort-Org", action) == 0
    assert calls[0] == ("Course-Org", "assignment-2-f2026", "Cohort-Org", "2026-10-15", True)
