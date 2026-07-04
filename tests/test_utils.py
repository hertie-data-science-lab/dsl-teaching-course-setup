"""Session directory helpers: sections/sessions are discovered from the directory
structure itself (any dir with an ordinal-prefixed subdir is a section) - no declared
config, so these pure functions are the whole contract."""

from __future__ import annotations

from dsl_course import utils


def test_session_number_extracts_ordinal_prefix():
    assert utils.session_number("00_intro") == 0
    assert utils.session_number("07_finals-review") == 7
    assert utils.session_number("13_other") == 13
    assert utils.session_number("3_regression") == 3
    assert utils.session_number("no-prefix-here") is None


def test_find_session_dir_plain_and_padded(tmp_path):
    section = tmp_path / "lectures"
    section.mkdir()
    (section / "00_intro").mkdir()
    (section / "03_regression").mkdir()  # zero-padded
    (section / "13_other").mkdir()  # must not match session "3"
    assert utils.find_session_dir(section, "3").name == "03_regression"
    assert utils.find_session_dir(section, "13").name == "13_other"
    assert utils.find_session_dir(section, "9") is None


def test_find_session_dir_missing_section_returns_none(tmp_path):
    assert utils.find_session_dir(tmp_path / "does-not-exist", "1") is None


def test_discover_sections_only_counts_dirs_with_ordinal_subdirs(tmp_path):
    (tmp_path / "lectures" / "00_intro").mkdir(parents=True)
    (tmp_path / "labs" / "03_regression").mkdir(parents=True)
    (tmp_path / "readings").mkdir()  # no ordinal subdirs -> not a section
    (tmp_path / "SYLLABUS.md").write_text("x")  # a file, not a dir
    assert utils.discover_sections(tmp_path) == ["labs", "lectures"]


def test_discover_sections_missing_root_returns_empty(tmp_path):
    assert utils.discover_sections(tmp_path / "nope") == []


def test_expand_int_spec_handles_lists_ranges_and_mixes():
    assert utils.expand_int_spec("1,2,3") == [1, 2, 3]
    assert utils.expand_int_spec("1-3") == [1, 2, 3]
    assert utils.expand_int_spec("1,3,5-7") == [1, 3, 5, 6, 7]
    assert utils.expand_int_spec(" 1 , 3   5-7 ") == [1, 3, 5, 6, 7]  # loose whitespace
    assert utils.expand_int_spec("5-5") == [5]  # single-element range
    assert utils.expand_int_spec("3,1,2") == [1, 2, 3]  # de-duplicated + sorted


def test_expand_int_spec_rejects_malformed_input():
    import pytest

    with pytest.raises(ValueError, match="empty"):
        utils.expand_int_spec("   ")
    with pytest.raises(ValueError, match="abc"):
        utils.expand_int_spec("1,abc,3")
    with pytest.raises(ValueError, match="backwards"):
        utils.expand_int_spec("5-2")


def test_reconcile_team_members_adds_missing_and_removes_extra(monkeypatch):
    monkeypatch.setattr(utils, "get_team_members", lambda org, team: {"alice", "bob"})
    monkeypatch.setattr(utils, "_acting_login", lambda: None)
    monkeypatch.setattr(utils, "get_org_owners", lambda org: frozenset())
    added, removed = [], []
    monkeypatch.setattr(
        utils, "add_team_member", lambda org, team, h, role="member": added.append(h) or True
    )
    monkeypatch.setattr(
        utils, "remove_team_member", lambda org, team, h: removed.append(h) or True
    )
    errors = utils.reconcile_team_members("org", "instructors", {"alice", "carol"})
    assert errors == 0
    assert added == ["carol"]
    assert removed == ["bob"]


def test_reconcile_team_members_never_prunes_the_acting_login(monkeypatch):
    monkeypatch.setattr(utils, "get_team_members", lambda org, team: {"alice", "hertie-dsl-bot"})
    monkeypatch.setattr(utils, "_acting_login", lambda: "hertie-dsl-bot")
    monkeypatch.setattr(utils, "get_org_owners", lambda org: frozenset())
    removed = []
    monkeypatch.setattr(utils, "add_team_member", lambda *a, **k: True)
    monkeypatch.setattr(
        utils, "remove_team_member", lambda org, team, h: removed.append(h) or True
    )
    errors = utils.reconcile_team_members("org", "course-admin", wanted=set())
    assert errors == 0
    assert removed == ["alice"]


def test_reconcile_team_members_never_prunes_any_org_owner(monkeypatch):
    # The robust fix: exclude ALL owners, not just whoever's currently running the
    # sync - so a human running this locally doesn't evict the bot (or vice versa).
    monkeypatch.setattr(
        utils, "get_team_members", lambda org, team: {"alice", "hertie-dsl-bot", "henrycgbaker"}
    )
    monkeypatch.setattr(utils, "_acting_login", lambda: "henrycgbaker")  # a human, running locally
    monkeypatch.setattr(
        utils, "get_org_owners", lambda org: frozenset({"hertie-dsl-bot", "henrycgbaker"})
    )
    removed = []
    monkeypatch.setattr(utils, "add_team_member", lambda *a, **k: True)
    monkeypatch.setattr(
        utils, "remove_team_member", lambda org, team, h: removed.append(h) or True
    )
    errors = utils.reconcile_team_members("org", "course-admin", wanted=set())
    assert errors == 0
    assert removed == ["alice"]  # neither owner touched, despite neither being declared
