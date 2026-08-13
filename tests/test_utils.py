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


def test_delete_file_treats_only_a_404_as_already_deleted(monkeypatch):
    # A missing file is a no-op success, but any OTHER failure to read its SHA (no
    # permission, rate limit, network) must not be reported as a successful delete -
    # otherwise a retired generated file silently survives in the org.
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (1, "gh: Not Found (HTTP 404)"))
    assert utils.delete_file("org", "repo", "x.yml", "retire x") is True
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (1, "gh: HTTP 403 - forbidden"))
    assert utils.delete_file("org", "repo", "x.yml", "retire x") is False


def test_delete_file_deletes_with_the_fetched_sha(monkeypatch):
    calls = []

    def fake_gh(*args, **kwargs):
        calls.append(args)
        return (0, "deadbeef") if len(calls) == 1 else (0, "")

    monkeypatch.setattr(utils, "gh", fake_gh)
    assert utils.delete_file("org", "repo", "x.yml", "retire x") is True
    assert "sha=deadbeef" in calls[1]


def _blob_sha(content: bytes) -> str:
    """What GitHub reports as a file's `.sha` - git's blob hash of its bytes."""
    import hashlib

    return hashlib.sha1(
        b"blob " + str(len(content)).encode() + b"\0" + content
    ).hexdigest()


def test_put_file_skips_the_write_when_the_content_is_identical(monkeypatch):
    # Refresh re-pushes every seeded file nightly, so an unchanged file must cost nothing:
    # the SHA already fetched for the update is git's blob sha, and comparing it locally
    # keeps a no-change night from filling every org's history with empty commits.
    content = b"name: onboard\n"
    calls = []

    def fake_gh(*args, **kwargs):
        calls.append(args)
        return (0, _blob_sha(content))

    monkeypatch.setattr(utils, "gh", fake_gh)
    assert utils.put_file("org", "repo", "x.yml", content, "ci: seed x") is True
    assert len(calls) == 1  # the SHA read only - no PUT


def test_put_file_writes_with_the_fetched_sha_when_the_content_differs(monkeypatch):
    calls = []

    def fake_gh(*args, **kwargs):
        calls.append(args)
        return (0, _blob_sha(b"something else")) if len(calls) == 1 else (0, "")

    monkeypatch.setattr(utils, "gh", fake_gh)
    assert utils.put_file("org", "repo", "x.yml", b"new\n", "ci: seed x") is True
    assert len(calls) == 2
    assert f"sha={_blob_sha(b'something else')}" in calls[1]


def test_reconcile_team_members_adds_missing_and_removes_extra(monkeypatch):
    monkeypatch.setattr(utils, "get_team_members", lambda org, team: {"alice", "bob"})
    monkeypatch.setattr(utils, "_acting_login", lambda: None)
    monkeypatch.setattr(utils, "get_org_owners", lambda org: frozenset())
    added, removed = [], []
    monkeypatch.setattr(
        utils,
        "add_team_member",
        lambda org, team, h, role="member": added.append(h) or True,
    )
    monkeypatch.setattr(
        utils, "remove_team_member", lambda org, team, h: removed.append(h) or True
    )
    errors = utils.reconcile_team_members("org", "instructors", {"alice", "carol"})
    assert errors == 0
    assert added == ["carol"]
    assert removed == ["bob"]


def test_reconcile_team_members_never_prunes_the_acting_login(monkeypatch):
    monkeypatch.setattr(
        utils, "get_team_members", lambda org, team: {"alice", "hertie-dsl-bot"}
    )
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
        utils,
        "get_team_members",
        lambda org, team: {"alice", "hertie-dsl-bot", "henrycgbaker"},
    )
    monkeypatch.setattr(
        utils, "_acting_login", lambda: "henrycgbaker"
    )  # a human, running locally
    monkeypatch.setattr(
        utils,
        "get_org_owners",
        lambda org: frozenset({"hertie-dsl-bot", "henrycgbaker"}),
    )
    removed = []
    monkeypatch.setattr(utils, "add_team_member", lambda *a, **k: True)
    monkeypatch.setattr(
        utils, "remove_team_member", lambda org, team, h: removed.append(h) or True
    )
    errors = utils.reconcile_team_members("org", "course-admin", wanted=set())
    assert errors == 0
    assert removed == ["alice"]  # neither owner touched, despite neither being declared
