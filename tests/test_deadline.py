"""Grading-deadline SSOT: the autograder's pin date comes from the cohort schedule
(`assignments[slug]` + optional `grace_days[slug]`), not a separate Grade-button input."""

from __future__ import annotations

from datetime import date

from dsl_course.collect import _grading_deadline


def test_due_date_no_grace():
    meta = {"schedule": {"assignments": {"assignment-1": "2026-10-13"}}}
    assert _grading_deadline(meta, "assignment-1") == "2026-10-13"


def test_grace_days_extend_only_the_grading_pin():
    meta = {
        "schedule": {
            "assignments": {"assignment-1": "2026-10-13"},
            "grace_days": {"assignment-1": 2},
        }
    }
    assert _grading_deadline(meta, "assignment-1") == "2026-10-15"


def test_due_as_yaml_date_object():
    meta = {
        "schedule": {
            "assignments": {"assignment-1": date(2026, 10, 13)},
            "grace_days": {"assignment-1": 1},
        }
    }
    assert _grading_deadline(meta, "assignment-1") == "2026-10-14"


def test_unscheduled_assignment_is_none():
    meta = {"schedule": {"assignments": {"assignment-1": "2026-10-13"}}}
    assert _grading_deadline(meta, "assignment-2") is None
    assert _grading_deadline({}, "assignment-1") is None


def test_grace_defaults_to_zero_when_absent_or_garbage():
    base = {"assignments": {"assignment-1": "2026-10-13"}}
    assert _grading_deadline({"schedule": base}, "assignment-1") == "2026-10-13"
    assert (
        _grading_deadline(
            {"schedule": {**base, "grace_days": {"assignment-1": "oops"}}},
            "assignment-1",
        )
        == "2026-10-13"
    )
