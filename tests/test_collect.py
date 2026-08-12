"""collect pure cores -- the grading-spec parse, the junit -> result.json contract, the
summary glyphs, and the deadline-snapshot logic. The gh/git/subprocess wiring is
deliberately not tested (testing strategy: cover the pure logic, not the fan-out), except
where a snapshot decision IS the logic - which commit gets graded is an academic-integrity
answer, so the pin's every branch is pinned down here with git/gh stubbed.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from dsl_course import collect
from dsl_course.roster import Student
from dsl_course.schedule import Schedule

SHA = "a" * 40
OTHER_SHA = "b" * 40


def test_parse_grading_spec_defaults_and_overrides():
    assert collect.parse_grading_spec("") == {
        "type": "individual",
        "format": "py",
        "autograde": True,
        "max_auto": None,
        "tests": "tests",
    }
    spec = collect.parse_grading_spec(
        "type: group\nformat: notebook\nautograde: false\nmax_auto: 20\ntests: solution/tests\n"
    )
    assert spec["type"] == "group" and spec["format"] == "notebook"
    assert spec["autograde"] is False
    assert spec["max_auto"] == 20 and spec["tests"] == "solution/tests"


def test_score_from_junit_counts_only_clean_passes():
    xml = """<testsuite>
      <testcase name="t_pass"/>
      <testcase name="t_fail"><failure>boom</failure></testcase>
      <testcase name="t_err"><error>kaboom</error></testcase>
      <testcase name="t_skip"><skipped/></testcase>
    </testsuite>"""
    result = collect.score_from_junit(xml)
    assert result["max"] == 4 and result["score"] == 1
    passed = {c["name"]: c["passed"] for c in result["tests"]}
    assert passed == {"t_pass": True, "t_fail": False, "t_err": False, "t_skip": False}


def test_score_from_junit_handles_testsuites_root():
    xml = '<testsuites><testsuite><testcase name="a"/></testsuite></testsuites>'
    result = collect.score_from_junit(xml)
    assert result == {"score": 1, "max": 1, "tests": [{"name": "a", "passed": True}]}


def test_summary_lines_use_tick_cross_not_emoji():
    result = {
        "score": 1,
        "max": 2,
        "tests": [{"name": "a", "passed": True}, {"name": "b", "passed": False}],
    }
    text = "\n".join(collect.summary_lines(result))
    assert "✓ a" in text and "✗ b" in text
    assert "✅" not in text and "❌" not in text


def test_today_in_cohort_tz_follows_the_schedule_timezone():
    # The fallback grading pin must anchor to the COHORT's timezone, not the (UTC)
    # Actions runner: +14 and -11 are always different calendar days, so a single
    # runner-local date() cannot be right for both.
    east = collect._today_in_cohort_tz(Schedule(timezone="Pacific/Kiritimati"))
    west = collect._today_in_cohort_tz(Schedule(timezone="Pacific/Niue"))
    assert east != west
    assert east == datetime.now(ZoneInfo("Pacific/Kiritimati")).date().isoformat()


def test_today_in_cohort_tz_defaults_to_berlin():
    berlin = datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
    assert collect._today_in_cohort_tz(Schedule()) == berlin  # no timezone declared
    assert collect._today_in_cohort_tz(Schedule(timezone="Nowhere/Fake")) == berlin


# ----------------------------------------------------------------- snapshot CSV (pure)


def test_snapshot_csv_round_trips_and_keeps_a_blank_sha():
    # A blank sha is a RECORD, not a gap: "nothing had been pushed by the deadline". Drop
    # it and grading falls back to the student-datable pin for exactly the repos where a
    # backdated commit would be most valuable.
    rows = [
        ("assignment-1-ben", "", "2026-10-16T00:04:12+00:00"),
        ("assignment-1-anna", SHA, "2026-10-16T00:04:12+00:00"),
    ]
    text = collect.dump_snapshots(rows)
    assert text.splitlines()[0] == "repo,sha,recorded_at"
    assert text.splitlines()[1].startswith("assignment-1-anna,")  # repo-sorted, stable
    assert collect.parse_snapshots(text) == {
        "assignment-1-anna": SHA,
        "assignment-1-ben": "",
    }


def test_parse_snapshots_skips_rows_without_a_repo():
    text = "repo,sha,recorded_at\n,deadbeef,2026-10-16T00:00:00+00:00\n"
    assert collect.parse_snapshots(text) == {}


def test_snapshot_path_lives_under_snapshots():
    assert collect.snapshot_path("assignment-1") == "snapshots/assignment-1.csv"


@pytest.mark.parametrize(
    "deadline,expected",
    [
        ("2026-10-13", "2026-10-13T23:59:59Z"),  # bare date -> end of day, like the pin
        ("2026-10-15T23:59:59+02:00", "2026-10-15T21:59:59Z"),  # offset -> UTC
        ("2026-10-15T23:59:59", "2026-10-15T23:59:59Z"),  # naive read as UTC
    ],
)
def test_until_param_is_always_a_utc_z_stamp(deadline, expected):
    # A `+HH:MM` offset in a query string would be read as a space, silently shifting the
    # cutoff by hours - so the API cutoff is always normalised to UTC Z.
    assert collect._until_param(deadline) == expected


# ------------------------------------------------------------------------------ the pin


def _git_stub(rev_list_sha: str = "", sha_in_clone: bool = True):
    """A fake `git` recording its calls: `cat-file -e` answers whether the snapshot sha is
    in the clone, `rev-list` answers the date-based fallback."""
    calls: list[tuple[str, ...]] = []

    def fake_git(*args, **kwargs):
        calls.append(args)
        if "cat-file" in args:
            return (0 if sha_in_clone else 1, "")
        if "rev-list" in args:
            return (0, rev_list_sha) if rev_list_sha else (1, "")
        return (0, "")

    return fake_git, calls


def test_pin_commit_prefers_the_snapshot_sha_and_never_looks_at_dates(monkeypatch):
    fake_git, calls = _git_stub(rev_list_sha=OTHER_SHA)
    monkeypatch.setattr(collect, "git", fake_git)
    assert collect._pin_commit(Path("/repo"), "2026-10-15T23:59:59+02:00", SHA) == SHA
    assert any("checkout" in c and SHA in c for c in calls)
    # the whole point: the client-supplied committer date is never consulted
    assert not any("rev-list" in c for c in calls)


def test_pin_commit_blank_snapshot_is_a_recorded_non_submission(monkeypatch):
    # "" means the server saw no commit by the deadline. Falling back to rev-list here
    # would re-open the hole: a later push backdated before the deadline would grade.
    fake_git, calls = _git_stub(rev_list_sha=OTHER_SHA)
    monkeypatch.setattr(collect, "git", fake_git)
    assert collect._pin_commit(Path("/repo"), "2026-10-15T23:59:59+02:00", "") is None
    assert calls == []


def test_pin_commit_falls_back_when_the_snapshot_sha_is_gone(monkeypatch):
    # History rewritten since the snapshot: warn, then pin on dates rather than crash.
    fake_git, calls = _git_stub(rev_list_sha=OTHER_SHA, sha_in_clone=False)
    monkeypatch.setattr(collect, "git", fake_git)
    assert collect._pin_commit(Path("/repo"), "2026-10-15T23:59", SHA) == OTHER_SHA
    assert any("rev-list" in c for c in calls)


def test_pin_commit_without_a_snapshot_uses_the_date_pin(monkeypatch):
    fake_git, calls = _git_stub(rev_list_sha=OTHER_SHA)
    monkeypatch.setattr(collect, "git", fake_git)
    assert collect._pin_commit(Path("/repo"), "2026-10-13") == OTHER_SHA
    before = [a for c in calls for a in c if a.startswith("--before=")]
    assert before == ["--before=2026-10-13 23:59:59"]  # bare date -> end of day


def test_pin_commit_no_commit_at_all_is_none(monkeypatch):
    fake_git, _calls = _git_stub(rev_list_sha="")
    monkeypatch.setattr(collect, "git", fake_git)
    assert collect._pin_commit(Path("/repo"), "2026-10-13") is None


# -------------------------------------------------------- notebook -> importable script

_JUNIT = '<testsuite><testcase name="test_solve"/></testsuite>'


def _fake_nbconvert(monkeypatch, written_suffix: str | None):
    """Stub the two subprocess boundaries `_run_tests` crosses. `written_suffix` is the
    extension nbconvert is pretended to have chosen for its script output (None = it wrote
    nothing at all); pytest always drops a passing junit report."""

    def fake_run(argv, **kwargs):
        if "nbconvert" in argv and written_suffix is not None:
            nb = Path(argv[-1])
            (nb.parent / (nb.stem + written_suffix)).write_text(
                "def solve(xs):\n    return xs\n"
            )
        if "pytest" in argv:
            report = next(a for a in argv if a.startswith("--junitxml="))
            Path(report.split("=", 1)[1]).write_text(_JUNIT)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(collect.subprocess, "run", fake_run)


@pytest.mark.parametrize("suffix", [".txt", ""])
def test_run_tests_renames_a_non_py_nbconvert_output(
    monkeypatch, tmp_path, capsys, suffix
):
    # nbconvert takes the output extension from metadata.language_info.file_extension, so a
    # notebook with empty metadata (or only a kernelspec) converts to starter.txt - or to a
    # bare `starter` - and the hidden tests' `from starter import ...` fails for EVERY
    # submission. The score would be a silent 0/n, so the output is renamed back to .py.
    _fake_nbconvert(monkeypatch, suffix)
    work = tmp_path / "sub"
    work.mkdir()
    (work / "starter.ipynb").write_text("{}")
    tests = tmp_path / "hidden"
    tests.mkdir()
    (tests / "test_x.py").write_text("from starter import solve\n")

    result = collect._run_tests(work, "notebook", tests)

    assert (work / "starter.py").read_text().startswith("def solve")
    assert not (work / f"starter{suffix}").exists()  # renamed, not copied
    assert result == {
        "score": 1,
        "max": 1,
        "tests": [{"name": "test_solve", "passed": True}],
    }
    assert "-> starter.py" in capsys.readouterr().out  # the rename is not silent


def test_run_tests_leaves_a_correct_py_conversion_alone(monkeypatch, tmp_path):
    # The happy path must not be disturbed: a notebook declaring `file_extension: ".py"`
    # already converts to starter.py, and a stray same-stem .txt is not the script.
    _fake_nbconvert(monkeypatch, ".py")
    work = tmp_path / "sub"
    work.mkdir()
    (work / "starter.ipynb").write_text("{}")
    (work / "starter.txt").write_text("notes, not code")
    tests = tmp_path / "hidden"
    tests.mkdir()

    assert collect._run_tests(work, "notebook", tests)["score"] == 1
    assert (work / "starter.py").read_text().startswith("def solve")
    assert (work / "starter.txt").read_text() == "notes, not code"  # untouched


def test_run_tests_py_format_never_converts_anything(monkeypatch, tmp_path):
    _fake_nbconvert(monkeypatch, ".txt")
    work = tmp_path / "sub"
    work.mkdir()
    (work / "starter.ipynb").write_text("{}")  # present but irrelevant for format: py
    tests = tmp_path / "hidden"
    tests.mkdir()

    assert collect._run_tests(work, "py", tests)["score"] == 1
    assert not (work / "starter.py").exists() and not (work / "starter.txt").exists()


def test_stray_conversion_ignores_a_same_stem_directory(tmp_path):
    (tmp_path / "starter").mkdir()  # extensionless candidate that is not a file
    assert collect._stray_conversion(tmp_path / "starter.ipynb") is None


# ------------------------------------------------------------------- target discovery


_STUDENTS = [
    Student("1", "a@x", "Anna", "anna-adams", "", ""),
    Student("2", "b@x", "Ben", "ben-baker", "", ""),
    Student("3", "c@x", "Not yet", "", "", ""),  # enrolled, not onboarded
]
_TEAMS = {"assignment-4-project": {"team-y": ["carla"], "team-x": ["anna-adams"]}}


def test_submission_targets_individual_skips_unonboarded(monkeypatch):
    monkeypatch.setattr(collect.roster, "load", lambda org: _STUDENTS)
    monkeypatch.setattr(collect.teams, "load", lambda org: {})
    assert collect.submission_targets("Cohort", "assignment-1") == [
        ("assignment-1-anna-adams", "anna-adams", ["anna-adams"]),
        ("assignment-1-ben-baker", "ben-baker", ["ben-baker"]),
    ]


def test_submission_targets_infers_group_from_teams_csv(monkeypatch):
    # The snapshot step has no grading.yml to read (it lives on the course template's
    # solution branch, in the other org), so teams.csv rows keyed on the slug are what
    # make an assignment a group one.
    monkeypatch.setattr(collect.teams, "load", lambda org: _TEAMS)
    monkeypatch.setattr(collect.roster, "load", lambda org: _STUDENTS)
    assert collect.submission_targets("Cohort", "assignment-4-project") == [
        ("assignment-4-project-team-x", "team-x", ["anna-adams"]),
        ("assignment-4-project-team-y", "team-y", ["carla"]),
    ]


def test_submission_targets_group_without_teams_is_empty(monkeypatch):
    monkeypatch.setattr(collect.teams, "load", lambda org: {})
    assert collect.submission_targets("Cohort", "assignment-4-project", True) == []


# -------------------------------------------------------------------- taking a snapshot


@pytest.mark.parametrize(
    "response,expected",
    [
        ((0, SHA), SHA),
        ((0, ""), ""),  # repo exists, no commit that early
        ((1, "gh: Not Found (HTTP 404)"), ""),  # not generated -> nothing was on time
        ((1, "Git Repository is empty (HTTP 409)"), ""),
        ((1, "server error (HTTP 500)"), None),  # transient -> the caller must retry
    ],
)
def test_snapshot_sha_maps_api_outcomes(monkeypatch, response, expected):
    monkeypatch.setattr(collect, "gh", lambda *a, **k: response)
    assert collect._snapshot_sha("Cohort", "assignment-1-anna", "2026-10-13") == expected


def test_snapshot_sha_asks_the_api_for_one_commit_before_a_utc_cutoff(monkeypatch):
    seen: list[tuple[str, ...]] = []
    monkeypatch.setattr(collect, "gh", lambda *a, **k: seen.append(a) or (0, SHA))
    collect._snapshot_sha("Cohort", "assignment-1-anna", "2026-10-15T23:59:59+02:00")
    args = seen[0]
    assert "repos/Cohort/assignment-1-anna/commits" in args
    assert "until=2026-10-15T21:59:59Z" in args and "per_page=1" in args


def _stub_snapshot_write(monkeypatch, shas: dict[str, str | None], existing=None):
    """Wire snapshot_assignment onto stubs; returns the (path, text) writes it makes."""
    written: list[tuple[str, str]] = []
    monkeypatch.setattr(collect, "load_snapshots", lambda org, slug: existing)
    monkeypatch.setattr(
        collect,
        "submission_targets",
        lambda org, slug, is_group=None: [(r, r.split("-")[-1], []) for r in shas],
    )
    monkeypatch.setattr(collect, "_snapshot_sha", lambda org, repo, deadline: shas[repo])
    monkeypatch.setattr(
        collect,
        "put_file",
        lambda org, repo, path, content, msg: written.append((path, content.decode()))
        or True,
    )
    return written


def test_snapshot_assignment_records_one_row_per_repo(monkeypatch):
    written = _stub_snapshot_write(
        monkeypatch, {"assignment-1-anna": SHA, "assignment-1-ben": ""}
    )
    assert collect.snapshot_assignment(
        "Cohort", "assignment-1", "2026-10-15T23:59:59+02:00"
    )
    ((path, text),) = written
    assert path == "snapshots/assignment-1.csv"
    assert collect.parse_snapshots(text) == {
        "assignment-1-anna": SHA,
        "assignment-1-ben": "",
    }
    # recorded_at is the SERVER's clock, not anything the schedule or a student supplied
    stamps = {row.split(",")[2] for row in text.splitlines()[1:]}
    assert len(stamps) == 1 and stamps.pop().endswith("+00:00")


def test_snapshot_assignment_never_overwrites_an_existing_snapshot(monkeypatch):
    # Write-once is the whole guarantee: a later run must not be able to move the pin.
    def boom(*args, **kwargs):
        raise AssertionError("an existing snapshot must never be re-taken")

    monkeypatch.setattr(collect, "load_snapshots", lambda org, slug: {"r": SHA})
    monkeypatch.setattr(collect, "_snapshot_sha", boom)
    monkeypatch.setattr(collect, "put_file", boom)
    assert (
        collect.snapshot_assignment("Cohort", "assignment-1", "2026-10-15T23:59") is True
    )


def test_snapshot_assignment_writes_nothing_when_a_lookup_fails(monkeypatch):
    # A transient API failure must not be frozen into a never-rewritten record: abandon
    # the whole file so the next hourly tick rebuilds it.
    written = _stub_snapshot_write(
        monkeypatch, {"assignment-1-anna": SHA, "assignment-1-ben": None}
    )
    assert (
        collect.snapshot_assignment("Cohort", "assignment-1", "2026-10-15T23:59") is False
    )
    assert written == []


def test_snapshot_assignment_fails_when_there_is_nothing_to_snapshot(monkeypatch):
    monkeypatch.setattr(collect, "load_snapshots", lambda org, slug: None)
    monkeypatch.setattr(collect, "submission_targets", lambda *a, **k: [])
    assert (
        collect.snapshot_assignment("Cohort", "assignment-1", "2026-10-15T23:59") is False
    )


def test_load_snapshots_distinguishes_a_missing_file_from_blank_shas(monkeypatch):
    monkeypatch.setattr(collect, "get_file_content", lambda *a: None)
    assert collect.load_snapshots("Cohort", "assignment-1") is None
    monkeypatch.setattr(
        collect,
        "get_file_content",
        lambda *a: "repo,sha,recorded_at\nr,,2026-10-16T00:00:00+00:00\n",
    )
    assert collect.load_snapshots("Cohort", "assignment-1") == {"r": ""}


# --------------------------------------------------------- collect() threads it through


def _fake_solution_clone(*args, **kwargs):
    """`gh repo clone` of the template's solution branch, faked into a real directory."""
    if args[:2] == ("repo", "clone"):
        dest = Path(args[3])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "grading.yml").write_text("autograde: true\nmax_auto: 2\n")
        (dest / "tests").mkdir(exist_ok=True)
    return (0, "")


