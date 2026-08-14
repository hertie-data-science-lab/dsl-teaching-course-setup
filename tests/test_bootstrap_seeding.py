"""Bootstrap seeding is create-only for USER-owned files.

"Bootstrap cohort" is the documented idempotent-repair path (re-run to apply new team
grants, refresh workflows), so it runs against LIVE cohorts. `utils.create_repo` reports
an already-existing repo as success, so the `if create_repo(...)` blocks are no
first-run guard - the guard has to be per file. These tests pin the split:

- USER-owned (classroom-config roster/schedule/people/grades, welcome's student-facing
  README, and the course org's dsl-course.yml SSOT): seeded once, NEVER rewritten - a
  rewrite destroyed a live roster (enrol codes + onboarded handles) in DSL-Demo-f2026.
- SYSTEM-owned (welcome's onboard/team-formation workflows + the issue forms they parse,
  classroom-config's dispatch-sync*.yml, its README contract and `*.csv.sample` worked
  examples, the cohort's generated dsl-course.yml pointer): re-pushed on every run so
  fixes reach running cohorts.
"""

from __future__ import annotations

import pytest

from dsl_course import bootstrap_course as bc
from dsl_course import seed, welcome

USER_OWNED = {
    "students.csv",
    "schedule.yml",
    "people.yml",
    "grades/.gitkeep",
}
SYSTEM_OWNED = {
    ".github/workflows/dispatch-sync.yml",
    ".github/workflows/dispatch-sync-site.yml",
    ".github/workflows/validate-schedule.yml",
    "README.md",
    "students.csv.sample",
    "teams.csv.sample",
    "grades/assignment-1.csv.sample",
}
WELCOME_SYSTEM_OWNED = {
    ".github/workflows/onboard.yml",
    ".github/workflows/team-formation.yml",
    ".github/ISSUE_TEMPLATE/01-join-course.yml",
    ".github/ISSUE_TEMPLATE/02-join-team.yml",
}


class FakeOrg:
    """The repo contents bootstrap writes into, plus the log lines it emits."""

    def __init__(self, existing: dict[tuple[str, str], str] | None = None):
        self.files: dict[tuple[str, str], str] = dict(existing or {})
        self.writes: list[tuple[str, str]] = []
        self.deletes: list[tuple[str, str]] = []
        self.skips: list[str] = []

    def get_file_content(self, org, repo, path):
        return self.files.get((repo, path))

    def put_file(self, org, repo, path, content, message):
        self.files[(repo, path)] = content.decode()
        self.writes.append((repo, path))
        return True

    def delete_file(self, org, repo, path, message):
        self.files.pop((repo, path), None)
        self.deletes.append((repo, path))
        return True

    def written(self, repo):
        return {path for r, path in self.writes if r == repo}


@pytest.fixture
def fake(monkeypatch):
    f = FakeOrg()
    monkeypatch.setattr(bc, "get_file_content", f.get_file_content)
    monkeypatch.setattr(bc, "put_file", f.put_file)
    # The welcome repo's SYSTEM-owned files are written by dsl_course.welcome (so that
    # seed.refresh can re-push them without importing bootstrap_course), so its own
    # put_file/delete_file have to be faked too.
    monkeypatch.setattr(welcome, "put_file", f.put_file)
    monkeypatch.setattr(welcome, "delete_file", f.delete_file)
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
    assert fake.written("welcome") == WELCOME_SYSTEM_OWNED | {"README.md"}
    assert fake.skips == []


def test_welcome_readme_links_to_this_orgs_issue_chooser(fake):
    # The "open a Join issue" link is org-specific, so `{org}` must be substituted - an
    # unrendered placeholder would send every cohort's students to a dead link.
    bc.setup_cohort_extras("Cohort-f2026")
    readme = fake.files[("welcome", "README.md")]
    assert "https://github.com/Cohort-f2026/welcome/issues/new/choose" in readme, readme
    assert "{org}" not in readme


def test_rerun_preserves_a_faculty_edited_welcome_readme(fake):
    # A repo-root README is content faculty may reword for their course; a repair re-run
    # must leave it alone while the .github/ machinery underneath it still refreshes.
    edited = "# Welcome to Deep Learning\n\nOur own wording.\n"
    fake.files[("welcome", "README.md")] = edited

    bc.setup_cohort_extras("Cohort-f2026")

    assert fake.files[("welcome", "README.md")] == edited
    assert fake.written("welcome") == WELCOME_SYSTEM_OWNED
    assert "welcome/README.md" in fake.skips


