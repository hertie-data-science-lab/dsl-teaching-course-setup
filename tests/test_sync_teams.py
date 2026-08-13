"""sync_teams flattens teams.csv into the GitHub Teams it should materialise.

The gh wiring (create/add/remove team) is not tested - only the pure mapping from the
parsed roster of project teams to {team_slug: members}, which decides what gets created,
plus ensure_team's prune guard (the membership primitives stubbed, no live calls).
"""

from __future__ import annotations

import pytest

from dsl_course import sync_teams, utils


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


@pytest.fixture
def stub_team(monkeypatch):
    """Stub the gh primitives ensure_team drives; return the recorded add/remove calls."""
    calls = {"added": [], "removed": []}
    monkeypatch.setattr(sync_teams, "create_team", lambda *a, **k: True)
    monkeypatch.setattr(
        utils,
        "get_team_members",
        lambda org, team: {"anna-adams", "hertie-dsl-bot", "henrycgbaker", "zoe-zed"},
    )
    monkeypatch.setattr(utils, "_acting_login", lambda: "hertie-dsl-bot")
    monkeypatch.setattr(
        utils, "get_org_owners", lambda org: frozenset({"henrycgbaker"})
    )
    monkeypatch.setattr(
        utils,
        "add_team_member",
        lambda org, team, h, role="member": calls["added"].append(h) or True,
    )
    monkeypatch.setattr(
        utils,
        "remove_team_member",
        lambda org, team, h: calls["removed"].append(h) or True,
    )
    return calls


def test_ensure_team_prunes_stray_members_but_never_owners_or_the_bot(stub_team):
    # GitHub auto-adds whoever creates a team, so the bot lands in a project team without
    # ever being a deliberate grant; pruning it (or an org Owner, who has full access
    # regardless) would churn membership - or evict a maintainer - on every sync.
    ok = sync_teams.ensure_team(
        "org", "assignment-4-project-wizards", {"anna-adams", "ben-baker"}, prune=True
    )
    assert ok
    assert stub_team["added"] == ["ben-baker"]
    assert stub_team["removed"] == ["zoe-zed"]


def test_ensure_team_without_prune_only_adds(stub_team):
    ok = sync_teams.ensure_team(
        "org", "assignment-4-project-wizards", {"anna-adams", "ben-baker"}, prune=False
    )
    assert ok
    assert stub_team["added"] == ["ben-baker"]
    assert stub_team["removed"] == []
