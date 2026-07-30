"""Pure content transforms in site.py - the logic with real edge cases.

The headline invariant: a PUBLIC course-site entry must never link into a private repo
(github.com / raw.githubusercontent), only site-relative paths. reading-list mode must
publish citations as text without leaking copyrighted bytes.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from dsl_course import site


def test_semester_label():
    assert site._semester_label("Deep-Learning-f2026") == "Fall 2026"
    assert site._semester_label("Intro-s2025") == "Spring 2025"
    assert site._semester_label("no-tag-here") == ""


def test_slug():
    assert site._slug("MidTerm Exam") == "midterm-exam"
    assert site._slug("") == "exam"


def test_exam_entry_date_only_keeps_the_nine_am_placeholder():
    # Unchanged rendering for every schedule that gives a bare `date:` (and for the
    # synthesised mid/end-of-semester fallback rows).
    out = site._exam_entry("MidTerm Exam", date(2026, 11, 3))
    assert "date: 2026-11-03T09:00:00" in out
    assert 'description: "MidTerm Exam"' in out
    assert "type: exam" in out


def test_exam_entry_renders_the_real_time_when_one_was_given():
    out = site._exam_entry(
        "Final Exam", datetime(2026, 12, 15, 14, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    )
    assert "date: 2026-12-15T14:00:00" in out
    assert "09:00" not in out
    assert "+01:00" not in out  # offset-free, like the assignment due rows


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
    e = site._public_lecture_entry("1", date(2025, 1, 1), [], "- Smith 2020")
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
    e = site._public_lecture_entry(
        "1", date(2025, 1, 1), [("lectures", lec), ("readings", rds)], ""
    )
    assert "lecture - s.pdf" in e and "reading - r.pdf" in e
    assert "github.com" not in e and "raw." not in e


def test_public_lecture_entry_labels_any_discovered_section():
    # Sections are free-form directory names - a repo with labs/ and faq/ must get
    # labelled links, not silently nothing (the site used to look only at lectures/).
    e = site._public_lecture_entry(
        "3",
        date(2025, 1, 1),
        [
            ("labs", [("lab3.ipynb", "/public-materials/m/session-3/labs/lab3.ipynb")]),
            ("faq", [("faq.md", "/public-materials/m/session-3/faq/faq.md")]),
        ],
        "",
    )
    assert 'name: "lab - lab3.ipynb"' in e
    assert 'name: "faq - faq.md"' in e  # not "fa - faq.md"


def test_singular_strips_only_a_real_trailing_s():
    assert site._singular("lectures") == "lecture"
    assert site._singular("labs") == "lab"
    assert site._singular("faq") == "faq"  # was "fa"
    assert site._singular("s") == "s"  # never empty


_TREE = "\n".join(
    [
        "README.md",
        "lectures/03_week-3/notes.pdf",
        "lectures/03_week-3/handouts/extra notes.pdf",
        "lectures/03_week-3/handouts/deep/further.md",
        "lectures/03_week-30/decoy.pdf",  # prefix-sharing sibling, must not leak in
        "lectures/04_week-4/other.pdf",
        "01_intro/root-shape.pdf",
    ]
)


def _tree_gh(*args, **kwargs):
    """Fake `gh api .../git/trees/<branch>?recursive=1` - the repo's blob paths."""
    return (0, _TREE)


def test_session_files_lists_nested_files_by_path(monkeypatch):
    # release.py copytrees a session folder wholesale, so nested files ARE released -
    # a non-recursive listing dropped them from the site entirely.
    monkeypatch.setattr(site, "get_default_branch", lambda org, repo: "main")
    monkeypatch.setattr(site, "gh", _tree_gh)
    pairs = site._session_files("Cohort-f2026", "materials", "lectures", "03_week-3")
    assert [n for n, _ in pairs] == [
        "handouts/deep/further.md",  # sorted by path, so nested first
        "handouts/extra notes.pdf",
        "notes.pdf",
    ]
    urls = dict(pairs)
    assert (
        urls["notes.pdf"]
        == "https://github.com/Cohort-f2026/materials/blob/main/lectures/03_week-3/notes.pdf"
    )
    assert "extra%20notes.pdf" in urls["handouts/extra notes.pdf"]  # spaces encoded


def test_session_files_root_shape_and_other_sessions_excluded(monkeypatch):
    monkeypatch.setattr(site, "get_default_branch", lambda org, repo: "main")
    monkeypatch.setattr(site, "gh", _tree_gh)
    # subpath="" - the release landed at the repo root (default destination)
    assert site._session_files("Cohort-f2026", "lectures", "", "01_intro") == [
        (
            "root-shape.pdf",
            "https://github.com/Cohort-f2026/lectures/blob/main/01_intro/root-shape.pdf",
        )
    ]


def test_repo_tree_is_fetched_once_per_repo(monkeypatch):
    # A cohort site asks for the files of every released session, nearly always from the
    # same repo - one tree fetch must serve them all, not one fetch per session.
    calls = []

    def counting_gh(*args, **kwargs):
        calls.append(args)
        return (0, _TREE)

    monkeypatch.setattr(site, "get_default_branch", lambda org, repo: "main")
    monkeypatch.setattr(site, "gh", counting_gh)
    for folder in ("03_week-3", "04_week-4", "03_week-30"):
        assert site._session_files("Cohort-f2026", "materials", "lectures", folder)
    assert len(calls) == 1


def test_session_files_api_failure_is_empty(monkeypatch):
    monkeypatch.setattr(site, "get_default_branch", lambda org, repo: "main")
    monkeypatch.setattr(site, "gh", lambda *a, **k: (1, "not found"))
    assert site._session_files("Cohort-f2026", "materials", "lectures", "03_x") == []