def _stub_collect(monkeypatch, snapshots):
    monkeypatch.setattr(collect, "gh", _fake_solution_clone)
    monkeypatch.setattr(collect.schedule, "load", lambda org: Schedule())
    monkeypatch.setattr(
        collect,
        "submission_targets",
        lambda org, slug, is_group=None: [
            (f"{slug}-{h}", h, [h]) for h in ("anna", "ben", "cara")
        ],
    )
    monkeypatch.setattr(collect, "load_snapshots", lambda org, slug: snapshots)
    monkeypatch.setattr(collect, "put_file", lambda *a, **k: True)
    monkeypatch.setattr(collect, "get_file_content", lambda *a: "")
    seen: dict[str, str | None] = {}

    def fake_grade(cohort_org, repo, spec, tests_src, deadline, snapshot=None):
        seen[repo] = snapshot
        return {"score": 1, "max": 2, "tests": []}

    monkeypatch.setattr(collect, "_grade_target", fake_grade)
    return seen


def test_collect_passes_each_repos_own_snapshot_entry_to_grading(monkeypatch):
    # The wiring bug worth a test: loading the snapshot but grading the wrong commit.
    seen = _stub_collect(
        monkeypatch, {"assignment-1-anna": SHA, "assignment-1-ben": ""}
    )
    assert collect.collect("Course", "assignment-1-f2026", "Cohort") == 0
    assert seen["assignment-1-anna"] == SHA
    assert seen["assignment-1-ben"] == ""  # recorded non-submission, graded as such
    assert seen["assignment-1-cara"] is None  # absent from the snapshot -> date fallback


