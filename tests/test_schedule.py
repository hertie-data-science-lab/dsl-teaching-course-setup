"""dsl_course.schedule pure core - classroom-config/schedule.yml is the single home
for a cohort's release calendar, due dates, and exams; a wrong parse here silently
mis-times a release or mis-pins a grading deadline, so it's the bit that must be right.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from dsl_course.schedule import AssignmentEntry, Exam, Schedule, _coerce_date, parse


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


def test_parse_full_schedule():
    meta = {
        "semester_start": "2026-09-07",
        "semester_end": "2026-12-18",
        "sessions": {"1": "2026-09-07", "3": "2026-09-21"},
        "labs": {"1": "2026-09-09"},
        "assignments": {"assignment-1": {"due": "2026-10-13", "grace_days": 2}},
        "exams": [{"name": "Final", "date": "2026-12-15"}],
    }
    sched = parse(meta)
    assert sched.semester_start == date(2026, 9, 7)
    assert sched.semester_end == date(2026, 12, 18)
    assert sched.sessions == {"1": date(2026, 9, 7), "3": date(2026, 9, 21)}
    assert sched.labs == {"1": date(2026, 9, 9)}
    assert sched.assignments == {
        "assignment-1": AssignmentEntry(due=date(2026, 10, 13), grace_days=2)
    }
    assert sched.exams == [Exam(name="Final", date=date(2026, 12, 15))]


def test_parse_empty_is_safe():
    assert parse({}) == Schedule()
    assert parse(None) == Schedule()


def test_parse_skips_bad_session_dates():
    sched = parse({"sessions": {"1": "2026-09-01", "2": "not-a-date", "3": ""}})
    assert sched.sessions == {"1": date(2026, 9, 1)}


def test_assignment_bare_date_is_rejected_only_the_nested_form_is_accepted():
    # `assignments: {slug: date}` (no nested due/grace_days) is not the documented
    # schema and is skipped, not silently coerced.
    sched = parse({"assignments": {"assignment-1": "2026-10-13"}})
    assert sched.assignments == {}


def test_assignment_without_due_is_skipped():
    sched = parse({"assignments": {"assignment-1": {"grace_days": 2}}})
    assert sched.assignments == {}
