"""The course-org faculty-team access policy is single-sourced and applied to every
scaffolded course repo - so a non-owner instructor can push content to a repo they just
scaffolded (previously only `.github` was granted, leaving content repos unwritable)."""

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
