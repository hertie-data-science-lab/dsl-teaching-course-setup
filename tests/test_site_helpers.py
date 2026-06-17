"""Pure content transforms in site.py - the logic with real edge cases.

The headline invariant: a PUBLIC course-site entry must never link into a private repo
(github.com / raw.githubusercontent), only site-relative paths. reading-list mode must
publish citations as text without leaking copyrighted bytes.
"""

from __future__ import annotations

from datetime import date, datetime

from dsl_course import site


def test_coerce_date_accepts_date_datetime_iso_and_rejects_junk():
    assert site._coerce_date(date(2026, 9, 7)) == date(2026, 9, 7)
    assert site._coerce_date(datetime(2026, 9, 7, 12, 0)) == date(2026, 9, 7)
    assert site._coerce_date("2026-09-07") == date(2026, 9, 7)
    assert site._coerce_date("not-a-date") is None
    assert site._coerce_date(12345) is None


def test_semester_label():
    assert site._semester_label("Deep-Learning-f2026") == "Fall 2026"
    assert site._semester_label("Intro-s2025") == "Spring 2025"
    assert site._semester_label("no-tag-here") == ""


def test_slug():
    assert site._slug("MidTerm Exam") == "midterm-exam"
    assert site._slug("") == "exam"


def test_set_config_replaces_only_the_named_key():
    cfg = 'course_name: "old"\ncourse_code: "X"\n'
    out = site._set_config(cfg, "course_name", "Deep Learning")
    assert 'course_name: "Deep Learning"' in out
    assert 'course_code: "X"' in out  # untouched


def test_schedule_parses_overrides():
    meta = {
        "schedule": {
            "semester_start": "2026-09-07",
            "assignments": {"assignment-1": "2026-10-13"},
            "exams": [{"name": "Final", "date": "2026-12-15"}],
        }
    }
    start, due, exams = site._schedule(meta)
    assert start == date(2026, 9, 7)
    assert due == {"assignment-1": date(2026, 10, 13)}
    assert exams == [("Final", date(2026, 12, 15))]


def test_schedule_empty_is_safe():
    assert site._schedule({}) == (None, {}, [])


def test_reading_list_md_inlines_text_lists_binaries_by_name(tmp_path):
    wk = tmp_path / "week-1"
    wk.mkdir()
    (wk / "reading.md").write_text("# Week 1\n- Smith 2020, ch.1")
    (wk / "paper.pdf").write_bytes(b"%PDF-1.4 copyrighted bytes")
    md = site._reading_list_md(wk)
    assert "Smith 2020" in md          # citation text is published
    assert "- paper.pdf" in md         # the PDF is named...
    assert "%PDF" not in md            # ...but its bytes are NOT


def test_public_links_are_site_relative(tmp_path):
    wk = tmp_path / "lectures"
    wk.mkdir()
    (wk / "01 intro.pdf").write_bytes(b"x")
    links = site._public_links(wk, "/public-materials/course-materials-f2026/week-1/lectures")
    assert len(links) == 1
    name, url = links[0]
    assert name == "01 intro.pdf"
    assert url.startswith("/public-materials/")
    assert "%20" in url or "01%20intro" in url  # space URL-encoded
    assert "github.com" not in url and "raw." not in url


def test_public_lecture_entry_reading_list_mode_has_no_links():
    e = site._public_lecture_entry("1", date(2025, 1, 1), [], [], "- Smith 2020")
    assert "links: []" in e
    assert "### Reading list" in e and "Smith 2020" in e
    assert "enrolled" not in e  # public-facing, no student gate language


def test_public_lecture_entry_actual_readings_mode_links_are_local():
    lec = [("s.pdf", "/public-materials/m/week-1/lectures/s.pdf")]
    rds = [("r.pdf", "/public-materials/m/week-1/readings/r.pdf")]
    e = site._public_lecture_entry("1", date(2025, 1, 1), lec, rds, "")
    assert "lecture - s.pdf" in e and "reading - r.pdf" in e
    assert "github.com" not in e and "raw." not in e
