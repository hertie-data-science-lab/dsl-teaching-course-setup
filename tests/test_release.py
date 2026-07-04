"""release._syllabus_files matches root syllabus files case/extension-agnostically,
and parse_destinations parses the "section=repo[/subpath]" routing spec.

(Session-directory discovery/matching moved to utils.py - see test_utils.py - since
release.py no longer hardcodes section names.)"""

from __future__ import annotations

import pytest

from dsl_course import release


def test_syllabus_files_is_caps_agnostic(tmp_path):
    # the scaffold ships an all-caps SYLLABUS.md that the old `*[Ss]yllabus*` glob
    # missed; faculty also use mixed/lower case and varied extensions. Distinct paths
    # (not case-only variants) so this holds on case-insensitive filesystems too.
    for name in ("SYLLABUS.md", "Course-Syllabus.pdf", "weekly_syllabus.txt"):
        (tmp_path / name).write_text("x")
    (tmp_path / "README.md").write_text("x")  # not a syllabus -> excluded
    found = [f.name for f in release._syllabus_files(tmp_path)]
    assert found == ["Course-Syllabus.pdf", "SYLLABUS.md", "weekly_syllabus.txt"]


def test_syllabus_files_ignores_non_syllabus_and_dirs(tmp_path):
    (tmp_path / "README.md").write_text("x")
    (tmp_path / "lectures").mkdir()  # a dir, not a file
    (tmp_path / "syllabus_archive").mkdir()  # dir whose name contains 'syllabus'
    assert release._syllabus_files(tmp_path) == []


def test_syllabus_files_missing_dir_returns_empty(tmp_path):
    assert release._syllabus_files(tmp_path / "nope") == []


def test_parse_destinations_maps_sections_to_repo_or_repo_subpath():
    assert release.parse_destinations("lectures=lectures,labs=materials/labs") == {
        "lectures": "lectures",
        "labs": "materials/labs",
    }


def test_parse_destinations_rejects_malformed_pairs():
    with pytest.raises(ValueError, match="section=destination"):
        release.parse_destinations("lectures")  # no '='
    with pytest.raises(ValueError, match="section=destination"):
        release.parse_destinations("=lectures")  # missing section
    with pytest.raises(ValueError, match="section=destination"):
        release.parse_destinations("lectures=")  # missing destination


def test_route_sections_explicit_destination_wins_with_optional_subpath():
    by_repo = release.route_sections(
        ["lectures", "labs"],
        destinations={"lectures": "lectures", "labs": "materials/labs"},
        default_repo=None,
        exclude=set(),
    )
    assert by_repo == {
        "lectures": [("lectures", "")],  # no subpath -> repo root
        "materials": [("labs", "labs")],
    }


def test_route_sections_two_sections_can_share_one_repo():
    by_repo = release.route_sections(
        ["lectures", "labs"],
        destinations={"lectures": "materials/lectures", "labs": "materials/labs"},
        default_repo=None,
        exclude=set(),
    )
    assert by_repo == {
        "materials": [("lectures", "lectures"), ("labs", "labs")],
    }


def test_route_sections_falls_back_to_default_repo_nested_by_section_name():
    by_repo = release.route_sections(
        ["lectures", "readings"],
        destinations={},
        default_repo="materials",
        exclude=set(),
    )
    assert by_repo == {
        "materials": [("lectures", "lectures"), ("readings", "readings")],
    }


def test_route_sections_excluded_and_unrouted_sections_are_dropped():
    by_repo = release.route_sections(
        ["lectures", "readings", "labs"],
        destinations={"lectures": "lectures"},
        default_repo="materials",
        exclude={"readings"},
    )
    # readings: excluded from the default-repo fallback -> dropped.
    # labs: no explicit destination, not excluded -> falls back to default_repo.
    assert by_repo == {
        "lectures": [("lectures", "")],
        "materials": [("labs", "labs")],
    }


def test_route_sections_no_destinations_and_no_default_repo_routes_nothing():
    assert release.route_sections(["lectures"], {}, None, set()) == {}
