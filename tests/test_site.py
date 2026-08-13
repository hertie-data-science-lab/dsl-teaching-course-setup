"""site.py schedule wiring: the cohort website's session rows take their dates from
schedule.yml's materials_releases (not a synthesised weekly guess), joined to the released
folders by ordinal. A wrong mapping here silently mis-dates the whole schedule page."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import yaml

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


def test_session_dates_use_the_event_datetime_not_the_deploy_datetime():
    # The site announces the class; the copies may ship on their own clocks.
    s = Schedule(
        releases=[
            Release(
                "week-2",
                datetime(2026, 9, 15, 10, 0, tzinfo=BERLIN),
                deploy=[
                    Deploy(
                        "cm",
                        "lectures/02_intro",
                        "materials",
                        None,
                        deploy_datetime=datetime(2026, 9, 15, 9, 0, tzinfo=BERLIN),
                    )
                ],
            )
        ]
    )
    assert site._session_dates(s)["2"] == datetime(2026, 9, 15, 10, 0, tzinfo=BERLIN)


def test_raw_event_entry_renders_a_display_only_schedule_row():
    from datetime import date as date_cls

    r = Release("project-clinic", datetime(2026, 11, 17, 10, 0, tzinfo=BERLIN))
    out = site._raw_event_entry(r, date_cls(2026, 12, 18))
    assert "type: raw_event" in out
    assert 'name: "Project Clinic"' in out  # prettified from the label
    assert "date: 2026-11-17T10:00:00" in out
    titled = Release(
        "project-clinic", datetime(2026, 11, 17, 10, 0, tzinfo=BERLIN), title="Bring your data"
    )
    assert 'name: "Bring your data"' in site._raw_event_entry(titled, date_cls(2026, 12, 18))


def test_cohort_site_links_back_to_the_cohort_org(monkeypatch, tmp_path):
    # The footer's GitHub link (site.github_org) is the cohort site's only click-back; it
    # must point at THIS cohort org, not the template default or the course org.
    captured = {}
    monkeypatch.setattr(
        site, "_sync_site_repo", lambda org, build: captured.update(plan=build(tmp_path)) or 0
    )
    monkeypatch.setattr(site.seed, "discover_cohort_repos", lambda orgs: [])
    monkeypatch.setattr(site.seed, "discover_release_sources", lambda org, repos: [])
    monkeypatch.setattr(site.seed, "discover_assignments", lambda org: [])
    monkeypatch.setattr(site, "_yaml_file", lambda *a: {})
    monkeypatch.setattr(site.schedule, "load", lambda org: Schedule())
    monkeypatch.setattr(site, "_people_yaml", lambda *a, **k: "people: []\n")
    assert site.sync_site("Course-Org", "Cohort-f2026") == 0
    assert captured["plan"].config["github_org"] == "Cohort-f2026"


def test_course_description_flows_from_course_metadata_into_config(monkeypatch, tmp_path):
    # course_description is declared once in the course org's dsl-course.yml and pushed to
    # every cohort site. Undeclared, it must not be written at all - the site repo keeps
    # whatever blurb it has.
    captured = {}
    monkeypatch.setattr(
        site, "_sync_site_repo", lambda org, build: captured.update(plan=build(tmp_path)) or 0
    )
    monkeypatch.setattr(site.seed, "discover_cohort_repos", lambda orgs: [])
    monkeypatch.setattr(site.seed, "discover_release_sources", lambda org, repos: [])
    monkeypatch.setattr(site.seed, "discover_assignments", lambda org: [])
    monkeypatch.setattr(site.schedule, "load", lambda org: Schedule())
    monkeypatch.setattr(site, "_people_yaml", lambda *a, **k: "people: []\n")

    monkeypatch.setattr(site, "_yaml_file", lambda *a: {})
    assert site.sync_site("Course-Org", "Cohort-f2026") == 0
    assert "course_description" not in captured["plan"].config

    monkeypatch.setattr(site, "_yaml_file", lambda *a: {"course_description": "Nets, from 0."})
    assert site.sync_site("Course-Org", "Cohort-f2026") == 0
    cfg = site._set_config(
        'course_name: "x"\ncourse_description: "old"\ncourse_code: "y"\n',
        "course_description",
        captured["plan"].config["course_description"],
    )
    assert yaml.safe_load(cfg)["course_description"] == "Nets, from 0."
    assert yaml.safe_load(cfg)["course_code"] == "y"  # neighbours untouched


def test_set_config_writes_one_line_over_a_block_scalar():
    # A faculty `>` block in dsl-course.yml, and/or one already in _config.yml: either way
    # the result must stay valid YAML on one line, its body not stranded as loose text.
    cfg = site._set_config(
        "course_description: >\n  an old\n  folded blurb\ncourse_code: 'y'\n",
        "course_description",
        "line one\nline two\n",
    )
    assert yaml.safe_load(cfg) == {"course_description": "line one line two", "course_code": "y"}


def test_tbc_rows_render_with_theme_flags():
    from datetime import date as date_cls

    # Undated (event_datetime: tbc): sortable end-of-term placeholder + dateless flag,
    # so the theme prints "TBC" instead of the placeholder date.
    undated = Release("guest-lecture", None, title="Guest lecture", tbc=True)
    out = site._raw_event_entry(undated, date_cls(2026, 12, 18))
    assert "tbc: true" in out and "dateless: true" in out
    assert "date: 2026-12-18T09:00:00" in out
    # Provisionally dated (tbc: true): real date kept, marker only.
    dated = Release(
        "project-clinic", datetime(2026, 11, 17, 10, 0, tzinfo=BERLIN), tbc=True
    )
    out = site._raw_event_entry(dated, date_cls(2026, 12, 18))
    assert "tbc: true" in out and "dateless" not in out
    assert "date: 2026-11-17T10:00:00" in out
    # Exams: same two shapes.
    out = site._exam_entry("Resit Exam", date_cls(2026, 12, 18), tbc=True, dateless=True)
    assert "dateless: true" in out
    out = site._exam_entry("MidTerm Exam", date_cls(2026, 11, 3), tbc=True)
    assert "tbc: true" in out and "dateless" not in out


def test_site_still_builds_when_schedule_yml_does_not_parse(monkeypatch, tmp_path, capsys):
    # The incident: unparseable schedule.yml crashed schedule.load, which crashed BOTH the
    # hourly Scheduled release AND Sync site - so the site kept the template's "Fall 2025"
    # placeholders. schedule.load now degrades to an empty Schedule, and the sync must
    # complete: course identity + inferred semester land, dates are synthesised.
    from tests.test_schedule import MALFORMED_SCHEDULE

    captured = {}
    monkeypatch.setattr(
        site, "_sync_site_repo", lambda org, build: captured.update(plan=build(tmp_path)) or 0
    )
    monkeypatch.setattr(site.seed, "discover_cohort_repos", lambda orgs: [])
    monkeypatch.setattr(site.seed, "discover_release_sources", lambda org, repos: [])
    monkeypatch.setattr(site.seed, "discover_assignments", lambda org: [])
    monkeypatch.setattr(site, "_yaml_file", lambda *a: {"course_name": "Deep Learning"})
    monkeypatch.setattr(site, "_people_yaml", lambda *a, **k: "people: []\n")
    # the REAL schedule.load, fed the malformed file
    monkeypatch.setattr(
        site.schedule, "get_file_content", lambda org, repo, path: MALFORMED_SCHEDULE
    )

    assert site.sync_site("Course-Org", "Cohort-f2026") == 0

    plan = captured["plan"]
    assert plan.config["course_name"] == "Deep Learning"
    assert plan.config["course_semester"] == "Fall 2026"
    # no schedule data: the exam rows fall back to the synthesised mid/end-term stubs
    assert {"midterm.md", "final.md"} <= set(plan.collections["_events"])
    assert "is NOT valid YAML" in capsys.readouterr().err
