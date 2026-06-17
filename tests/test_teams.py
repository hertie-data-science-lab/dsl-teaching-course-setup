"""teams.parse is the pure core consumed by group provisioning - a wrong pivot puts a
student on the wrong team's repo. No network.
"""

from __future__ import annotations

from dsl_course import teams


def test_parse_groups_by_assignment_and_team():
    text = (
        "assignment,team,github_handle\n"
        "assignment-4-project,wizards,ada-lovelace\n"
        "assignment-4-project,wizards,alan-turing\n"
        "assignment-4-project,hackers,grace-hopper\n"
        "assignment-6-project,wizards,ada-lovelace\n"
    )
    per = teams.parse(text)
    assert per["assignment-4-project"]["wizards"] == ["ada-lovelace", "alan-turing"]
    assert per["assignment-4-project"]["hackers"] == ["grace-hopper"]
    # per-assignment composition: same team name, different roster next assignment
    assert per["assignment-6-project"]["wizards"] == ["ada-lovelace"]


def test_parse_dedupes_and_skips_blank_rows():
    text = (
        "assignment,team,github_handle\n"
        "a1,t1,ada\n"
        "a1,t1,ada\n"  # duplicate
        "a1,,grace\n"  # blank team -> skipped
        ",t1,alan\n"  # blank assignment -> skipped
    )
    per = teams.parse(text)
    assert per == {"a1": {"t1": ["ada"]}}


def test_teams_for_returns_empty_for_unknown_assignment():
    per = teams.parse("assignment,team,github_handle\na1,t1,ada\n")
    assert teams.teams_for(per, "nope") == {}
    assert teams.teams_for(per, "a1") == {"t1": ["ada"]}
