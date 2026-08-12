"""Grading-deadline SSOT: the autograder's pin comes from the cohort schedule, not a separate
Grade-button input. Precedence is an explicit `assignments[slug].grading_deadline`, else the
legacy `due + grace_days`, else `due`. Every value is a timezone-aware datetime; a bare date
closes at end of day (23:59:59)."""

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


# ---------------------------------------------------------- explicit grading_deadline
# The pin students never see. It exists so the snapshot freeze and the autograde run share
# one instant that is stated outright, rather than inferred from due + a day count.


def test_explicit_grading_deadline_wins_over_due_plus_grace():
    sched = parse(
        {
            "assignments": {
                "assignment-1": {
                    "due": "2026-10-13",
                    "grading_deadline": "2026-10-15",
                    "grace_days": 7,
                }
            }
        }
    )
    assert grading_deadline(sched, "assignment-1").startswith("2026-10-15T23:59:59")
    # the due date students see is untouched by it
    assert sched.assignments["assignment-1"].due.isoformat().startswith("2026-10-13T23:59:59")


def test_grading_deadline_bare_date_closes_end_of_day():
    sched = parse(
        {"assignments": {"assignment-1": {"due": "2026-10-13", "grading_deadline": "2026-10-15"}}}
    )
    assert grading_deadline(sched, "assignment-1").startswith("2026-10-15T23:59:59")
    sched = parse(
        {
            "assignments": {
                "assignment-1": {"due": "2026-10-13", "grading_deadline": date(2026, 10, 15)}
            }
        }
    )
    assert grading_deadline(sched, "assignment-1").startswith("2026-10-15T23:59:59")


def test_grading_deadline_with_an_explicit_time_is_honoured():
    sched = parse(
        {
            "assignments": {
                "assignment-1": {"due": "2026-10-13", "grading_deadline": "2026-10-15T09:00"}
            }
        }
    )
    assert grading_deadline(sched, "assignment-1").startswith("2026-10-15T09:00")


def test_grading_deadline_can_be_earlier_than_due_plus_grace():
    # Nothing clamps it - the pin is whatever the cohort states.
    sched = parse(
        {
            "assignments": {
                "assignment-1": {
                    "due": "2026-10-13",
                    "grace_days": 5,
                    "grading_deadline": "2026-10-14",
                }
            }
        }
    )
    assert grading_deadline(sched, "assignment-1").startswith("2026-10-14T23:59:59")


def test_malformed_grading_deadline_falls_back_to_the_grace_days_path():
    # Silently ignored, like every other unparseable field here - not an error, and not a
    # drop of the whole entry.
    sched = parse(
        {
            "assignments": {
                "assignment-1": {
                    "due": "2026-10-13",
                    "grace_days": 2,
                    "grading_deadline": "soon-ish",
                }
            }
        }
    )
    assert sched.assignments["assignment-1"].grading_deadline is None
    assert grading_deadline(sched, "assignment-1").startswith("2026-10-15T23:59:59")


def test_grading_deadline_without_due_is_still_dropped():
    # `due` remains the required field - it is what students are told.
    assert (
        parse({"assignments": {"assignment-1": {"grading_deadline": "2026-10-15"}}}).assignments
        == {}
    )
