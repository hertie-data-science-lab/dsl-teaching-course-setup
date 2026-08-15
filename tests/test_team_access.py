"""The course-org faculty-team access policy is single-sourced and applied to every
scaffolded course repo - so a non-owner instructor can push content to a repo they just
scaffolded (previously only `.github` was granted, leaving content repos unwritable).

The same policy covers a cohort org's infra repos (welcome, classroom-config): the cohort
is `default_repository_permission=none`, so before this only org owners could edit the
roster/schedule or triage onboarding issues."""

from __future__ import annotations

from dsl_course import bootstrap_course, scaffold, utils


def test_course_team_access_policy():
    assert utils.COURSE_TEAM_ACCESS == {"instructors": "push", "course-admin": "admin"}


def test_button_teams_is_single_sourced():
    # bootstrap's .github grant and the scaffold grant must not drift apart
    assert bootstrap_course.BUTTON_TEAMS is utils.COURSE_TEAM_ACCESS


def test_scaffolds_use_the_shared_grant_helper():
    # the materials/assignment scaffolds grant the faculty teams via this helper
    assert scaffold.grant_course_team_access is utils.grant_course_team_access


def test_faculty_teams_are_only_instructors_and_admin():
    slugs = {t[0] for t in bootstrap_course.FACULTY_TEAMS}
    assert slugs == {"instructors", "course-admin"}
    # students/auditors must NOT be created on the persistent course org (it holds
    # unreleased materials, model solutions, and hidden tests)
    assert "students" not in slugs and "auditors" not in slugs


def test_cohort_teams_are_students_and_auditors():
    assert {t[0] for t in bootstrap_course.COHORT_TEAMS} == {"students", "auditors"}


def test_faculty_and_cohort_team_sets_are_disjoint():
    faculty = {t[0] for t in bootstrap_course.FACULTY_TEAMS}
    cohort = {t[0] for t in bootstrap_course.COHORT_TEAMS}
    assert not (faculty & cohort)


def test_cohort_infra_repos_get_the_faculty_grant():
    # A cohort org is default_repository_permission=none, so a non-owner instructor could
    # not open classroom-config (schedule.yml/students.csv/teams.csv/people.yml + grades/)
    # or triage welcome's needs-review onboarding issues without these.
    assert bootstrap_course.COHORT_FACULTY_REPOS == ["welcome", "classroom-config"]


def test_cohort_faculty_grant_uses_the_shared_policy(monkeypatch):
    granted = []

    def fake_grant(org, team, repo, perm):
        granted.append((org, team, repo, perm))
        return True

    monkeypatch.setattr(bootstrap_course, "grant_team_repo_access", fake_grant)
    bootstrap_course.grant_cohort_faculty_access("Course-f2026")
    assert set(granted) == {
        ("Course-f2026", "instructors", "welcome", "push"),
        ("Course-f2026", "course-admin", "welcome", "admin"),
        ("Course-f2026", "instructors", "classroom-config", "push"),
        ("Course-f2026", "course-admin", "classroom-config", "admin"),
    }


def test_cohort_setup_grants_faculty_access_even_when_nothing_is_seeded(monkeypatch):
    # The grant must sit OUTSIDE the `if create_repo(...)` seeding blocks: "Bootstrap
    # cohort" re-runs this on an existing org, and that re-run is the repair path for a
    # cohort bootstrapped before the grant existed.
    granted = []
    monkeypatch.setattr(bootstrap_course, "gh", lambda *a, **k: (0, ""))
    monkeypatch.setattr(bootstrap_course, "create_cohort_teams", lambda org: None)
    monkeypatch.setattr(bootstrap_course, "create_repo", lambda *a, **k: False)
    monkeypatch.setattr(bootstrap_course, "put_file", lambda *a, **k: True)
    monkeypatch.setattr(bootstrap_course.scaffold, "scaffold_site", lambda org: 0)
    monkeypatch.setattr(bootstrap_course, "grant_cohort_faculty_access", granted.append)
    bootstrap_course.setup_cohort_extras("Course-f2026")
    assert granted == ["Course-f2026"]
