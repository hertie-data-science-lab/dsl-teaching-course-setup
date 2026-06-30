"""release._week_dir tolerates the padding variants faculty actually create."""

from __future__ import annotations

from dsl_course import release


def test_week_dir_matches_padding_variants(tmp_path):
    section = tmp_path / "lectures"
    section.mkdir()
    (section / "week-01").mkdir()  # zero-padded on disk
    # discover reports unpadded "1"; _week_dir must still find week-01
    assert release._week_dir(section, "1") == section / "week-01"


def test_week_dir_plain_and_dashless(tmp_path):
    section = tmp_path / "readings"
    section.mkdir()
    (section / "week3").mkdir()  # no dash
    assert release._week_dir(section, "3") == section / "week3"


def test_week_dir_missing_returns_none(tmp_path):
    section = tmp_path / "lectures"
    section.mkdir()
    assert release._week_dir(section, "9") is None


def test_week_dir_no_section_returns_none(tmp_path):
    assert release._week_dir(tmp_path / "does-not-exist", "1") is None


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
