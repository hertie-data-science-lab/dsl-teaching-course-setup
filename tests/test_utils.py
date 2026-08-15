"""Session directory helpers: sections/sessions are discovered from the directory
structure itself (any dir with an ordinal-prefixed subdir is a section) - no declared
config, so these pure functions are the whole contract."""

from __future__ import annotations

import pytest

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


def test_repo_is_archived_reads_the_flag_and_assumes_live_when_it_cannot(monkeypatch):
    # This gates whether the nightly refresh skips a cohort, so the failure default is the
    # whole point: an unreadable repo must read as LIVE. Guessing "archived" on a transient
    # error would silently stop converging a running cohort with nothing in the log to say
    # so; guessing "live" costs a loud 403 from the write itself, which is the right alarm.
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (0, "true\n"))
    assert utils.repo_is_archived("Cohort-f2025", "classroom-config") is True
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (0, "false\n"))
    assert utils.repo_is_archived("Cohort-f2026", "classroom-config") is False
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (1, "gh: HTTP 502 - bad gateway"))
    assert utils.repo_is_archived("Cohort-f2026", "classroom-config") is False


def test_get_file_content_returns_none_only_for_a_genuine_404(monkeypatch):
    # None is what every caller reads as "not configured yet" (an unseeded roster, an
    # empty cohort registry), so only a real 404 may produce it - a rate-limited or
    # forbidden read has to be loud, or a transient failure looks like an empty course.
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (1, "gh: Not Found (HTTP 404)"))
    assert utils.get_file_content("Org", "classroom-config", "students.csv") is None
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (1, "gh: HTTP 403 - rate limited"))
    with pytest.raises(RuntimeError, match="Org/classroom-config/students.csv"):
        utils.get_file_content("Org", "classroom-config", "students.csv")


def test_get_file_content_returns_the_decoded_body(monkeypatch):
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (0, "handle,email\n"))
    assert utils.get_file_content("Org", "repo", "students.csv") == "handle,email\n"


def test_gh_always_returns_a_pair(monkeypatch):
    # The retry loop is gh's only return path, so a negative `retries` (no attempt at all)
    # used to fall off the end and hand back None - which every caller unpacks.
    code, out = utils.gh("api", "user", retries=-1)
    assert code != 0 and out


def test_gh_json_names_the_command_it_failed_to_run(monkeypatch):
    # This message is what a CLI prints in an Actions log instead of a traceback, so
    # "gh command failed" on its own leaves nothing to act on.
    import subprocess

    class Result:
        returncode = 1
        stdout = ""
        stderr = "HTTP 403: rate limited"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    with pytest.raises(RuntimeError, match="`gh search repos topic:dsl-course-hub`"):
        utils.gh_json("search", "repos", "topic:dsl-course-hub")


def test_get_org_owners_distinguishes_no_owners_from_an_unreadable_list(monkeypatch):
    # An empty frozenset disables the prune guard in reconcile_team_members, so a failed
    # read must NOT produce one - it produces None, which skips pruning altogether.
    utils.get_org_owners.cache_clear()
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (1, "gh: HTTP 502"))
    assert utils.get_org_owners("Org") is None
    utils.get_org_owners.cache_clear()
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (0, "[]"))
    assert utils.get_org_owners("Org") == frozenset()
    utils.get_org_owners.cache_clear()


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


def test_reconcile_team_members_compares_case_insensitively(monkeypatch, capsys):
    # GitHub logins are case-insensitive: a hand-typed `Anna-Adams` and the API's
    # `anna-adams` are the same account. Comparing raw casing added-then-pruned it every
    # run, oscillating that person's access nightly.
    monkeypatch.setattr(utils, "get_team_members", lambda org, team: {"anna-adams"})
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
    errors = utils.reconcile_team_members("org", "instructors", {"Anna-Adams"})
    assert errors == 0
    assert added == []  # already present (case-folded) - not re-added
    assert removed == []  # ...and therefore not pruned as "unwanted"


