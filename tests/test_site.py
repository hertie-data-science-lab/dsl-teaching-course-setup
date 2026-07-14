"""site.py schedule wiring: the cohort website's session rows take their dates from
schedule.yml's materials_releases (not a synthesised weekly guess), joined to the released
folders by ordinal. A wrong mapping here silently mis-dates the whole schedule page."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from dsl_course import site
from dsl_course.schedule import Deploy, Release, Schedule

BERLIN = ZoneInfo("Europe/Berlin")


def _sched(releases: list[Release]) -> Schedule:
    return Schedule(releases=releases)


def test_session_dates_maps_folder_ordinal_to_release_when():
    s = _sched(
        [
            Release(
                "week-2",
                datetime(2026, 9, 15, 14, 0, tzinfo=BERLIN),
                deploy=[
                    Deploy("cm", "lectures/02_intro", "lectures", None),
                    Deploy("cm", "labs/02_x", "labs", None),
                ],
            ),
            Release(
                "week-1",
                datetime(2026, 9, 8, 14, 0, tzinfo=BERLIN),
                deploy=[Deploy("cm", "lectures/01_a", "lectures", "01_a")],
            ),
        ]
    )
    sw = site._session_dates(s)
    assert sw["2"] == datetime(2026, 9, 15, 14, 0, tzinfo=BERLIN)
    assert sw["1"] == datetime(2026, 9, 8, 14, 0, tzinfo=BERLIN)  # keyed off dest_path ordinal


def test_session_dates_earliest_release_wins_for_an_ordinal():
    s = _sched(
        [
            Release("late", datetime(2026, 9, 15, 14, 0, tzinfo=BERLIN),
                    deploy=[Deploy("cm", "lectures/02_x", "lectures", None)]),
            Release("early", datetime(2026, 9, 10, 9, 0, tzinfo=BERLIN),
                    deploy=[Deploy("cm", "readings/02_y", "materials", None)]),
        ]
    )
    assert site._session_dates(s)["2"] == datetime(2026, 9, 10, 9, 0, tzinfo=BERLIN)


def test_session_dates_ignores_non_ordinal_deploys():
    s = _sched(
        [
            Release("ds", datetime(2026, 10, 20, 9, 30, tzinfo=BERLIN),
                    deploy=[Deploy("data", "week7/housing.csv", "materials", "datasets/housing.csv")]),
        ]
    )
    assert site._session_dates(s) == {}  # not a numbered session folder


def test_lecture_entry_shows_real_time_from_a_datetime():
    md = site._lecture_entry("Cohort", "2", datetime(2026, 9, 15, 14, 30, tzinfo=BERLIN), [])
    assert "date: 2026-09-15T14:30:00" in md


def test_lecture_entry_falls_back_to_0900_for_a_bare_date():
    md = site._lecture_entry("Cohort", "2", date(2026, 9, 15), [])
    assert "date: 2026-09-15T09:00:00" in md
