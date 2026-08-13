"""dsl_course.schedule pure core - classroom-config/schedule.yml is the single home for a
cohort's release plan (releases), due dates (assignments), and display-only calendar rows
(events); a wrong parse here silently mis-times a release or mis-pins a grading deadline,
so it's the bit that must be right. Times are timezone-aware (naive -> Europe/Berlin by
default).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from dsl_course import schedule
from dsl_course.schedule import (
    Deploy,
    Event,
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
    assert (
        aware.utcoffset().total_seconds() == 0
    )  # explicit offset honoured, not overridden


def test_parse_full_schedule():
    meta = {
        "timezone": "Europe/Berlin",
        "semester_start": "2026-09-07",
        "semester_end": "2026-12-18",
        "releases": {
            "session_2": {
                "event_datetime": "2026-09-15T14:00",
                "deploy": [
                    {
                        "course_source_repo": "cm-f2026",
                        "course_source_path": "lectures/02_intro",
                        "cohort_dest_repo": "materials",
                        "cohort_dest_path": "lectures/02_intro",
                    }
                ],
            },
            "a1-handout": {
                "event_datetime": "2026-10-15T00:00",
                "assignment": "assignment-1-f2026",
            },
        },
        "assignments": {
            "assignment-1": {
                "due_datetime": "2026-10-13",
                "grading_datetime": "2026-10-15",
            }
        },
        "events": {
            "final": {"type": "exam", "title": "Final", "event_datetime": "2026-12-15"},
            "project-clinic": {
                "title": "Project Clinic",
                "event_datetime": "2026-10-14T10:00",
            },
        },
    }
    sched = parse(meta)
    assert sched.semester_start == date(2026, 9, 7)
    assert [r.label for r in sched.releases] == [
        "session_2",
        "a1-handout",
    ]  # sorted by when
    s2 = sched.releases[0]
    assert s2.deploy == [
        Deploy("cm-f2026", "lectures/02_intro", "materials", "lectures/02_intro")
    ]
    assert sched.releases[1].assignment == "assignment-1-f2026"
    assert (
        sched.assignments["assignment-1"]
        .due_datetime.isoformat()
        .startswith("2026-10-13T23:59:59")
    )
    assert (
        sched.assignments["assignment-1"]
        .grading_datetime.isoformat()
        .startswith("2026-10-15")
    )
    # events are display-only rows, in calendar order; `type` defaults to special_event
    assert sched.events == [
        Event(
            label="project-clinic",
            title="Project Clinic",
            when=datetime(2026, 10, 14, 10, 0, tzinfo=BERLIN),
            type="special_event",
        ),
        Event(label="final", title="Final", when=date(2026, 12, 15), type="exam"),
    ]


def test_parse_empty_is_safe():
    assert parse({}) == Schedule()
    assert parse(None) == Schedule()


def test_release_without_when_is_dropped():
    meta = {
        "releases": {
            "ok": {"event_datetime": "2026-09-01", "deploy": []},
            "nope": {"deploy": []},
        }
    }
    assert [r.label for r in parse(meta).releases] == ["ok"]


def test_deploy_accepts_single_mapping_defaults_cohort_dest_path_none():
    meta = {
        "releases": {
            "s": {
                "event_datetime": "2026-09-01",
                "deploy": {
                    "course_source_repo": "cm",
                    "course_source_path": "lectures/00_x",
                },
            }
        }
    }
    assert parse(meta).releases[0].deploy == [
        Deploy("cm", "lectures/00_x", "materials", None)
    ]


def test_deploy_entry_missing_source_is_skipped():
    meta = {
        "releases": {
            "s": {
                "event_datetime": "2026-09-01",
                "deploy": [{"course_source_repo": "cm"}, {"course_source_path": "x"}],
            }
        }
    }
    assert parse(meta).releases[0].deploy == []


def test_deploy_entry_using_the_old_unprefixed_keys_is_skipped():
    # The org prefixes are a hard rename with no alias handling, so a cohort whose
    # schedule.yml predates it must lose the copy outright rather than half-parse it.
    meta = {
        "releases": {
            "s": {
                "event_datetime": "2026-09-01",
                "deploy": [
                    {
                        "source_repo": "cm",
                        "source_path": "lectures/00_x",
                        "dest_repo": "materials",
                    }
                ],
            }
        }
    }
    assert parse(meta).releases[0].deploy == []


def test_event_bare_date_stays_a_date_timed_event_becomes_aware_datetime():
    # `event_datetime:` doubles as "whole day" (a plain date) and "starts at" (a
    # datetime) - the website renders its placeholder time only for the former, so the
    # two must not collapse into one type.
    sched = parse(
        {
            "events": {
                "mid-term": {"type": "exam", "event_datetime": "2026-11-03"},
                "final": {"type": "exam", "event_datetime": "2026-12-15T14:00"},
            }
        }
    )
    midterm, final = sched.events
    assert midterm.when == date(2026, 11, 3)
    assert not isinstance(midterm.when, datetime)
    assert final.when == datetime(2026, 12, 15, 14, 0, tzinfo=BERLIN)
    assert final.when.utcoffset() == BERLIN.utcoffset(datetime(2026, 12, 15, 14, 0))


def test_event_yaml_native_date_and_datetime_objects():
    # PyYAML hands us real date/datetime objects, not strings, for unquoted values.
    sched = parse(
        {
            "events": {
                "whole-day": {"event_datetime": date(2026, 11, 3)},
                "timed": {"event_datetime": datetime(2026, 12, 15, 14, 0)},
            }
        }
    )
    assert sched.events[0].when == date(2026, 11, 3)
    assert sched.events[1].when == datetime(2026, 12, 15, 14, 0, tzinfo=BERLIN)


def test_event_explicit_offset_is_honoured_not_overridden():
    sched = parse(
        {
            "timezone": "Europe/Berlin",
            "events": {"remote": {"event_datetime": "2026-12-15T14:00+00:00"}},
        }
    )
    assert sched.events[0].when.utcoffset().total_seconds() == 0


def test_event_timezone_comes_from_the_cohort_setting():
    sched = parse(
        {
            "timezone": "Pacific/Niue",
            "events": {"e": {"event_datetime": "2026-12-15T14:00"}},
        }
    )
    assert sched.events[0].when.tzinfo == ZoneInfo("Pacific/Niue")


def test_event_without_a_usable_date_is_dropped():
    assert (
        parse(
            {"events": {"no-date": {"title": "X"}, "bad": {"event_datetime": "soon"}}}
        ).events
        == []
    )


def test_event_type_defaults_to_special_event_and_rejects_unknown_values():
    meta = {
        "events": {
            "mid-term": {"type": "Exam", "event_datetime": "2026-11-03"},
            "clinic": {"event_datetime": "2026-10-14T10:00"},
            "typo": {"type": "examm", "event_datetime": "2026-10-20"},
        }
    }
    events = {e.label: e for e in parse(meta).events}
    assert events["mid-term"].type == "exam"  # case-normalised
    assert events["clinic"].type == "special_event"
    assert (
        events["typo"].type == "special_event"
    )  # unknown value -> the display default


def test_events_sort_by_date_with_undated_last():
    meta = {
        "events": {
            "resit": {"event_datetime": "tbc"},
            "final": {"type": "exam", "event_datetime": "2026-12-15T14:00"},
            "clinic": {"event_datetime": date(2026, 10, 14)},
        }
    }
    # whole-day and timed entries sort against each other; TBC rows go to the end
    assert [e.label for e in parse(meta).events] == ["clinic", "final", "resit"]


def test_tbc_semantics_for_events():
    meta = {
        "events": {
            "mid-term": {"type": "exam", "event_datetime": "2026-11-03", "tbc": True},
            "resit": {"type": "exam", "event_datetime": "tbc"},
            "broken": {"event_datetime": "not-a-date"},  # no date, no tbc -> dropped
        }
    }
    midterm, resit = parse(meta).events
    assert midterm.tbc and midterm.when == date(2026, 11, 3)  # provisional, but dated
    assert resit.tbc and resit.when is None


def test_assignment_bare_date_is_rejected_only_the_nested_form_is_accepted():
    # `assignments: {slug: date}` (no nested due_datetime) is not the documented schema.
    assert parse({"assignments": {"assignment-1": "2026-10-13"}}).assignments == {}


def test_assignment_without_due_is_skipped():
    assert (
        parse({"assignments": {"assignment-1": {"max_team_size": 2}}}).assignments == {}
    )


def test_event_datetime_is_the_only_accepted_key():
    meta = {
        "releases": {
            "new-style": {"event_datetime": "2026-09-15T10:00", "deploy": []},
            "old-alias": {"calendar_event": "2026-09-01T09:00", "deploy": []},
            "older-alias": {"when": "2026-08-01T09:00", "deploy": []},
        }
    }
    releases = {r.label: r for r in parse(meta).releases}
    assert list(releases) == ["new-style"]
    assert releases["new-style"].when.isoformat().startswith("2026-09-15T10:00")


def test_deploy_datetime_parses_and_defaults_to_none():
    meta = {
        "releases": {
            "session_2": {
                "event_datetime": "2026-09-15T10:00",
                "deploy": [
                    {
                        "course_source_repo": "cm-f2026",
                        "course_source_path": "lectures/02_intro",
                        "deploy_datetime": "2026-09-15T09:00",
                    },
                    {
                        "course_source_repo": "cm-f2026",
                        "course_source_path": "readings/02_intro",
                    },
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
        "releases": {
            "project-clinic": {
                "event_datetime": "2026-11-17T10:00",
                "title": "Project clinic",
            }
        }
    }
    (r,) = parse(meta).releases
    assert r.is_event_only and r.title == "Project clinic"


def test_malformed_deploy_datetime_falls_back_to_the_event_datetime():
    meta = {
        "releases": {
            "s": {
                "event_datetime": "2026-09-15T10:00",
                "deploy": [
                    {
                        "course_source_repo": "cm-f2026",
                        "course_source_path": "lectures/02_intro",
                        "deploy_datetime": "not-a-date",
                    }
                ],
            }
        }
    }
    (r,) = parse(meta).releases
    assert r.deploy[0].deploy_datetime is None  # ships at the event_datetime


def test_max_team_size_parses_and_defaults_to_none():
    meta = {
        "assignments": {
            "assignment-4-project": {"due_datetime": "2026-11-15", "max_team_size": 3},
            "assignment-1": {"due_datetime": "2026-10-13"},
            "bad": {"due_datetime": "2026-10-20", "max_team_size": "lots"},
        }
    }
    entries = parse(meta).assignments
    assert entries["assignment-4-project"].max_team_size == 3
    assert entries["assignment-1"].max_team_size is None
    assert entries["bad"].max_team_size is None  # malformed -> silently dropped


def test_assignment_handout_parses():
    meta = {
        "assignments": {
            "assignment-1": {
                "due_datetime": "2026-10-13",
                "handout_datetime": "2026-09-22T09:00",
            },
            "assignment-2": {"due_datetime": "2026-11-10"},
        }
    }
    entries = parse(meta).assignments
    assert (
        entries["assignment-1"]
        .handout_datetime.isoformat()
        .startswith("2026-09-22T09:00")
    )
    assert entries["assignment-2"].handout_datetime is None


def test_tbc_event_datetime_keeps_an_undated_entry():
    meta = {
        "releases": {
            "guest-lecture": {"event_datetime": "tbc", "title": "Guest lecture"},
            "dated": {"event_datetime": "2026-09-15T10:00", "deploy": []},
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
        "releases": {
            "clinic": {"event_datetime": "2026-11-17T10:00", "tbc": True},
        },
    }
    (clinic,) = parse(meta).releases
    assert clinic.tbc and clinic.when is not None  # provisional: still fires


def test_assignment_type_parses_and_rejects_unknown_values():
    meta = {
        "assignments": {
            "assignment-4-project": {"due_datetime": "2026-11-15", "type": "group"},
            "assignment-1": {"due_datetime": "2026-10-13", "type": "Individual"},
            "assignment-2": {"due_datetime": "2026-10-27"},
            "typo": {"due_datetime": "2026-11-01", "type": "grp"},
        }
    }
    entries = parse(meta).assignments
    assert entries["assignment-4-project"].type == "group"
    assert entries["assignment-1"].type == "individual"  # case-normalised
    assert entries["assignment-2"].type is None
    assert entries["typo"].type is None  # unknown value -> silently dropped


def test_insert_handout_records_write_once():
    from dsl_course.schedule import _insert_handout

    base = """timezone: Europe/Berlin

