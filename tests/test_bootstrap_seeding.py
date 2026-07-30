"""Bootstrap seeding is create-only for USER-owned files.

"Bootstrap cohort" is the documented idempotent-repair path (re-run to apply new team
grants, refresh workflows), so it runs against LIVE cohorts. `utils.create_repo` reports
an already-existing repo as success, so the `if create_repo(...)` blocks are no
first-run guard - the guard has to be per file. These tests pin the split:

- USER-owned (classroom-config roster/schedule/people/teams/README/grades, and the course
  org's dsl-course.yml SSOT): seeded once, NEVER rewritten - a rewrite destroyed a live
  roster (enrol codes + onboarded handles) in DSL-Demo-f2026.
- SYSTEM-owned (welcome's onboard/team-formation workflows + the issue forms they parse,
  classroom-config's dispatch-sync*.yml, the cohort's generated dsl-course.yml pointer):
  re-pushed on every run so fixes reach running cohorts.
"""

from __future__ import annotations

import pytest

from dsl_course import bootstrap_course as bc

USER_OWNED = {
    "students.csv",
    "schedule.yml",
    "people.yml",
    "teams.csv.sample",
    "README.md",
    "grades/.gitkeep",
}
SYSTEM_OWNED = {
    ".github/workflows/dispatch-sync.yml",
    ".github/workflows/dispatch-sync-site.yml",
}


class FakeOrg:
    """The repo contents bootstrap writes into, plus the log lines it emits."""

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
    f = FakeOrg()
    monkeypatch.setattr(bc, "get_file_content", f.get_file_content)
    monkeypatch.setattr(bc, "put_file", f.put_file)
    monkeypatch.setattr(bc, "log_skip", lambda msg: f.skips.append(msg))
    # everything else setup_cohort_extras does is repo-level and safe to re-run; it is
    # stubbed out so these tests stay pure (no gh calls).
    monkeypatch.setattr(bc, "create_repo", lambda *a, **k: True)
    monkeypatch.setattr(bc, "create_cohort_teams", lambda org: None)
    monkeypatch.setattr(bc, "grant_cohort_faculty_access", lambda org: None)
    monkeypatch.setattr(bc, "gh", lambda *a, **k: (0, ""))
    monkeypatch.setattr(bc.scaffold, "scaffold_site", lambda org: 0)
    return f


def test_fresh_cohort_seeds_every_file(fake):
    bc.setup_cohort_extras("Cohort-f2026")
    assert USER_OWNED | SYSTEM_OWNED == fake.written("classroom-config")
    assert fake.written("welcome") == {
        ".github/workflows/onboard.yml",
        ".github/workflows/team-formation.yml",
        ".github/ISSUE_TEMPLATE/join.yml",
        ".github/ISSUE_TEMPLATE/join-team.yml",
    }
    assert fake.skips == []


def test_rerun_preserves_user_config_and_refreshes_workflows(fake):
    # A live mid-semester cohort: real roster + faculty-edited schedule/people/teams.
    live = {
        "students.csv": "email,github_handle,enrol_code\na@x.edu,ahandle,AB12CD\n",
        "schedule.yml": "timezone: Europe/Berlin\nassignments:\n  - id: a1\n",
        "people.yml": "people:\n  instructors:\n    - github_handle: profx\n",
        "teams.csv.sample": "team,members\nreal,edited\n",
        "README.md": "# our cohort\n",
        "grades/.gitkeep": "",
        ".github/workflows/dispatch-sync.yml": "name: stale dispatcher\n",
    }
    fake.files.update({("classroom-config", p): c for p, c in live.items()})
    fake.files[("welcome", ".github/workflows/onboard.yml")] = "name: stale onboard\n"

    bc.setup_cohort_extras("Cohort-f2026")

    # USER-owned files: untouched, byte for byte.
    for path in USER_OWNED:
        assert ("classroom-config", path) not in fake.written("classroom-config"), path
        assert fake.files[("classroom-config", path)] == live[path], path
    assert fake.written("classroom-config") == SYSTEM_OWNED

    # SYSTEM-owned files: re-pushed, so the stale copies are replaced by the templates.
    assert fake.files[("classroom-config", ".github/workflows/dispatch-sync.yml")] == (
        bc._template("classroom-config/dispatch-sync.yml")
    )
    assert fake.files[("welcome", ".github/workflows/onboard.yml")] == (
        bc._template("welcome/onboard.yml")
    )
    assert len(fake.written("welcome")) == 4


def test_rerun_logs_one_skip_per_preserved_file(fake):
    fake.files.update(
        {
            ("classroom-config", "students.csv"): "email\na@x.edu\n",
            ("classroom-config", "schedule.yml"): "timezone: Europe/Berlin\n",
        }
    )
    bc.setup_cohort_extras("Cohort-f2026")
    assert fake.skips == [
        "classroom-config/students.csv",
        "classroom-config/schedule.yml",
    ]


def test_seed_user_file_skips_an_empty_existing_file(fake):
    # get_file_content returns "" for an existing empty file (grades/.gitkeep) - falsy but
    # present, so it must still count as existing.
    fake.files[("classroom-config", "grades/.gitkeep")] = ""
    assert not bc._seed_user_file(
        "Cohort-f2026", "classroom-config", "grades/.gitkeep", b"x", "msg"
    )
    assert fake.writes == []


def test_course_dsl_course_yml_is_never_rewritten(fake, monkeypatch):
    # The course org's dsl-course.yml is the faculty SSOT (people.course_admins, instructor
    # cards): a repair re-run of "Bootstrap course" must not reset it to the template.
    monkeypatch.setattr(bc, "set_repo_topics", lambda *a, **k: True)
    edited = "org: My-Course-E1\npeople:\n  course_admins:\n    - github_handle: alice\n"
    fake.files[(".github", "dsl-course.yml")] = edited

    bc.create_profile_repo("My-Course-E1", "My Course", "Deep Learning", "E1")

    assert fake.files[(".github", "dsl-course.yml")] == edited
    assert fake.writes == []
    assert fake.skips == [".github/dsl-course.yml"]
