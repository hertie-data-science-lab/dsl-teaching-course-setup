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


def test_exam_bare_date_stays_a_date_timed_exam_becomes_aware_datetime():
    # `date:` doubles as "whole day" (a plain date) and "starts at" (a datetime) - the
    # website renders its 09:00 placeholder only for the former, so the two must not
    # collapse into one type.
    sched = parse(
        {
            "exams": [
                {"name": "MidTerm Exam", "date": "2026-11-03"},
                {"name": "Final Exam", "date": "2026-12-15T14:00"},
            ]
        }
    )
    midterm, final = sched.exams
    assert midterm.date == date(2026, 11, 3)
    assert not isinstance(midterm.date, datetime)
    assert final.date == datetime(2026, 12, 15, 14, 0, tzinfo=BERLIN)
    assert final.date.utcoffset() == BERLIN.utcoffset(datetime(2026, 12, 15, 14, 0))


def test_exam_yaml_native_date_and_datetime_objects():
    # PyYAML hands us real date/datetime objects, not strings, for unquoted values.
    sched = parse(
        {
            "exams": [
                {"name": "Whole day", "date": date(2026, 11, 3)},
                {"name": "Timed", "date": datetime(2026, 12, 15, 14, 0)},
            ]
        }
    )
    assert sched.exams[0].date == date(2026, 11, 3)
    assert sched.exams[1].date == datetime(2026, 12, 15, 14, 0, tzinfo=BERLIN)


def test_exam_explicit_offset_is_honoured_not_overridden():
    sched = parse(
        {
            "timezone": "Europe/Berlin",
            "exams": [{"name": "Remote", "date": "2026-12-15T14:00+00:00"}],
        }
    )
    assert sched.exams[0].date.utcoffset().total_seconds() == 0


def test_exam_timezone_comes_from_the_cohort_setting():
    sched = parse(
        {"timezone": "Pacific/Niue", "exams": [{"name": "E", "date": "2026-12-15T14:00"}]}
    )
    assert sched.exams[0].date.tzinfo == ZoneInfo("Pacific/Niue")


def test_exam_without_a_usable_date_is_dropped():
    assert parse({"exams": [{"name": "No date"}, {"name": "Bad", "date": "soon"}]}).exams == []


def test_assignment_bare_date_is_rejected_only_the_nested_form_is_accepted():
    # `assignments: {slug: date}` (no nested due/grace_days) is not the documented schema.
    assert parse({"assignments": {"assignment-1": "2026-10-13"}}).assignments == {}


def test_assignment_without_due_is_skipped():
    assert parse({"assignments": {"assignment-1": {"grace_days": 2}}}).assignments == {}


def test_calendar_event_is_the_canonical_key_when_is_a_legacy_alias():
    meta = {
        "materials_releases": {
            "new-style": {"calendar_event": "2026-09-15T10:00", "deploy": []},
            "old-style": {"when": "2026-09-01T09:00", "deploy": []},
            "both": {
                # calendar_event wins - `when` is only read for schedules written
                # before the rename
                "calendar_event": "2026-09-22T10:00",
                "when": "2026-09-22T09:00",
            },
        }
    }
    releases = {r.label: r for r in parse(meta).releases}
    assert releases["new-style"].when.isoformat().startswith("2026-09-15T10:00")
    assert releases["old-style"].when.isoformat().startswith("2026-09-01T09:00")
    assert releases["both"].when.isoformat().startswith("2026-09-22T10:00")


def test_deploy_datetime_parses_and_defaults_to_none():
    meta = {
        "materials_releases": {
            "session_2": {
                "calendar_event": "2026-09-15T10:00",
                "deploy": [
                    {
                        "source_repo": "cm-f2026",
                        "source_path": "lectures/02_intro",
                        "deploy_datetime": "2026-09-15T09:00",
                    },
                    {"source_repo": "cm-f2026", "source_path": "readings/02_intro"},
                ],
            }
        }
    }
    (r,) = parse(meta).releases
    early, at_class = r.deploy
    assert early.deploy_datetime.isoformat().startswith("2026-09-15T09:00")
    assert at_class.deploy_datetime is None
    # due_deploys: the early copy fires before the class, the other at it
    tz = early.deploy_datetime.tzinfo
    between = datetime(2026, 9, 15, 9, 30, tzinfo=tz)
    assert r.due_deploys(between) == [early]
    assert r.due_deploys(datetime(2026, 9, 15, 10, 0, tzinfo=tz)) == [early, at_class]


