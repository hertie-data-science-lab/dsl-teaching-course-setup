"""Pure content transforms in site.py - the logic with real edge cases.

The headline invariant: a PUBLIC course-site entry must never link into a private repo
(github.com / raw.githubusercontent), only site-relative paths. reading-list mode must
publish citations as text without leaking copyrighted bytes.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from dsl_course import site


def test_semester_label():
    assert site._semester_label("Deep-Learning-f2026") == "Fall 2026"
    assert site._semester_label("Intro-s2025") == "Spring 2025"
    assert site._semester_label("no-tag-here") == ""


def test_slug():
    assert site._slug("MidTerm Exam") == "midterm-exam"
    assert site._slug("") == "exam"


_PEOPLE_META = {
    "people": {
        "instructors": [{"name": "Prof. Jane", "photo": "j.jpg", "url": "u/jane"}],
        "teaching_assistants": [{"name": "Alex TA", "photo": "a.jpg", "url": "u/alex"}],
    }
}


def test_people_yaml_cohort_includes_tas():
    # The cohort site reads its own people.yml and renders instructors AND TAs.
    out = site._people_yaml("Some-Cohort-f2026", _PEOPLE_META)
    assert "Prof. Jane" in out
    assert "Alex TA" in out


def test_people_yaml_course_site_drops_tas():
    # The multi-year open-courseware site shows instructors only - TAs are cohort-only.
    out = site._people_yaml("Some-Course", _PEOPLE_META, include_tas=False)
    assert "Prof. Jane" in out
    assert "Alex TA" not in out
    assert "teaching_assistants:" in out  # the (now empty) key is still emitted


def test_set_config_replaces_only_the_named_key():
    cfg = 'course_name: "old"\ncourse_code: "X"\n'
    out = site._set_config(cfg, "course_name", "Deep Learning")
    assert 'course_name: "Deep Learning"' in out
    assert 'course_code: "X"' in out  # untouched


def test_reading_list_md_inlines_text_lists_binaries_by_name(tmp_path):
    wk = tmp_path / "session-1"
    wk.mkdir()
    (wk / "reading.md").write_text("# Session 1\n- Smith 2020, ch.1")
    (wk / "paper.pdf").write_bytes(b"%PDF-1.4 copyrighted bytes")
    md = site._reading_list_md(wk)
    assert "Smith 2020" in md  # citation text is published
    assert "- paper.pdf" in md  # the PDF is named...
    assert "%PDF" not in md  # ...but its bytes are NOT


def test_public_links_are_site_relative(tmp_path):
    wk = tmp_path / "lectures"
    wk.mkdir()
    (wk / "01 intro.pdf").write_bytes(b"x")
    links = site._public_links(
        wk, "/public-materials/course-materials-f2026/session-1/lectures"
    )
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


def test_lecture_entry_labels_links_by_repo_or_subpath():
    def fake_session_files(org, repo, subpath, folder):
        return {
            ("labs", ""): [("intro.pdf", "https://x/1")],  # root shape: label = repo
            ("materials", "lectures"): [("slides.pdf", "https://x/2")],  # nested: label = subpath
        }.get((repo, subpath), [])

    with patch.object(site, "_session_files", side_effect=fake_session_files):
        entry = site._lecture_entry(
            "Cohort-f2026",
            "1",
            date(2026, 9, 7),
            [("labs", "", "01_intro"), ("materials", "lectures", "01_intro")],
        )
    assert "https://x/1" in entry and "https://x/2" in entry
    assert 'name: "lab - intro.pdf"' in entry
    assert 'name: "lecture - slides.pdf"' in entry
    assert 'name: "lecture - slides.pdf"' in entry


def test_public_lecture_entry_actual_readings_mode_links_are_local():
    lec = [("s.pdf", "/public-materials/m/session-1/lectures/s.pdf")]
    rds = [("r.pdf", "/public-materials/m/session-1/readings/r.pdf")]
    e = site._public_lecture_entry("1", date(2025, 1, 1), lec, rds, "")
    assert "lecture - s.pdf" in e and "reading - r.pdf" in e
    assert "github.com" not in e and "raw." not in e
