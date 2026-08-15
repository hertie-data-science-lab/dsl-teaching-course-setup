"""scaffold create-if-absent + failure propagation.

"New materials repo" / "New assignment" re-run against the SAME tag lands on a repo
`create_repo` reports as already-existing - so the starter files (README.md, SYLLABUS.md,
starter.py/.ipynb, the section .gitkeep scaffolds) must be create-only, never overwriting
faculty content or resurrecting a deleted starter directory. A run that failed to seed the
Release buttons (or the solution branch) must report non-zero, not a green "ready".
"""

from __future__ import annotations

import pytest

from dsl_course import scaffold, seed


class FakeRepo:
    """The file contents a scaffold writes into, plus the skips it logs."""

    def __init__(self, existing: dict[tuple[str, str], str] | None = None):
        self.files: dict[tuple[str, str], str] = dict(existing or {})
        self.writes: list[tuple[str, str]] = []
        self.skips: list[str] = []

    def get_file_content(self, org, repo, path):
        return self.files.get((repo, path))

    def put_file(self, org, repo, path, content, message):
        self.files[(repo, path)] = content.decode()
        self.writes.append((repo, path))
        return True

    def written(self, repo):
        return {path for r, path in self.writes if r == repo}


@pytest.fixture
def fake(monkeypatch):
    f = FakeRepo()
    monkeypatch.setattr(scaffold, "get_file_content", f.get_file_content)
    monkeypatch.setattr(scaffold, "put_file", f.put_file)
    monkeypatch.setattr(scaffold, "log_skip", lambda msg: f.skips.append(msg))
    monkeypatch.setattr(scaffold, "create_repo", lambda *a, **k: True)
    monkeypatch.setattr(scaffold, "grant_course_team_access", lambda *a, **k: None)
    monkeypatch.setattr(scaffold, "grant_tagged_team_access", lambda *a, **k: None)
    monkeypatch.setattr(scaffold, "set_repo_topics", lambda *a, **k: None)
    monkeypatch.setattr(seed, "discover_cohorts", lambda org: [])
    monkeypatch.setattr(seed, "discover_assignments", lambda org: [])
    monkeypatch.setattr(seed, "_push_workflows", lambda *a, **k: 0)
    return f


# --------------------------------------------------------------- materials scaffold


def test_fresh_materials_repo_gets_the_full_skeleton(fake):
    assert scaffold.scaffold_materials("Org", "f2026") == 0
    assert fake.written("course-materials-f2026") == {
        "README.md",
        "MAINTAINING.md",
        "SYLLABUS.md",
        "lectures/01_session-1/.gitkeep",
        "readings/01_session-1/.gitkeep",
        "labs/01_session-1/.gitkeep",
    }
    assert fake.skips == []


def test_rerun_never_overwrites_a_faculty_authored_readme(fake):
    # The live hazard: Release materials copies README.md to students, so a re-run reverting
    # it to the stub silently republishes the placeholder over the faculty's real overview.
    edited = "# Real course overview\n\nWritten by faculty for students.\n"
    fake.files[("course-materials-f2026", "README.md")] = edited

    assert scaffold.scaffold_materials("Org", "f2026") == 0
    assert fake.files[("course-materials-f2026", "README.md")] == edited
    assert "README.md" not in fake.written("course-materials-f2026")
    assert "course-materials-f2026/README.md" in fake.skips


def test_rerun_does_not_resurrect_a_deleted_section_directory(fake):
    # Faculty deleted labs/ (no labs this year). A re-run must not re-create its .gitkeep,
    # which would resurrect the directory. The other absent scaffolds are still seeded.
    fake.files[("course-materials-f2026", "labs/01_session-1/.gitkeep")] = ""

    scaffold.scaffold_materials("Org", "f2026")
    assert "labs/01_session-1/.gitkeep" not in fake.written("course-materials-f2026")
    assert "lectures/01_session-1/.gitkeep" in fake.written("course-materials-f2026")


def test_materials_repo_reports_non_zero_when_release_buttons_do_not_seed(
    fake, monkeypatch
):
    # A materials repo with no Release buttons (workflow writes failed) must not report a
    # green "ready" - _push_workflows' failure count is the exit code.
    monkeypatch.setattr(seed, "_push_workflows", lambda *a, **k: 2)
    assert scaffold.scaffold_materials("Org", "f2026") == 1


# -------------------------------------------------------------- assignment scaffold


def _clone_ok(monkeypatch, git_fake):
    """gh clone materialises an empty work dir; git behaviour is the caller's fake."""
    import pathlib

    def fake_gh(*args, **k):
        if args[:2] == ("repo", "clone"):
            pathlib.Path(args[3]).mkdir(parents=True, exist_ok=True)
            return (0, "")
        return (0, "")

    monkeypatch.setattr(scaffold, "gh", fake_gh)
    monkeypatch.setattr(scaffold, "git", git_fake)


def test_fresh_assignment_seeds_the_starter(fake, monkeypatch):
    _clone_ok(monkeypatch, lambda *a: (0, ""))
    assert scaffold.scaffold_assignment("Org", "1", "f2026") == 0
    assert {"README.md", "starter.py"} <= fake.written("assignment-1-f2026")


def test_rerun_never_overwrites_an_authored_assignment_starter(fake, monkeypatch):
    _clone_ok(monkeypatch, lambda *a: (0, ""))
    authored = '"""Assignment 1."""\n\n\ndef solve():\n    return real_work()\n'
    fake.files[("assignment-1-f2026", "starter.py")] = authored

    assert scaffold.scaffold_assignment("Org", "1", "f2026") == 0
    assert fake.files[("assignment-1-f2026", "starter.py")] == authored
    assert "starter.py" not in fake.written("assignment-1-f2026")
    assert "assignment-1-f2026/starter.py" in fake.skips


def test_assignment_reports_a_failed_solution_branch_checkout(
    fake, monkeypatch, capsys
):
    # A failed `git checkout -b solution` (e.g. the branch already exists) must be reported,
    # not swallowed and then misreported as a push failure further down.
    def git_fake(*args):
        return (1, "") if "checkout" in args else (0, "")

    _clone_ok(monkeypatch, git_fake)
    assert scaffold.scaffold_assignment("Org", "1", "f2026") == 1
    assert "solution branch" in capsys.readouterr().err