def test_reconcile_team_members_aborts_when_current_membership_is_unreadable(
    monkeypatch, capsys
):
    # get_team_members returns None when the team's membership can't be read. Adding or
    # pruning blind against it is unsafe, so the whole reconcile aborts with an error -
    # it must not treat the team as empty (which would re-add everyone, or prune nobody).
    monkeypatch.setattr(utils, "get_team_members", lambda org, team: None)
    added, removed = [], []
    monkeypatch.setattr(
        utils,
        "add_team_member",
        lambda org, team, h, role="member": added.append(h) or True,
    )
    monkeypatch.setattr(
        utils, "remove_team_member", lambda org, team, h: removed.append(h) or True
    )
    errors = utils.reconcile_team_members("org", "instructors", {"alice"})
    assert errors == 1
    assert added == [] and removed == []
    assert "reconcile aborted" in capsys.readouterr().err


def test_get_team_members_returns_none_on_failure_not_an_empty_set(monkeypatch):
    # None (unreadable) must never be conflated with an empty team, or a reconcile acts
    # blind. Mirrors get_org_owners.
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (1, "gh: HTTP 502"))
    assert utils.get_team_members("Org", "students") is None
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (0, "not json"))
    assert utils.get_team_members("Org", "students") is None
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (0, '[{"login": "alice"}]'))
    assert utils.get_team_members("Org", "students") == {"alice"}


def test_active_today_accepts_date_objects_as_bounds():
    # An unquoted `start: 2026-09-01` in people.yml parses to a datetime.date, not a
    # string; `today < start` used to raise TypeError: str < date.
    from datetime import date, datetime

    assert utils.active_today(date(2026, 9, 1), None, "2026-10-01") is True
    assert utils.active_today(date(2026, 11, 1), None, "2026-10-01") is False
    assert utils.active_today(None, date(2026, 9, 30), "2026-10-01") is False
    assert utils.active_today(None, date(2026, 12, 31), "2026-10-01") is True
    # a full datetime (date subclass) is sliced back to its date portion
    assert utils.active_today(datetime(2026, 9, 1, 12, 0), None, "2026-10-01") is True
    # strings still work exactly as before
    assert utils.active_today("2026-09-01", "2026-12-31", "2026-10-01") is True


def test_load_yaml_config_distinguishes_absent_empty_and_malformed(monkeypatch):
    import yaml

    # ABSENT (404 -> get_file_content None) -> None: pruning callers must not treat this
    # as an empty desired set.
    monkeypatch.setattr(utils, "get_file_content", lambda *a, **k: None)
    assert utils.load_yaml_config("Org", ".github", "dsl-course.yml") is None

    # present but empty -> {} (a legitimate "empty the team")
    monkeypatch.setattr(utils, "get_file_content", lambda *a, **k: "")
    assert utils.load_yaml_config("Org", ".github", "dsl-course.yml") == {}

    # present with content -> the parsed mapping
    monkeypatch.setattr(utils, "get_file_content", lambda *a, **k: "people:\n  x: 1\n")
    assert utils.load_yaml_config("Org", ".github", "dsl-course.yml") == {
        "people": {"x": 1}
    }

    # malformed YAML -> logged + raised, never silently {}
    monkeypatch.setattr(utils, "get_file_content", lambda *a, **k: "a: b: c\n")
    with pytest.raises(yaml.YAMLError):
        utils.load_yaml_config("Org", ".github", "dsl-course.yml")

    # a non-mapping top level (list/scalar) -> raised, naming the file
    monkeypatch.setattr(utils, "get_file_content", lambda *a, **k: "- a\n- b\n")
    with pytest.raises(RuntimeError, match="not a YAML mapping"):
        utils.load_yaml_config("Org", ".github", "dsl-course.yml")