def test_collect_without_a_snapshot_grades_on_dates_and_says_so(monkeypatch, capsys):
    seen = _stub_collect(monkeypatch, None)
    assert collect.collect("Course", "assignment-1-f2026", "Cohort") == 0
    assert set(seen.values()) == {None}
    err = capsys.readouterr().err
    assert "snapshots/assignment-1.csv" in err and "students control" in err


def test_template_is_group_reads_the_solution_branch_grading_yml(monkeypatch):
    seen = {}

    def fake_get(org, repo, path, ref=""):
        seen.update(org=org, repo=repo, path=path, ref=ref)
        return "type: group\nformat: py\n"

    monkeypatch.setattr(collect, "get_file_content", fake_get)
    assert collect.template_is_group("Course-Org", "assignment-4-project-f2026")
    assert seen == {
        "org": "Course-Org",
        "repo": "assignment-4-project-f2026",
        "path": collect.GRADING_FILE,
        "ref": collect.SOLUTION_BRANCH,
    }


def test_template_is_group_defaults_to_individual_without_grading_yml(monkeypatch):
    # No solution branch / no grading.yml -> the contents fetch misses -> individual.
    monkeypatch.setattr(collect, "get_file_content", lambda *a, **k: None)
    assert not collect.template_is_group("Course-Org", "assignment-1-f2026")


def test_assignment_is_group_prefers_the_cohort_schedule(monkeypatch):
    # schedule.yml's assignments.<slug>.type wins; grading.yml is only the fallback.
    from dsl_course.schedule import AssignmentEntry, Schedule

    entry = AssignmentEntry(due=datetime(2026, 11, 15, tzinfo=ZoneInfo("Europe/Berlin")))
    sched = Schedule(assignments={"assignment-4-project": entry})
    monkeypatch.setattr(collect.schedule, "load", lambda org: sched)
    calls = []
    monkeypatch.setattr(
        collect, "template_is_group", lambda org, template: calls.append(template) or True
    )
    # no cohort declaration -> falls through to grading.yml
    entry.type = None
    assert collect.assignment_is_group("Course", "Cohort-f2026", "assignment-4-project-f2026")
    assert calls == ["assignment-4-project-f2026"]
    # cohort says individual -> grading.yml is NOT consulted
    entry.type = "individual"
    calls.clear()
    assert not collect.assignment_is_group("Course", "Cohort-f2026", "assignment-4-project-f2026")
    assert calls == []
    # cohort says group -> group, regardless of the template
    entry.type = "group"
    assert collect.assignment_is_group("Course", "Cohort-f2026", "assignment-4-project-f2026")
