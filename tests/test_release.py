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