assignments:
  assignment-1:
    due_datetime: 2026-10-13
  assignment-2:
    handout_datetime: 2026-09-29T14:00
    due_datetime: 2026-10-27
"""
    # inserted into the existing entry, directly under the slug line
    out = _insert_handout(base, "assignment-1", "2026-09-22T14:05")
    assert "handout_datetime: 2026-09-22T14:05" in out
    assert out.index("assignment-1:") < out.index("handout_datetime: 2026-09-22T14:05")
    # write-once: an existing handout (scheduled or recorded) is never touched
    assert _insert_handout(base, "assignment-2", "2026-10-01T00:00") is None
    # unknown slug: appended into the block with a due_datetime TODO
    out = _insert_handout(base, "assignment-9", "2026-11-01T09:00")
    assert "assignment-9:" in out and "handout_datetime: 2026-11-01T09:00" in out
    assert "TODO" in out
    # no assignments block at all: one is created
    out = _insert_handout(
        "timezone: Europe/Berlin\n", "assignment-1", "2026-09-22T14:05"
    )
    assert "assignments:" in out and "handout_datetime: 2026-09-22T14:05" in out


def test_record_handout_round_trips_through_the_parser(monkeypatch):
    import yaml

    from dsl_course import schedule as S

    store = {"text": "assignments:\n  assignment-1:\n    due_datetime: 2026-10-13\n"}
    monkeypatch.setattr(S, "get_file_content", lambda org, repo, path: store["text"])
    writes = []
    monkeypatch.setattr(
        "dsl_course.utils.put_file",
        lambda org, repo, path, content, msg: writes.append(content.decode()) or True,
    )
    S.record_handout("Cohort-f2026", "assignment-1", "2026-09-22T14:05")
    (new,) = writes
    sched = S.parse(yaml.safe_load(new))
    assert (
        sched.assignments["assignment-1"]
        .handout_datetime.isoformat()
        .startswith("2026-09-22T14:05")
    )
    # second call sees the recorded value and is a no-op
    store["text"] = new
    S.record_handout("Cohort-f2026", "assignment-1", "2026-09-23T09:00")
    assert len(writes) == 1


# --------------------------------------------------------- a file that does not parse
#
# The incident: a faculty member left an unclosed flow mapping in schedule.yml, so
# `yaml.safe_load` raised inside `schedule.load` and took down BOTH the hourly Scheduled
# release run AND Sync site for that cohort - the site kept showing the template's
# placeholders. `load` now treats an unparseable file exactly as an absent one (empty
# Schedule) and says so loudly.
#
# NB the literal below is the incident's flow mapping. tests/ is out of scope for the
# block-style guard (tests/test_yaml_block_style.py sweeps dsl_course/*.py, the repo's
# *.yml and the docs' yaml fences), and this is a malformed counter-example, not a
# faculty-facing example to copy.
MALFORMED_SCHEDULE = """\
materials_releases:
  lab-1:
    event_datetime: 2026-09-03T14:00
    deploy:
      - {course_source_repo: course-materials-f2026,
        course_source_path: labs/01_lab
"""


def test_unparseable_schedule_loads_as_empty_and_says_so_loudly(monkeypatch, capsys):
    from dsl_course import schedule as S

    monkeypatch.setattr(
        S, "get_file_content", lambda org, repo, path: MALFORMED_SCHEDULE
    )

    sched = S.load("Cohort-f2026")

    # same shape a missing schedule.yml yields - nothing scheduled, nothing raised
    assert sched == Schedule()
    err = capsys.readouterr().err
    # self-diagnosing: which cohort, which file, the parser's own line/column, what to do
    assert "Cohort-f2026/classroom-config/schedule.yml is NOT valid YAML" in err
    assert "line 5" in err and "flow mapping" in err
    assert "fix classroom-config/schedule.yml on main" in err
    assert "NOTHING is scheduled" in err


def test_a_wellformed_schedule_is_untouched_by_the_yaml_guard(monkeypatch, capsys):
    from dsl_course import schedule as S

    good = (
        "timezone: Europe/Berlin\n"
        "semester_start: 2026-09-07\n"
        "releases:\n"
        "  lab-1:\n"
        "    event_datetime: 2026-09-03T14:00\n"
        "    deploy:\n"
        "      - course_source_repo: course-materials-f2026\n"
        "        course_source_path: labs/01_lab\n"
    )
    monkeypatch.setattr(S, "get_file_content", lambda org, repo, path: good)

    sched = S.load("Cohort-f2026")

    assert sched.semester_start == date(2026, 9, 7)
    assert [r.label for r in sched.releases] == ["lab-1"]
    assert sched.releases[0].deploy[0].course_source_path == "labs/01_lab"
    assert capsys.readouterr().err == ""


def test_a_non_mapping_schedule_still_loads_as_empty(monkeypatch):
    # parses fine, but isn't a mapping - the pre-existing isinstance guard, pinned here
    # so the new try/except can't be mistaken for the only defence.
    from dsl_course import schedule as S

    monkeypatch.setattr(
        S, "get_file_content", lambda org, repo, path: "- just\n- a list\n"
    )
    assert S.load("Cohort-f2026") == Schedule()


# --------------------------------------------------------------- dropped-entry reporting
# A malformed entry cannot be rescued, but it must never vanish quietly: valid YAML with a
# typo'd key is the one schedule fault that leaves a green run and a short term plan.


def test_every_kind_of_dropped_entry_is_recorded_with_its_cost():
    sched = parse(
        {
            "releases": {
                "ok": {
                    "event_datetime": "2026-09-15T10:00",
                    "deploy": [
                        {"course_source_repo": "cm", "course_source_path": "l/01"},
                        {"source_repo": "cm", "source_path": "l/02"},  # pre-rename keys
                    ],
                },
                "typo": {"evetn_datetime": "2026-09-22T10:00"},
            },
            "assignments": {
                "a1": {"due_datetime": "2026-10-13"},
                "a2": {"due_date": "2026-11-13"},
            },
            "events": {"mid-term": {"type": "exam"}},
        }
    )
    # the well-formed entries still parse - one bad entry never poisons its neighbours
    assert [r.label for r in sched.releases] == ["ok"]
    assert len(sched.releases[0].deploy) == 1
    assert list(sched.assignments) == ["a1"]

    where = [d.split(":")[0] for d in sched.dropped]
    assert where == [
        "releases.ok.deploy[1]",
        "releases.typo",
        "assignments.a2",
        "events.mid-term",
    ]
    # each line names the field at fault AND what the cohort loses by it
    assert (
        "`course_source_repo`" in sched.dropped[0] and "never ships" in sched.dropped[0]
    )
    assert (
        "`event_datetime`" in sched.dropped[1] and "nothing deploys" in sched.dropped[1]
    )
    assert "`due_datetime`" in sched.dropped[2] and "no autograding" in sched.dropped[2]
    assert (
        "`event_datetime`" in sched.dropped[3] and "never appears" in sched.dropped[3]
    )


def test_an_unknown_timezone_is_reported_rather_than_silently_swapped():
    sched = parse(
        {"timezone": "Europe/Berlyn", "events": {"e": {"event_datetime": "2026-11-03"}}}
    )
    assert len(sched.dropped) == 1
    assert "Europe/Berlyn" in sched.dropped[0] and "Europe/Berlin" in sched.dropped[0]
    assert sched.events[0].when == date(2026, 11, 3)  # the event itself survives


def test_a_clean_schedule_drops_nothing():
    assert parse({}).dropped == []
    assert (
        parse(
            {
                "releases": {"s": {"event_datetime": "2026-09-01", "deploy": []}},
                "assignments": {"a1": {"due_datetime": "2026-10-13"}},
                "events": {"e": {"event_datetime": "2026-11-03"}},
            }
        ).dropped
        == []
    )


def test_tbc_entries_are_not_drops():
    # `tbc` is a deliberate "date not settled yet", not a malformed date
    sched = parse(
        {
            "releases": {"r": {"event_datetime": "tbc"}},
            "events": {"guest": {"event_datetime": "tbc"}},
        }
    )
    assert sched.dropped == []
    assert len(sched.releases) == 1 and len(sched.events) == 1


def test_load_logs_every_dropped_entry_loudly(monkeypatch, capsys):
    from dsl_course import schedule as S

    monkeypatch.setattr(
        S,
        "get_file_content",
        lambda org, repo, path: (
            "assignments:\n  assignment-2:\n    due_date: 2026-11-13\n"
        ),
    )

    sched = S.load("Cohort-f2026")

    assert sched.assignments == {}
    err = capsys.readouterr().err
    # which cohort, which file, which entry, which field, and what it costs
    assert "Cohort-f2026/classroom-config/schedule.yml" in err
    assert "DROPPED" in err
    assert "assignments.assignment-2" in err
    assert "`due_datetime`" in err
    assert "no autograding" in err


# ------------------------------------------------------- validating a file on disk (CI)


def test_load_file_reports_unparseable_yaml_rather_than_treating_it_as_empty(tmp_path):
    # The opposite stance to `load`: the cron must survive a typo, a validator must fail on
    # one. A broken file that silently validated would be worse than no validator at all.
    bad = tmp_path / "schedule.yml"
    bad.write_text("releases:\n  a:\n    deploy:\n      - {x: 1,\n")
    sched, error = schedule.load_file(str(bad))
    assert sched is None
    assert "not valid YAML" in error and "line" in error


def test_load_file_reports_a_missing_file(tmp_path):
    sched, error = schedule.load_file(str(tmp_path / "nope.yml"))
    assert sched is None and "cannot read" in error


def test_load_file_rejects_valid_yaml_that_is_not_a_mapping(tmp_path):
    p = tmp_path / "schedule.yml"
    p.write_text("- just\n- a list\n")
    sched, error = schedule.load_file(str(p))
    assert sched is None and "not a mapping" in error


def test_load_file_parses_and_surfaces_drops(tmp_path):
    p = tmp_path / "schedule.yml"
    p.write_text("assignments:\n  assignment-2:\n    due_date: 2026-11-13\n")
    sched, error = schedule.load_file(str(p))
    assert error is None
    assert sched.assignments == {} and len(sched.dropped) == 1


@pytest.mark.parametrize(
    "path",
    [
        "example-course/cohort-org/schedule.yml",
        "templates/classroom-config/schedule.yml",
    ],
)
def test_shipped_schedules_parse_with_nothing_dropped(path):
    # The CI gate. The example is what faculty copy and the template is what every new
    # cohort is seeded with, so either one silently dropping an entry would teach the
    # mistake rather than catch it.
    full = Path(__file__).resolve().parents[1] / path
    sched, error = schedule.load_file(str(full))
    assert error is None, error
    assert sched.dropped == [], f"{path} drops entries:\n" + "\n".join(sched.dropped)
