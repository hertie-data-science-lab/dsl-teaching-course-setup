"""The seeded welcome workflows/forms must be valid YAML - a typo breaks a cohort's
bootstrap (they're put_file'd verbatim into the welcome repo). github-script bodies are
YAML literal-block strings, so safe_load parses the workflow without running any JS.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WELCOME = Path(__file__).resolve().parents[1] / "templates" / "welcome"
TEMPLATES = [
    "onboard.yml",
    "team-formation.yml",
    "ISSUE_TEMPLATE/join.yml",
    "ISSUE_TEMPLATE/join-team.yml",
]


@pytest.mark.parametrize("rel", TEMPLATES)
def test_welcome_template_is_valid_yaml(rel):
    doc = yaml.safe_load((WELCOME / rel).read_text())
    assert isinstance(doc, dict) and doc.get("name")


def test_team_formation_gated_on_join_team_title():
    doc = yaml.safe_load((WELCOME / "team-formation.yml").read_text())
    job = doc["jobs"]["form-team"]
    assert "Join team" in job["if"]
    # writes to the private roster repo, not a public one
    assert "classroom-config" in (WELCOME / "team-formation.yml").read_text()
