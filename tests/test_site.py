"""site.py schedule wiring: the cohort website's rows take their dates and their types
from schedule.yml (not a synthesised weekly guess), joined to the released folders by
ordinal AND section - a week's lecture and its lab are separate rows. A wrong mapping here
silently mis-dates the whole schedule page, or hides a lab inside a lecture row."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
import yaml

from dsl_course import site
from dsl_course.schedule import AssignmentEntry, Deploy, Event, Release, Schedule

UTC = ZoneInfo("UTC")

BERLIN = ZoneInfo("Europe/Berlin")
END_OF_TERM = date(2026, 12, 18)


def _sched(releases: list[Release]) -> Schedule:
    return Schedule(releases=releases)


def test_session_dates_maps_folder_ordinal_and_section_to_release_when():
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
    assert sw[("2", "lecture")] == datetime(2026, 9, 15, 14, 0, tzinfo=BERLIN)
    assert sw[("2", "lab")] == datetime(2026, 9, 15, 14, 0, tzinfo=BERLIN)
    # keyed off the cohort_dest_path ordinal; a bare dest folder takes its section from
    # cohort_dest_repo
    assert sw[("1", "lecture")] == datetime(2026, 9, 8, 14, 0, tzinfo=BERLIN)


def test_session_dates_date_a_lab_row_from_its_own_release():
    # Monday's lecture and Wednesday's lab are two entries; the lab row must carry its own
    # time rather than inheriting the (earlier) lecture's.
    s = _sched(
        [
            Release(
                "lecture-3",
                datetime(2026, 9, 15, 10, 0, tzinfo=BERLIN),
                deploy=[Deploy("cm", "lectures/03_week-3", "materials", None)],
            ),
            Release(
                "lab-3",
                datetime(2026, 9, 17, 14, 0, tzinfo=BERLIN),
                deploy=[Deploy("cm", "labs/03_week-3", "materials", None)],
            ),
        ]
    )
    sw = site._session_dates(s)
    assert sw[("3", "lecture")] == datetime(2026, 9, 15, 10, 0, tzinfo=BERLIN)
    assert sw[("3", "lab")] == datetime(2026, 9, 17, 14, 0, tzinfo=BERLIN)


def test_session_dates_earliest_release_wins_for_a_row():
    s = _sched(
        [
            Release(
                "late",
                datetime(2026, 9, 15, 14, 0, tzinfo=BERLIN),
                deploy=[Deploy("cm", "lectures/02_x", "lectures", None)],
            ),
            Release(
                "early",
                datetime(2026, 9, 10, 9, 0, tzinfo=BERLIN),
                deploy=[Deploy("cm", "readings/02_y", "materials", None)],
            ),
        ]
    )
    # readings are lecture material, so both land on the same row - earliest wins
    assert site._session_dates(s)[("2", "lecture")] == datetime(
        2026, 9, 10, 9, 0, tzinfo=BERLIN
    )


def test_session_dates_ignores_non_ordinal_deploys():
    s = _sched(
        [
            Release(
                "ds",
                datetime(2026, 10, 20, 9, 30, tzinfo=BERLIN),
                deploy=[
                    Deploy(
                        "data", "week7/housing.csv", "materials", "datasets/housing.csv"
                    )
                ],
            ),
        ]
    )
    assert site._session_dates(s) == {}  # not a numbered session folder


def test_lecture_entry_shows_real_time_from_a_datetime():
    md = site._lecture_entry(
        "Cohort", "2", datetime(2026, 9, 15, 14, 30, tzinfo=BERLIN), []
    )
    assert "date: 2026-09-15T14:30:00" in md


def test_lecture_entry_falls_back_to_0900_for_a_bare_date():
    md = site._lecture_entry("Cohort", "2", date(2026, 9, 15), [])
    assert "date: 2026-09-15T09:00:00" in md


def test_lecture_entry_renders_a_lab_row_as_its_own_type():
    md = site._lecture_entry("Cohort", "3", date(2026, 9, 17), [], "lab")
    assert "type: lab" in md
    assert 'title: "Lab 3"' in md
    assert "Session 3" not in md
    lec = site._lecture_entry("Cohort", "3", date(2026, 9, 15), [])
    assert "type: lecture" in lec and 'title: "Session 3"' in lec


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
    assert site._session_dates(s)[("2", "lecture")] == datetime(
        2026, 9, 15, 10, 0, tzinfo=BERLIN
    )


def test_event_entry_renders_a_display_only_schedule_row():
    e = Event("project-clinic", "", datetime(2026, 11, 17, 10, 0, tzinfo=BERLIN))
    out = site._event_entry(e, END_OF_TERM)
    assert "type: special_event" in out
    assert 'name: "Project Clinic"' in out  # prettified from the label
    assert "date: 2026-11-17T10:00:00" in out
    assert 'description: ""' in out
    titled = Event(
        "project-clinic",
        "Bring your data",
        datetime(2026, 11, 17, 10, 0, tzinfo=BERLIN),
    )
    assert 'name: "Bring your data"' in site._event_entry(titled, END_OF_TERM)


def test_event_entry_renders_an_exam_as_an_exam_row():
    e = Event("mid-term", "MidTerm Exam", date(2026, 11, 3), type="exam")
    out = site._event_entry(e, END_OF_TERM)
    assert "type: exam" in out
    assert 'description: "MidTerm Exam"' in out
    assert "date: 2026-11-03T09:00:00" in out  # whole day -> the placeholder time
    assert "name:" not in out  # the exam row reads `description`, not `name`


def test_event_entry_title_falls_back_to_the_prettified_label():
    e = Event("resit_exam", "", date(2026, 12, 20), type="exam")
    assert 'description: "Resit Exam"' in site._event_entry(e, END_OF_TERM)


def test_tbc_rows_render_with_theme_flags():
    # Undated (event_datetime: tbc): sortable end-of-term placeholder + dateless flag,
    # so the theme prints "TBC" instead of the placeholder date.
    undated = Event("guest-lecture", "Guest lecture", None, tbc=True)
    out = site._event_entry(undated, END_OF_TERM)
    assert "tbc: true" in out and "dateless: true" in out
    assert "date: 2026-12-18T09:00:00" in out
    # Provisionally dated (tbc: true): real date kept, marker only.
    dated = Event(
        "project-clinic", "", datetime(2026, 11, 17, 10, 0, tzinfo=BERLIN), tbc=True
    )
    out = site._event_entry(dated, END_OF_TERM)
    assert "tbc: true" in out and "dateless" not in out
    assert "date: 2026-11-17T10:00:00" in out
    # Exams: same two shapes.
    out = site._event_entry(
        Event("resit", "Resit Exam", None, "exam", True), END_OF_TERM
    )
    assert "type: exam" in out and "dateless: true" in out
    out = site._event_entry(
        Event("mid-term", "MidTerm Exam", date(2026, 11, 3), "exam", True), END_OF_TERM
    )
    assert "tbc: true" in out and "dateless" not in out


def test_term_date_entry_hides_the_placeholder_time():
    out = site._term_date_entry("Term starts", date(2026, 9, 7))
    assert "type: term_date" in out
    assert "date: 2026-09-07T09:00:00" in out
    assert "hide_time: true" in out  # a term boundary is a whole day, not a 09:00 slot
    assert 'name: "Term starts"' in out  # the name is the row's only text
    assert 'description: ""' in out


def test_assignment_entry_dates_the_released_row_from_the_handout(monkeypatch):
    monkeypatch.setattr(
        site, "get_file_content", lambda *a, **k: "# Assignment 1\nBrief."
    )
    out = site._assignment_entry(
        "Course",
        "assignment-1-f2026",
        datetime(2026, 10, 13, 23, 59, 59, tzinfo=BERLIN),
        datetime(2026, 9, 22, 9, 0, tzinfo=BERLIN),
    )
    # the entry's own row is the "released!" row; the due row lives in due_event
    assert "date: 2026-09-22T09:00:00" in out.split("due_event:")[0]
    assert "    date: 2026-10-13T23:59:59" in out
    # the theme's due row is already labelled "due", so the description just names it
    assert '    description: "Assignment 1"' in out


def test_assignment_entry_falls_back_to_the_due_date_without_a_handout(monkeypatch):
    monkeypatch.setattr(site, "get_file_content", lambda *a, **k: "")
    out = site._assignment_entry("Course", "assignment-2-f2026", date(2026, 11, 10))
    assert out.count("date: 2026-11-10T23:59:00") == 2  # both rows on the due date


def test_assignment_dates_read_the_schedule():
    from dsl_course.schedule import AssignmentEntry

    sched = Schedule(
        assignments={
            "assignment-1": AssignmentEntry(
                course_source_repo="assignment-1-f2026",
                due_datetime=datetime(2026, 10, 13, 23, 59, 59, tzinfo=BERLIN),
                handout_datetime=datetime(2026, 9, 22, 9, 0, tzinfo=BERLIN),
            )
        }
    )
    due, handout = site._assignment_dates(sched, "assignment-1-f2026", date(2026, 1, 1))
    assert due == datetime(2026, 10, 13, 23, 59, 59, tzinfo=BERLIN)
    assert handout == datetime(2026, 9, 22, 9, 0, tzinfo=BERLIN)
    # unscheduled: the synthesised fallback, and no handout row
    assert site._assignment_dates(sched, "assignment-9-f2026", date(2026, 1, 1)) == (
        date(2026, 1, 1),
        None,
    )


def _plan(
    monkeypatch, tmp_path, sched: Schedule, sources=(), assignments=(), files=None
):
    """Run sync_site against a faked org and return the _SitePlan it built. `files` fakes
    the per-source file listing (default: every source is empty)."""
    captured: dict = {}
    monkeypatch.setattr(
        site,
        "_sync_site_repo",
        lambda org, build: captured.update(plan=build(tmp_path)) or 0,
    )
    monkeypatch.setattr(site.seed, "discover_cohort_repos", lambda orgs: [])
    monkeypatch.setattr(
        site.seed, "discover_release_sources", lambda org, repos: list(sources)
    )
    monkeypatch.setattr(
        site.seed, "discover_assignments", lambda org: list(assignments)
    )
    monkeypatch.setattr(site, "_yaml_file", lambda *a: {})
    monkeypatch.setattr(site.schedule, "load", lambda org: sched)
    monkeypatch.setattr(site, "_people_yaml", lambda *a, **k: "people: []\n")
    monkeypatch.setattr(
        site, "_session_files", files or (lambda org, repo, subpath, folder: [])
    )
    monkeypatch.setattr(site, "get_file_content", lambda *a, **k: "")
    assert site.sync_site("Course-Org", "Cohort-f2026") == 0
    return captured["plan"]


def test_cohort_site_links_back_to_the_cohort_org(monkeypatch, tmp_path):
    # The footer's GitHub link (site.github_org) is the cohort site's only click-back; it
    # must point at THIS cohort org, not the template default or the course org.
    plan = _plan(monkeypatch, tmp_path, Schedule())
    assert plan.config["github_org"] == "Cohort-f2026"


def test_a_mixed_week_becomes_a_lecture_row_and_a_lab_row(monkeypatch, tmp_path):
    plan = _plan(
        monkeypatch,
        tmp_path,
        Schedule(
            releases=[
                Release(
                    "lecture-2",
                    datetime(2026, 9, 8, 10, 0, tzinfo=BERLIN),
                    deploy=[Deploy("cm", "lectures/02_week-2", "materials", None)],
                ),
                Release(
                    "lab-2",
                    datetime(2026, 9, 10, 14, 0, tzinfo=BERLIN),
                    deploy=[Deploy("cm", "labs/02_week-2", "materials", None)],
                ),
            ]
        ),
        sources=[
            ("materials", "lectures", "02_week-2", 2),
            ("materials", "readings", "02_week-2", 2),
            ("materials", "labs", "02_week-2", 2),
        ],
    )
    lectures = plan.collections["_lectures"]
    assert sorted(lectures) == ["lab-02.md", "session-02.md"]
    assert "type: lecture" in lectures["session-02.md"]
    assert "date: 2026-09-08T10:00:00" in lectures["session-02.md"]
    assert "type: lab" in lectures["lab-02.md"]
    assert "date: 2026-09-10T14:00:00" in lectures["lab-02.md"]  # its OWN release time


def test_course_description_flows_from_course_metadata_into_config(
    monkeypatch, tmp_path
):
    # course_description is declared once in the course org's dsl-course.yml and pushed to
    # every cohort site. Undeclared, it must not be written at all - the site repo keeps
    # whatever blurb it has.
    captured = {}
    monkeypatch.setattr(
        site,
        "_sync_site_repo",
        lambda org, build: captured.update(plan=build(tmp_path)) or 0,
    )
    monkeypatch.setattr(site.seed, "discover_cohort_repos", lambda orgs: [])
    monkeypatch.setattr(site.seed, "discover_release_sources", lambda org, repos: [])
    monkeypatch.setattr(site.seed, "discover_assignments", lambda org: [])
    monkeypatch.setattr(site.schedule, "load", lambda org: Schedule())
    monkeypatch.setattr(site, "_people_yaml", lambda *a, **k: "people: []\n")

    monkeypatch.setattr(site, "_yaml_file", lambda *a: {})
    assert site.sync_site("Course-Org", "Cohort-f2026") == 0
    assert "course_description" not in captured["plan"].config

    monkeypatch.setattr(
        site, "_yaml_file", lambda *a: {"course_description": "Nets, from 0."}
    )
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
    assert yaml.safe_load(cfg) == {
        "course_description": "line one line two",
        "course_code": "y",
    }


def test_site_still_builds_when_schedule_yml_does_not_parse(
    monkeypatch, tmp_path, capsys
):
    # The incident: unparseable schedule.yml crashed schedule.load, which crashed BOTH the
    # hourly Scheduled release AND Sync site - so the site kept the template's "Fall 2025"
    # placeholders. schedule.load now degrades to an empty Schedule, and the sync must
    # complete: course identity + inferred semester land, dates are synthesised.
    from tests.test_schedule import MALFORMED_SCHEDULE

    captured = {}
    monkeypatch.setattr(
        site,
        "_sync_site_repo",
        lambda org, build: captured.update(plan=build(tmp_path)) or 0,
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


def test_a_week_with_only_one_kind_gets_only_that_row(monkeypatch, tmp_path):
    lab_only = _plan(
        monkeypatch,
        tmp_path,
        Schedule(),
        sources=[("materials", "labs", "03_week-3", 3)],
    )
    assert sorted(lab_only.collections["_lectures"]) == ["lab-03.md"]
    lecture_only = _plan(
        monkeypatch,
        tmp_path,
        Schedule(),
        sources=[("materials", "lectures", "04_week-4", 4)],
    )
    assert sorted(lecture_only.collections["_lectures"]) == ["session-04.md"]


def test_the_lecture_row_never_carries_the_weeks_lab_links(monkeypatch, tmp_path):
    # Labs are their own entries; a lab file linked from the lecture row too would show
    # the lab twice (schedule + the theme's labs page).
    plan = _plan(
        monkeypatch,
        tmp_path,
        Schedule(),
        sources=[
            ("materials", "lectures", "02_week-2", 2),
            ("materials", "labs", "02_week-2", 2),
        ],
        files=lambda org, repo, subpath, folder: [
            (f"{subpath}.pdf", f"https://x/{subpath}")
        ],
    )
    session = plan.collections["_lectures"]["session-02.md"]
    assert 'name: "lecture - lectures.pdf"' in session
    assert "lab - " not in session
    assert 'name: "lab - labs.pdf"' in plan.collections["_lectures"]["lab-02.md"]


def test_events_render_as_their_declared_types(monkeypatch, tmp_path):
    plan = _plan(
        monkeypatch,
        tmp_path,
        Schedule(
            events=[
                Event("mid-term", "MidTerm Exam", date(2026, 11, 3), "exam"),
                Event("project-clinic", "Project clinic", date(2026, 11, 10)),
            ]
        ),
    )
    events = plan.collections["_events"]
    assert "type: exam" in events["01-mid-term.md"]
    assert "type: special_event" in events["02-project-clinic.md"]
    # a schedule that names its own exams gets no synthesised stubs
    assert "midterm.md" not in events and "final.md" not in events


def test_synthesised_exams_appear_when_the_schedule_names_none(monkeypatch, tmp_path):
    plan = _plan(
        monkeypatch,
        tmp_path,
        Schedule(
            events=[Event("project-clinic", "Project clinic", date(2026, 11, 10))]
        ),
    )
    events = plan.collections["_events"]
    assert 'description: "MidTerm Exam"' in events["midterm.md"]
    assert 'description: "Final Exam"' in events["final.md"]
    assert "type: special_event" in events["01-project-clinic.md"]


def test_term_date_rows_only_when_the_schedule_pins_the_bounds(monkeypatch, tmp_path):
    plan = _plan(
        monkeypatch,
        tmp_path,
        Schedule(semester_start=date(2026, 9, 7), semester_end=date(2026, 12, 18)),
    )
    events = plan.collections["_events"]
    assert 'name: "Term starts"' in events["term-start.md"]
    assert "date: 2026-09-07T09:00:00" in events["term-start.md"]
    assert 'name: "Term ends"' in events["term-end.md"]
    assert "date: 2026-12-18T09:00:00" in events["term-end.md"]

    unbounded = _plan(monkeypatch, tmp_path, Schedule())
    assert "term-start.md" not in unbounded.collections["_events"]
    assert "term-end.md" not in unbounded.collections["_events"]


# -------------------------------------------------------- dest_repo mismatch (fix 4)


def test_assignment_entry_names_the_cohort_dest_repo_not_the_course_repo(monkeypatch):
    # assign.py provisions `<cohort_dest_repo or slug>-<handle>`; the site must name the
    # same repo (and title the page from it), not the course repo minus its tag.
    monkeypatch.setattr(site, "get_file_content", lambda *a, **k: "")
    sched = Schedule(
        assignments={
            "assignment-1": AssignmentEntry(
                course_source_repo="assignment-1-f2026",
                due_datetime=datetime(2026, 10, 13, 23, 59, 59, tzinfo=BERLIN),
                cohort_dest_repo="homework-1",
            )
        }
    )
    out = site._assignment_entry(
        "Course", "assignment-1-f2026", date(2026, 10, 13), sched=sched
    )
    assert "`homework-1-<your-handle>`" in out
    assert 'title: "Homework 1"' in out


# ---------------------------------------------- fail-loud reads (fixes 5 and 6)


def test_session_files_missing_tree_is_empty(monkeypatch):
    monkeypatch.setattr(site, "get_default_branch", lambda org, repo: "main")
    monkeypatch.setattr(site, "gh", lambda *a, **k: (1, "HTTP 404: Not Found"))
    assert site._session_files("Cohort-f2026", "materials", "lectures", "03_x") == []


def test_session_files_fetch_failure_raises_rather_than_stripping_the_site(monkeypatch):
    # A swallowed failure returned (), the site republished with every material link gone.
    monkeypatch.setattr(site, "get_default_branch", lambda org, repo: "main")
    monkeypatch.setattr(site, "gh", lambda *a, **k: (1, "HTTP 502: bad gateway"))
    with pytest.raises(RuntimeError):
        site._session_files("Cohort-f2026", "materials", "lectures", "03_x")


def test_team_people_missing_team_is_empty(monkeypatch):
    monkeypatch.setattr(site, "gh", lambda *a, **k: (1, "HTTP 404: Not Found"))
    assert site._team_people("Course", "instructors") == []


def test_team_people_read_failure_raises_rather_than_wiping_the_team(monkeypatch):
    monkeypatch.setattr(site, "gh", lambda *a, **k: (1, "HTTP 500: boom"))
    with pytest.raises(RuntimeError):
        site._team_people("Course", "instructors")


# --------------------------------------------- front-matter escaping (fix 7)


def test_front_matter_survives_a_backslash_in_a_title(monkeypatch):
    # `# \sigma review` is an invalid YAML escape unquoted - the whole site build fails
    # (ScannerError) unless every scalar is routed through _q.
    monkeypatch.setattr(
        site, "get_file_content", lambda *a, **k: "# \\sigma review\nBody"
    )
    out = site._assignment_entry("Course", "assignment-1-f2026", date(2026, 11, 10))
    front = yaml.safe_load(out.split("---")[1])  # must parse, no ScannerError
    assert "sigma" in front["title"]


def test_links_block_survives_a_backslash_in_a_filename():
    block = site._links_block([("lectures", [("notes \\x.pdf", "https://x/1")])])
    parsed = yaml.safe_load(block)  # must parse, no ScannerError
    assert "notes" in parsed["links"][0]["name"]


def test_assignment_readme_body_is_fenced_as_liquid_raw(monkeypatch):
    # A `{% ... %}`/`{{ ... }}` in a README would run as Liquid and a malformed tag fails
    # the build; the inlined body is fenced.
    monkeypatch.setattr(
        site, "get_file_content", lambda *a, **k: "# A1\nUse {{ x }} in your code"
    )
    out = site._assignment_entry("Course", "assignment-1-f2026", date(2026, 11, 10))
    assert "{% raw %}" in out and "{% endraw %}" in out


# --------------------------------------------- tz-aware display (fix 8)


def test_iso_when_converts_an_explicit_offset_to_the_cohort_tz():
    # 10:00 UTC in a Berlin cohort (CEST, +2 in September) displays as 12:00 - the time it
    # actually fires - not the written offset's 10:00.
    when = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)
    assert site._iso_when(when, tz=BERLIN) == "2026-09-15T12:00:00"
    assert (
        site._iso_when(when) == "2026-09-15T10:00:00"
    )  # no tz -> own clock (unchanged)


def test_event_entry_shows_the_cohort_wall_clock_time_for_a_written_offset():
    e = Event("remote", "Remote talk", datetime(2026, 9, 15, 10, 0, tzinfo=UTC))
    out = site._event_entry(e, END_OF_TERM, BERLIN)
    assert "date: 2026-09-15T12:00:00" in out


def test_display_only_rows_come_from_events_alone(monkeypatch, tmp_path):
    # `releases:` is the deploy plan; a row with nothing to release belongs in `events:`,
    # and an action-less release entry is NOT a second way to write one.
    plan = _plan(
        monkeypatch,
        tmp_path,
        Schedule(
            releases=[
                Release("guest-lecture", datetime(2026, 11, 17, 10, 0, tzinfo=BERLIN))
            ]
        ),
    )
    assert "Guest Lecture" not in "".join(plan.collections["_events"].values())