def test_rerun_preserves_user_config_and_refreshes_workflows(fake):
    # A live mid-semester cohort: real roster + faculty-edited schedule/people, plus a
    # stale README/sample from an older engine version.
    live = {
        "students.csv": "email,github_handle,enrol_code\na@x.edu,ahandle,AB12CD\n",
        "schedule.yml": "timezone: Europe/Berlin\nassignments:\n  - id: a1\n",
        "people.yml": "people:\n  instructors:\n    - github_handle: profx\n",
        "teams.csv.sample": "team,members\nstale,sample\n",
        "README.md": "# stale contract from an older engine\n",
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
        welcome.template("classroom-config/dispatch-sync.yml")
    )
    assert fake.files[("classroom-config", "README.md")] == (
        welcome.template("classroom-config/README.md")
    )
    assert fake.files[("classroom-config", "teams.csv.sample")] == (
        welcome.template("classroom-config/teams.csv.sample")
    )
    assert fake.files[("welcome", ".github/workflows/onboard.yml")] == (
        welcome.template("welcome/onboard.yml")
    )
    assert fake.written("welcome") == WELCOME_SYSTEM_OWNED | {"README.md"}


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


def test_seeded_scaffolds_render_this_cohorts_tag(fake):
    # The commented examples must be copy-paste-correct for THIS cohort: schedule.yml
    # names `course-materials-<tag>` / `assignment-1-<tag>`, people.yml carries this
    # year's dates, and no format placeholder survives into any seeded file.
    bc.setup_cohort_extras("Deep-Learning-f2027")
    sched = fake.files[("classroom-config", "schedule.yml")]
    assert "course-materials-f2027" in sched and "assignment-1-f2027" in sched
    assert "2027-09-15" in sched
    people = fake.files[("classroom-config", "people.yml")]
    assert '"2027-09-01"' in people and '"2028-01-31"' in people
    for (repo, path), content in fake.files.items():
        assert "{tag}" not in content and "{year" not in content, f"{repo}/{path}"


def test_cohort_tag_derivation():
    assert bc._cohort_tag("Deep-Learning-f2027") == ("f2027", 2027)
    assert bc._cohort_tag("Stats-S2030") == ("s2030", 2030)
    # No recognisable suffix -> the fallback keeps the examples plausible.
    assert bc._cohort_tag("Some-Odd-Name") == ("f2026", 2026)


def test_sample_headers_match_the_engine_schemas():
    # The seeded worked examples must always carry the real, current column sets - a
    # drifted sample teaches faculty a schema the engine no longer reads.
    from dsl_course.grades import GRADE_FIELDS
    from dsl_course.roster import FIELDS

    roster_header = ",".join(FIELDS)
    assert (
        welcome.template("classroom-config/students.csv").splitlines()[0]
        == roster_header
    )
    sample = welcome.template("classroom-config/students.csv.sample").splitlines()
    assert sample[0] == roster_header
    assert any(",auditor" in line for line in sample[1:])  # the auditor worked example
    grades_sample = welcome.template(
        "classroom-config/grades/assignment-1.csv.sample"
    ).splitlines()
    assert grades_sample[0] == ",".join(GRADE_FIELDS)


def test_course_dsl_course_yml_is_never_rewritten(fake, monkeypatch):
    # The course org's dsl-course.yml is the faculty SSOT (people.course_admins, instructor
    # cards): a repair re-run of "Bootstrap course" must not reset it to the template.
    monkeypatch.setattr(bc, "set_repo_topics", lambda *a, **k: True)
    edited = (
        "org: My-Course-E1\npeople:\n  course_admins:\n    - github_handle: alice\n"
    )
    fake.files[(".github", "dsl-course.yml")] = edited

    bc.create_profile_repo("My-Course-E1", "My Course", "Deep Learning", "E1")

    assert fake.files[(".github", "dsl-course.yml")] == edited
    assert fake.writes == []
    assert fake.skips == [".github/dsl-course.yml"]