def test_load_yaml_config_propagates_a_non_404_read_error(monkeypatch):
    # get_file_content raises on any non-404 failure; load_yaml_config must not swallow it
    # into None/{}, or a transient error reads as "not configured".
    def boom(*a, **k):
        raise RuntimeError("could not read Org/.github/dsl-course.yml: HTTP 403")

    monkeypatch.setattr(utils, "get_file_content", boom)
    with pytest.raises(RuntimeError, match="HTTP 403"):
        utils.load_yaml_config("Org", ".github", "dsl-course.yml")


def test_create_repo_only_treats_a_genuine_name_clash_422_as_success(monkeypatch):
    # A bare `"422" in out` swallowed an invalid-name/policy 422 as success, so the caller
    # then wrote into a repo that was never created. Only the name-clash message is success.
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (0, ""))
    assert utils.create_repo("Org", "good") is True
    monkeypatch.setattr(
        utils,
        "gh",
        lambda *a, **k: (
            1,
            "HTTP 422: Validation Failed - name already exists on this account",
        ),
    )
    assert utils.create_repo("Org", "dup") is True
    monkeypatch.setattr(
        utils,
        "gh",
        lambda *a, **k: (1, "HTTP 422: Validation Failed - name is invalid"),
    )
    assert utils.create_repo("Org", "bad name") is False


def test_create_team_only_treats_an_already_exists_422_as_success(monkeypatch):
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (0, ""))
    assert utils.create_team("Org", "students") is True
    monkeypatch.setattr(
        utils, "gh", lambda *a, **k: (1, "HTTP 422: name already_exists")
    )
    assert utils.create_team("Org", "students") is True
    # The body GitHub's teams endpoint ACTUALLY returns for a duplicate team, verbatim.
    # It says neither "already exists" nor `already_exists`, so it read as a hard failure
    # and every membership sync after a team's first creation died on it.
    duplicate_team_422 = (
        '{"message":"Validation Failed","errors":[{"resource":"Team",'
        '"code":"unprocessable","field":"data",'
        '"message":"Name must be unique for this org"}],'
        '"documentation_url":"https://docs.github.com/rest/teams..."}'
    )
    monkeypatch.setattr(utils, "gh", lambda *a, **k: (1, duplicate_team_422))
    assert utils.create_team("Org", "students") is True
    monkeypatch.setattr(
        utils, "gh", lambda *a, **k: (1, "HTTP 422: Validation Failed - name too long")
    )
    assert utils.create_team("Org", "x" * 200) is False


def test_is_valid_github_username_charset_and_hyphen_rules():
    assert utils.is_valid_github_username("anna-adams")
    assert utils.is_valid_github_username("Anna-Adams")
    assert utils.is_valid_github_username("a" * 39)
    assert not utils.is_valid_github_username("a" * 40)  # too long
    assert not utils.is_valid_github_username("-anna")  # leading hyphen
    assert not utils.is_valid_github_username("anna-")  # trailing hyphen
    assert not utils.is_valid_github_username("an--na")  # double hyphen
    assert not utils.is_valid_github_username("a_b")  # underscore not allowed
    assert not utils.is_valid_github_username("")


def test_reconcile_team_members_skips_the_prune_when_the_owners_are_unreadable(
    monkeypatch, capsys
):
    # Without the owner list there is no way to tell an Owner from a stray member, and a
    # blind prune could evict one. Adds still happen; the prune pass is skipped, loudly.
    monkeypatch.setattr(utils, "get_team_members", lambda org, team: {"alice"})
    monkeypatch.setattr(utils, "_acting_login", lambda: None)
    monkeypatch.setattr(utils, "get_org_owners", lambda org: None)
    added, removed = [], []
    monkeypatch.setattr(
        utils,
        "add_team_member",
        lambda org, team, h, role="member": added.append(h) or True,
    )
    monkeypatch.setattr(
        utils, "remove_team_member", lambda org, team, h: removed.append(h) or True
    )
    errors = utils.reconcile_team_members("org", "course-admin", {"carol"})
    assert errors == 0
    assert added == ["carol"]
    assert removed == []
    assert "pruning skipped" in capsys.readouterr().err
