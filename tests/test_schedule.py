"""dsl_course.schedule pure core - classroom-config/schedule.yml is the single home for a
cohort's release plan (materials_releases), due dates, and exams; a wrong parse here
silently mis-times a release or mis-pins a grading deadline, so it's the bit that must be
right. Times are timezone-aware (naive -> Europe/Berlin by default).
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from dsl_course.schedule import (
    Deploy,
    Exam,
    Grade,
    Schedule,
    _coerce_date,
    _coerce_datetime,
    parse,
)

BERLIN = ZoneInfo("Europe/Berlin")


@pytest.mark.parametrize(
    "value,expected",
    [
        (date(2026, 9, 7), date(2026, 9, 7)),
        (datetime(2026, 9, 7, 12, 0), date(2026, 9, 7)),
        ("2026-09-07", date(2026, 9, 7)),
        ("not-a-date", None),
        (12345, None),
    ],
)
def test_coerce_date(value, expected):
    assert _coerce_date(value) == expected


def test_coerce_datetime_bare_date_start_or_end_of_day():
    # A release date opens at the start of the day; a due date closes at the end.
    start = _coerce_datetime(date(2026, 9, 15), BERLIN)
    assert (start.hour, start.minute, start.second) == (0, 0, 0)
    end = _coerce_datetime(date(2026, 10, 13), BERLIN, end_of_day=True)
    assert (end.hour, end.minute, end.second) == (23, 59, 59)


def test_coerce_datetime_naive_gets_default_tz_explicit_offset_kept():
    naive = _coerce_datetime("2026-09-15T14:00", BERLIN)
    assert naive.tzinfo is not None
    assert naive.utcoffset() == BERLIN.utcoffset(naive.replace(tzinfo=None))
    aware = _coerce_datetime("2026-09-15T14:00+00:00", BERLIN)
    assert aware.utcoffset().total_seconds() == 0  # explicit offset honoured, not overridden


def test_parse_full_schedule():
    meta = {
        "timezone": "Europe/Berlin",
        "semester_start": "2026-09-07",
        "semester_end": "2026-12-18",
        "materials_releases": {
            "session_2": {
                "when": "2026-09-15T14:00",
                "deploy": [
                    {
                        "source_repo": "cm-f2026",
                        "source_path": "lectures/02_intro",
                        "dest_repo": "materials",
                        "dest_path": "lectures/02_intro",
                    }
                ],
            },
            "a1-grade": {
                "when": "2026-10-15T00:00",
                "grade": {"template": "assignment-1-f2026", "deadline": "2026-10-13T23:59"},
            },
        },
        "assignments": {"assignment-1": {"due": "2026-10-13", "grace_days": 2}},
        "exams": [{"name": "Final", "date": "2026-12-15"}],
    }
    sched = parse(meta)
    assert sched.semester_start == date(2026, 9, 7)
    assert [r.label for r in sched.releases] == ["session_2", "a1-grade"]  # sorted by when
    s2 = sched.releases[0]
    assert s2.deploy == [Deploy("cm-f2026", "lectures/02_intro", "materials", "lectures/02_intro")]
    assert sched.releases[1].grade.template == "assignment-1-f2026"
    assert sched.assignments["assignment-1"].due.isoformat().startswith("2026-10-13T23:59:59")
    assert sched.assignments["assignment-1"].grace_days == 2
    assert sched.exams == [Exam(name="Final", date=date(2026, 12, 15))]


def test_parse_empty_is_safe():
    assert parse({}) == Schedule()
    assert parse(None) == Schedule()


def test_release_without_when_is_dropped():
    meta = {
        "materials_releases": {
            "ok": {"when": "2026-09-01", "deploy": []},
            "nope": {"deploy": []},
        }
    }
    assert [r.label for r in parse(meta).releases] == ["ok"]


def test_deploy_accepts_single_mapping_defaults_dest_path_none():
    meta = {
        "materials_releases": {
            "s": {
                "when": "2026-09-01",
                "deploy": {"source_repo": "cm", "source_path": "lectures/00_x"},
            }
        }
    }
    assert parse(meta).releases[0].deploy == [Deploy("cm", "lectures/00_x", "materials", None)]


def test_deploy_entry_missing_source_is_skipped():
    meta = {
        "materials_releases": {
            "s": {"when": "2026-09-01", "deploy": [{"source_repo": "cm"}, {"source_path": "x"}]}
        }
    }
    assert parse(meta).releases[0].deploy == []


def test_grade_string_and_dict_forms():
    meta = {
        "materials_releases": {
            "g1": {"when": "2026-10-01", "grade": "assignment-1-f2026"},
            "g2": {
                "when": "2026-10-02",
                "grade": {"template": "assignment-2-f2026", "deadline": "2026-10-13", "group": True},
            },
        }
    }
    rels = {r.label: r for r in parse(meta).releases}
    assert rels["g1"].grade == Grade(template="assignment-1-f2026", deadline=None, group=False)
    g2 = rels["g2"].grade
    assert g2.template == "assignment-2-f2026" and g2.group is True
    assert g2.deadline.isoformat().startswith("2026-10-13T23:59:59")  # bare date -> end of day


def test_assignment_bare_date_is_rejected_only_the_nested_form_is_accepted():
    # `assignments: {slug: date}` (no nested due/grace_days) is not the documented schema.
    assert parse({"assignments": {"assignment-1": "2026-10-13"}}).assignments == {}


def test_assignment_without_due_is_skipped():
    assert parse({"assignments": {"assignment-1": {"grace_days": 2}}}).assignments == {}
