"""release._syllabus_files matches root syllabus files case/extension-agnostically.

(Session-directory discovery/matching moved to utils.py - see test_utils.py - since
release.py no longer hardcodes section names.)"""

from __future__ import annotations

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
