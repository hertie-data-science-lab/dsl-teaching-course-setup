"""sync_teams flattens teams.csv into the GitHub Teams it should materialise.

The gh wiring (create/add/remove team) is not tested - only the pure mapping from the
parsed roster of project teams to {team_slug: members}, which decides what gets created.
"""

from __future__ import annotations

from dsl_course import sync_teams


def test_team_slug_is_assignment_prefixed_and_lowercased():
    # Assignment-prefixed so a name reused across assignments stays org-unique; lower-cased
    # to match the slug GitHub derives from the team name.
    assert (
        sync_teams.team_slug("assignment-4-project", "Wizards")
        == "assignment-4-project-wizards"
    )


def test_desired_teams_flattens_per_assignment_without_collision():
    per = {
        "assignment-4-project": {
            "wizards": ["anna-adams", "ben-baker"],
            "hackers": ["carla-cohen"],
        },
        "assignment-6-capstone": {"wizards": ["dan-davies"]},
    }
    assert sync_teams.desired_teams(per) == {
        "assignment-4-project-wizards": {"anna-adams", "ben-baker"},
        "assignment-4-project-hackers": {"carla-cohen"},
        "assignment-6-capstone-wizards": {"dan-davies"},
    }