def test_display_only_entry_is_kept_with_its_title():
    meta = {
        "materials_releases": {
            "project-clinic": {"calendar_event": "2026-11-17T10:00", "title": "Project clinic"}
        }
    }
    (r,) = parse(meta).releases
    assert r.is_event_only and r.title == "Project clinic"


def test_malformed_deploy_datetime_falls_back_to_the_calendar_event():
    meta = {
        "materials_releases": {
            "s": {
                "calendar_event": "2026-09-15T10:00",
                "deploy": [
                    {
                        "source_repo": "cm-f2026",
                        "source_path": "lectures/02_intro",
                        "deploy_datetime": "not-a-date",
                    }
                ],
            }
        }
    }
    (r,) = parse(meta).releases
    assert r.deploy[0].deploy_datetime is None  # ships at the calendar_event


def test_max_team_size_parses_and_defaults_to_none():
    meta = {
        "assignments": {
            "assignment-4-project": {"due": "2026-11-15", "max_team_size": 3},
            "assignment-1": {"due": "2026-10-13"},
            "bad": {"due": "2026-10-20", "max_team_size": "lots"},
        }
    }
    entries = parse(meta).assignments
    assert entries["assignment-4-project"].max_team_size == 3
    assert entries["assignment-1"].max_team_size is None
    assert entries["bad"].max_team_size is None  # malformed -> silently dropped


def test_assignment_handout_parses():
    meta = {
        "assignments": {
            "assignment-1": {"due": "2026-10-13", "handout": "2026-09-22T09:00"},
            "assignment-2": {"due": "2026-11-10"},
        }
    }
    entries = parse(meta).assignments
    assert entries["assignment-1"].handout.isoformat().startswith("2026-09-22T09:00")
    assert entries["assignment-2"].handout is None


def test_tbc_calendar_event_keeps_an_undated_entry():
    meta = {
        "materials_releases": {
            "guest-lecture": {"calendar_event": "tbc", "title": "Guest lecture"},
            "dated": {"calendar_event": "2026-09-15T10:00", "deploy": []},
            "dropped": {"deploy": []},  # no date, no tbc -> gone
        }
    }
    releases = parse(meta).releases
    assert [r.label for r in releases] == ["dated", "guest-lecture"]  # TBC sorts last
    gl = releases[-1]
    assert gl.when is None and gl.tbc and gl.is_event_only
    # undated -> nothing can ever be due
    assert gl.due_deploys(datetime(2099, 1, 1, tzinfo=ZoneInfo("UTC"))) == []


def test_tbc_flag_keeps_a_provisional_date_firing():
    meta = {
        "materials_releases": {
            "clinic": {"calendar_event": "2026-11-17T10:00", "tbc": True},
        },
        "exams": [
            {"name": "MidTerm", "date": "2026-11-03", "tbc": True},
            {"name": "Resit", "date": "tbc"},
            {"name": "Broken", "date": "not-a-date"},  # no date, no tbc -> dropped
        ],
    }
    sched = parse(meta)
    (clinic,) = sched.releases
    assert clinic.tbc and clinic.when is not None  # provisional: still fires
    midterm, resit = sched.exams
    assert midterm.tbc and midterm.date is not None
    assert resit.tbc and resit.date is None


def test_assignment_type_parses_and_rejects_unknown_values():
    meta = {
        "assignments": {
            "assignment-4-project": {"due": "2026-11-15", "type": "group"},
            "assignment-1": {"due": "2026-10-13", "type": "Individual"},
            "assignment-2": {"due": "2026-10-27"},
            "typo": {"due": "2026-11-01", "type": "grp"},
        }
    }
    entries = parse(meta).assignments
    assert entries["assignment-4-project"].type == "group"
    assert entries["assignment-1"].type == "individual"  # case-normalised
    assert entries["assignment-2"].type is None
    assert entries["typo"].type is None  # unknown value -> silently dropped
