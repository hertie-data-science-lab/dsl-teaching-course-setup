"""site.sync_public_site over a real (temp-filesystem) source repo.

The public open-courseware site must publish whatever sections the materials repo
actually HAS - `discover_sessions` is generic across every top-level section, so a course
whose content lives in `labs/` used to get empty, useless session pages. Only the gh/git
calls are faked (clone = populate a directory, commit/push = success); the copying, the
served layout and the generated `_lectures/` entries are the real code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dsl_course import seed, site

COURSE = "Course-Org"
SOURCE = "course-materials-f2026"
SERVED = f"public-materials/{SOURCE}"


def _seed_source(root: Path) -> None:
    """A materials repo with NO `lectures/` at all: labs + readings + a faq section,
    plus a session (3) that has no content in any section."""
    files = {
        "labs/01_first-lab/lab.ipynb": "notebook",
        "labs/01_first-lab/data/rows.csv": "a,b",  # nested - must still be published
        "labs/02_second-lab/lab.ipynb": "notebook",
        "faq/02_second-lab/faq.md": "Q: why? A: because.",
        "readings/01_first-lab/list.md": "- Smith 2020, ch.1",
        "readings/01_first-lab/paper.pdf": "%PDF-1.4 copyrighted",
        "README.md": "# materials",  # not a section
    }
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)


@pytest.fixture
def published(monkeypatch):
    """Run sync_public_site and return {path: content} of the site repo as committed."""
    committed: dict[str, str] = {}

    def fake_gh(*args, **kwargs):
        if args[:2] == ("repo", "clone"):
            spec, dest = args[2], Path(args[3])
            dest.mkdir(parents=True, exist_ok=True)
            if spec == f"{COURSE}/{SOURCE}":
                _seed_source(dest)
            else:  # the site repo, as the template leaves it
                (dest / "_config.yml").write_text(
                    'course_name: "x"\ncourse_code: "y"\ncourse_semester: "z"\n'
                )
            return (0, "")
        return (0, "")

    def fake_git(*args):
        if "add" in args:
            wd = Path(args[1])
            committed.clear()
            committed.update(
                {
                    p.relative_to(wd).as_posix(): p.read_text(errors="replace")
                    for p in wd.rglob("*")
                    if p.is_file()
                }
            )
        return (0, "")

    monkeypatch.setattr(site, "gh", fake_gh)
    monkeypatch.setattr(site, "git", fake_git)
    monkeypatch.setattr(site, "repo_exists", lambda org, name: True)
    monkeypatch.setattr(site, "get_file_content", lambda *a, **k: "")
    monkeypatch.setattr(seed, "discover_sessions", lambda org, repo: ["1", "2", "3"])

    def run(**kwargs) -> dict[str, str]:
        assert site.sync_public_site(COURSE, SOURCE, **kwargs) == 0
        return dict(committed)

    return run


def test_publishes_every_discovered_section_not_just_lectures(published):
    files = published(readings_mode="none")
    # labs/ and faq/ are hosted and linked, though neither is named "lectures"
    assert f"{SERVED}/session-1/labs/lab.ipynb" in files
    assert f"{SERVED}/session-1/labs/data/rows.csv" in files  # nested file too
    assert f"{SERVED}/session-2/faq/faq.md" in files
    s1 = files["_lectures/session-01.md"]
    assert 'name: "lab - lab.ipynb"' in s1
    assert 'name: "lab - data/rows.csv"' in s1
    assert 'name: "faq - faq.md"' in files["_lectures/session-02.md"]


def test_session_with_no_content_gets_no_page(published):
    files = published(readings_mode="none")
    assert "_lectures/session-01.md" in files
    assert "_lectures/session-02.md" in files
    assert "_lectures/session-03.md" not in files  # session 3 has nothing anywhere


def test_reading_list_mode_publishes_citations_as_text_only(published):
    files = published(readings_mode="reading-list")
    s1 = files["_lectures/session-01.md"]
    assert "### Reading list" in s1 and "Smith 2020" in s1
    assert "- paper.pdf" in s1  # named, not hosted
    assert not [p for p in files if "/readings/" in p]  # no reading bytes served


def test_actual_readings_mode_hosts_and_links_readings(published):
    files = published(readings_mode="actual-readings")
    assert f"{SERVED}/session-1/readings/paper.pdf" in files
    s1 = files["_lectures/session-01.md"]
    assert 'name: "reading - paper.pdf"' in s1
    assert "### Reading list" not in s1  # hosted instead of inlined
    assert "github.com" not in s1  # public links are always site-relative


def test_readings_only_when_file_sections_are_off(published):
    files = published(readings_mode="actual-readings", include_lectures=False)
    assert f"{SERVED}/session-1/readings/paper.pdf" in files
    assert not [p for p in files if "/labs/" in p or "/faq/" in p]
    # session 2 has labs + faq but no readings -> nothing to publish for it
    assert "_lectures/session-02.md" not in files


def test_nothing_to_publish_at_all_is_an_error():
    # No file sections and no readings - refuse before touching a single repo.
    assert site.sync_public_site(COURSE, SOURCE, "none", include_lectures=False) == 1
