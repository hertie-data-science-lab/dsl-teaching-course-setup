"""Grading-deadline SSOT: the autograder's pin comes from the cohort schedule
(`assignments[slug].due` + optional `grace_days`), not a separate Grade-button input.
`due` is a timezone-aware datetime; a bare due date closes at end of day (23:59:59)."""

from __future__ import annotations

from datetime import date

from dsl_course.schedule import Schedule, grading_deadline, parse


def test_due_date_no_grace_closes_end_of_day():
    sched = parse({"assignments": {"assignment-1": {"due": "2026-10-13"}}})
    assert grading_deadline(sched, "assignment-1").startswith("2026-10-13T23:59:59")


def test_grace_days_extend_only_the_grading_pin():
    sched = parse({"assignments": {"assignment-1": {"due": "2026-10-13", "grace_days": 2}}})
    assert grading_deadline(sched, "assignment-1").startswith("2026-10-15T23:59:59")


def test_due_as_yaml_date_object():
    sched = parse(
        {"assignments": {"assignment-1": {"due": date(2026, 10, 13), "grace_days": 1}}}
    )
    assert grading_deadline(sched, "assignment-1").startswith("2026-10-14T23:59:59")


def test_due_with_explicit_time_is_honoured():
    sched = parse({"assignments": {"assignment-1": {"due": "2026-10-13T18:00"}}})
    assert grading_deadline(sched, "assignment-1").startswith("2026-10-13T18:00")


def test_unscheduled_assignment_is_none():
    sched = parse({"assignments": {"assignment-1": {"due": "2026-10-13"}}})
    assert grading_deadline(sched, "assignment-2") is None
    assert grading_deadline(Schedule(), "assignment-1") is None


def test_grace_defaults_to_zero_when_absent_or_garbage():
    sched = parse({"assignments": {"assignment-1": {"due": "2026-10-13"}}})
    assert grading_deadline(sched, "assignment-1").startswith("2026-10-13T23:59:59")
    sched = parse(
        {"assignments": {"assignment-1": {"due": "2026-10-13", "grace_days": "oops"}}}
    )
    assert grading_deadline(sched, "assignment-1").startswith("2026-10-13T23:59:59")