def test_rerun_retires_the_pre_rename_issue_forms(fake):
    # The forms moved to 01-/02- prefixed names (chooser ordering); a live cohort still
    # carrying the old files would show both generations in the issue chooser.
    fake.files[("welcome", ".github/ISSUE_TEMPLATE/join.yml")] = "name: old\n"
    bc.setup_cohort_extras("Cohort-f2026")
    assert ("welcome", ".github/ISSUE_TEMPLATE/join.yml") in fake.deletes
    assert ("welcome", ".github/ISSUE_TEMPLATE/join.yml") not in fake.files


# ------------------------------------------ the one initial site sync a bootstrap does


def _stub_bootstrap(monkeypatch) -> None:
    """Neutralise everything a cohort bootstrap does EXCEPT the site sync - the org-level
    gh/git layer, the repo seeding (covered above) and the summary output."""
    for name in (
        "set_org_settings",
        "create_default_teams",
        "setup_cohort_extras",
        "grant_button_access",
        "seed_workflows",
    ):
        monkeypatch.setattr(bc, name, lambda *a, **k: None)
    monkeypatch.setattr(bc, "preflight", lambda org: True)
    monkeypatch.setattr(bc, "create_profile_repo", lambda *a, **k: None)
    monkeypatch.setattr(bc, "add_course_admins", lambda org, handles: None)
    monkeypatch.setattr(bc, "validate_secret_presence", lambda org, secret: True)
    monkeypatch.setattr(bc, "put_file", lambda *a, **k: True)
    monkeypatch.setattr(bc.seed, "register_cohort", lambda course, cohort: True)
    monkeypatch.setattr(bc.seed, "update_profile_readme", lambda *a, **k: None)
    monkeypatch.setattr(bc.sync_faculty, "sync", lambda course, cohorts=None: 0)


def test_cohort_bootstrap_runs_one_initial_site_sync(monkeypatch):
    # Without it a fresh cohort site keeps the website template's placeholders ("Fall
    # 2025", "Course Name (Code)") until the first successful "Sync site" - which in the
    # live incident never came, because the cohort's schedule.yml stopped parsing.
    synced: list[tuple[str, str]] = []
    _stub_bootstrap(monkeypatch)
    monkeypatch.setattr(bc.site, "sync_site", lambda c, o: synced.append((c, o)) or 0)
    monkeypatch.setattr(
        "sys.argv",
        [
            "bootstrap_course",
            "--org",
            "Cohort-f2026",
            "--cohort",
            "--course",
            "Course-Org",
        ],
    )

    assert bc.main() == 0
    assert synced == [("Course-Org", "Cohort-f2026")]


def _raises(c, o):
    raise RuntimeError("pages 404")


@pytest.mark.parametrize("outcome", [lambda c, o: 1, _raises], ids=["rc=1", "raises"])
def test_bootstrap_survives_a_failing_initial_site_sync(monkeypatch, capsys, outcome):
    # Best effort: Pages provisioning can lag right behind repo creation, and the org is
    # already configured by this point - a hiccup must not fail the bootstrap.
    _stub_bootstrap(monkeypatch)
    monkeypatch.setattr(bc.site, "sync_site", outcome)
    monkeypatch.setattr(
        "sys.argv",
        [
            "bootstrap_course",
            "--org",
            "Cohort-f2026",
            "--cohort",
            "--course",
            "Course-Org",
        ],
    )

    assert bc.main() == 0
    assert "Sync site" in capsys.readouterr().err


def test_bootstrap_reports_an_unreachable_api_instead_of_a_traceback(
    monkeypatch, capsys
):
    # Every read on the way through (the create-only file check, the cohort registry, the
    # repo listing behind the profile README) now raises rather than reporting an absent
    # file or an empty org. Bootstrap runs from a button, so that has to land as an [err]
    # line and a red run, not a Python traceback halfway down the log.
    _stub_bootstrap(monkeypatch)

    def boom(org, org_name=None, course_name=None):
        raise RuntimeError("could not list repos in Course-Org: gh: HTTP 502")

    monkeypatch.setattr(bc.seed, "update_profile_readme", boom)
    monkeypatch.setattr("sys.argv", ["bootstrap_course", "--org", "Course-Org"])

    assert bc.main() == 1
    assert "HTTP 502" in capsys.readouterr().err


