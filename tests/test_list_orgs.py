"""The inventory CLI is a pure reader: its failure modes are the discovery search and the
per-org metadata read. Both have to reach the Actions log as a line, not a traceback, and
neither may be written out as an inventory of zero (or mis-tiered) orgs.
"""

from __future__ import annotations

import pytest

from dsl_course import list_orgs


def test_main_reports_a_failed_search_and_exits_nonzero(monkeypatch, capsys):
    def boom() -> list[dict]:
        raise RuntimeError("`gh search repos topic:dsl-course-hub` failed: HTTP 403")

    monkeypatch.setattr(list_orgs, "discover_course_orgs", boom)
    monkeypatch.setattr("sys.argv", ["list_orgs"])

    assert list_orgs.main() == 1
    assert "HTTP 403" in capsys.readouterr().err


def test_main_writes_the_inventory_when_discovery_succeeds(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        list_orgs,
        "discover_course_orgs",
        lambda: [
            {
                "org": "My-Course",
                "org_name": "My Course",
                "course_name": "Deep Learning",
                "course_code": "E1",
                "url": "https://github.com/My-Course",
            }
        ],
    )
    monkeypatch.setattr(list_orgs, "discover_cohort_orgs", list)
    page = tmp_path / "inventory.md"
    monkeypatch.setattr("sys.argv", ["list_orgs", "--update-file", str(page)])

    assert list_orgs.main() == 0
    assert "My-Course" in page.read_text()
    assert "1 course orgs" in capsys.readouterr().out


def test_metadata_is_empty_only_for_an_org_that_carries_none(monkeypatch):
    # The tier split reads this file (a `course:` pointer means COHORT), so {} from a
    # transient failure used to list a cohort org under Course orgs. Only a 404 is {}.
    monkeypatch.setattr(
        list_orgs, "gh", lambda *a, **k: (1, "gh: Not Found (HTTP 404)")
    )
    assert list_orgs._fetch_metadata("Cohort-f2026") == {}
    monkeypatch.setattr(
        list_orgs, "gh", lambda *a, **k: (1, "gh: HTTP 403 - forbidden")
    )
    with pytest.raises(RuntimeError, match="Cohort-f2026/.github/dsl-course.yml"):
        list_orgs._fetch_metadata("Cohort-f2026")


def test_a_full_search_page_is_read_as_truncation(monkeypatch):
    # `gh search repos --limit N` returns one page. A result set that exactly fills it is
    # indistinguishable from a truncated one, and this page is fully generated and merged
    # unattended - so every org past the limit would be silently deleted from the
    # inventory. Fail the run instead.
    monkeypatch.setattr(
        list_orgs,
        "gh_json",
        lambda *a: [
            {"name": ".github", "owner": {"login": f"Org-{i}"}}
            for i in range(list_orgs.SEARCH_LIMIT)
        ],
    )
    with pytest.raises(RuntimeError, match="truncated"):
        list_orgs._tagged_orgs(list_orgs.COURSE_HUB_TOPIC)


def test_a_partial_search_page_is_read_normally(monkeypatch):
    monkeypatch.setattr(
        list_orgs,
        "gh_json",
        lambda *a: [
            {"name": ".github", "owner": {"login": "Org-A"}},
            {"name": "course-materials", "owner": {"login": "Org-B"}},  # not a .github
        ],
    )
    assert list_orgs._tagged_orgs(list_orgs.COURSE_HUB_TOPIC) == ["Org-A"]


def test_metadata_parses_the_yaml_body(monkeypatch):
    monkeypatch.setattr(list_orgs, "gh", lambda *a, **k: (0, "course: My-Course\n"))
    assert list_orgs._fetch_metadata("Cohort-f2026") == {"course": "My-Course"}


def test_a_failed_metadata_read_stops_the_inventory_being_rewritten(
    monkeypatch, tmp_path, capsys
):
    # The page is fully generated and overwrites whatever is there: a wrong refresh is
    # worse than no refresh, so the CLI must exit 1 with the file untouched.
    monkeypatch.setattr(list_orgs, "_tagged_orgs", lambda topic: ["Cohort-f2026"])
    monkeypatch.setattr(list_orgs, "gh", lambda *a, **k: (1, "gh: HTTP 502"))
    page = tmp_path / "inventory.md"
    page.write_text("# the previous, good inventory\n")
    monkeypatch.setattr("sys.argv", ["list_orgs", "--update-file", str(page)])

    assert list_orgs.main() == 1
    assert page.read_text() == "# the previous, good inventory\n"
    assert "HTTP 502" in capsys.readouterr().err