# ----------------------------------------- the nightly refresh converges live cohorts


def test_refresh_re_pushes_every_registered_cohorts_welcome_workflows(monkeypatch):
    # A cohort's onboarding workflows are seeded once, at Bootstrap cohort, and then run
    # against an engine that keeps moving on central main. The nightly Refresh is what
    # closes that gap, so it has to reach EVERY registered cohort, not just the course org.
    refreshed: list[str] = []
    _stub_refresh(monkeypatch, welcome_failures=lambda org: refreshed.append(org) or 0)

    assert seed.refresh("Course-Org") == 0
    assert refreshed == ["Cohort-f2026", "Cohort-s2027"]


def _stub_refresh(monkeypatch, welcome_failures=lambda org: 0, seed_failures=0) -> None:
    """Neutralise every network call seed.refresh makes; the two write paths report a
    failure count, which is what refresh's exit code is built from."""
    monkeypatch.setattr(
        seed, "discover_cohorts", lambda org: ["Cohort-f2026", "Cohort-s2027"]
    )
    monkeypatch.setattr(seed, "discover_content_repos", lambda org: [])
    monkeypatch.setattr(seed, "discover_assignments", lambda org: [])
    monkeypatch.setattr(seed, "_propagate_repo_secret", lambda org, repos: None)
    monkeypatch.setattr(seed, "seed_github_workflows", lambda org: seed_failures)
    monkeypatch.setattr(seed, "update_profile_readme", lambda org: None)
    monkeypatch.setattr(seed, "refresh_welcome_workflows", welcome_failures)


@pytest.mark.parametrize(
    ("seed_failures", "welcome_failures"),
    [(2, 0), (0, 1)],
    ids=["org-workflows", "welcome-workflows"],
)
def test_refresh_goes_red_when_it_could_not_converge(
    monkeypatch, capsys, seed_failures, welcome_failures
):
    # The nightly cron is how an org keeps up with central. A run that failed to write
    # the buttons but reported success leaves faculty with a stale (or absent) button and
    # nothing in the Actions list to say so.
    _stub_refresh(
        monkeypatch,
        welcome_failures=lambda org: welcome_failures,
        seed_failures=seed_failures,
    )
    assert seed.refresh("Course-Org") == 1
    assert "refresh incomplete" in capsys.readouterr().err


def test_refresh_cli_logs_an_unreachable_api_instead_of_a_traceback(
    monkeypatch, capsys
):
    # Discovery now raises rather than reporting an empty org; the CLI is where that
    # becomes an [err] line + exit 1, so the Actions log stays readable.
    def boom(org: str) -> list[str]:
        raise RuntimeError("could not list repos in Course-Org: gh: HTTP 502")

    monkeypatch.setattr(seed, "discover_cohorts", boom)
    monkeypatch.setattr("sys.argv", ["seed", "refresh", "--course-org", "Course-Org"])

    assert seed.main() == 1
    assert "HTTP 502" in capsys.readouterr().err


def test_welcome_refresh_counts_failed_writes_and_says_nothing_is_up_to_date(
    monkeypatch, capsys
):
    # "[ok] welcome repo workflows + Join forms up to date" used to print unconditionally,
    # so a cohort whose onboarding workflow never landed still read as fully seeded.
    monkeypatch.setattr(welcome, "put_file", lambda *a, **k: False)
    monkeypatch.setattr(welcome, "delete_file", lambda *a, **k: True)
    assert welcome.refresh_welcome_workflows("Cohort-f2026") == 4
    out = capsys.readouterr()
    assert "up to date" not in out.out
    assert "4 welcome-repo file(s) not written" in out.err


def test_org_settings_ok_line_only_prints_when_2fa_was_set(monkeypatch, capsys):
    # The summary line claims "(2FA enforced)" - it must not print when the PATCH failed.
    monkeypatch.setattr(bc, "gh", lambda *a, **k: (1, "gh: HTTP 403"))
    bc.set_org_settings("Course-Org")
    out = capsys.readouterr()
    assert "2FA enforced" not in out.out
    assert "could not enable 2FA" in out.err

    monkeypatch.setattr(bc, "gh", lambda *a, **k: (0, ""))
    bc.set_org_settings("Course-Org")
    assert "2FA enforced" in capsys.readouterr().out
