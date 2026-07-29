"""The seeded welcome workflows/forms must be valid YAML - a typo breaks a cohort's
bootstrap (they're put_file'd verbatim into the welcome repo). github-script bodies are
YAML literal-block strings, so safe_load parses the workflow without running any JS.

The JS itself can't be executed here (no node in CI, and github-script has no npm
deps), so what's asserted instead is the Python <-> JS contract: the embedded scripts
parse the CSVs with real quote-aware helpers rather than line.split(','), and every
column they address by name really exists in roster.FIELDS / teams.FIELDS.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from dsl_course import roster, teams

WELCOME = Path(__file__).resolve().parents[1] / "templates" / "welcome"
TEMPLATES = [
    "onboard.yml",
    "team-formation.yml",
    "ISSUE_TEMPLATE/join.yml",
    "ISSUE_TEMPLATE/join-team.yml",
]
# The two workflows carrying an embedded github-script CSV reader/writer.
CSV_WORKFLOWS = {"onboard.yml": "onboard", "team-formation.yml": "form-team"}


def script_of(rel: str, job: str) -> str:
    """The github-script body of a workflow's single step."""
    doc = yaml.safe_load((WELCOME / rel).read_text())
    (step,) = doc["jobs"][job]["steps"]
    return step["with"]["script"]


def code_of(script: str) -> str:
    """The script minus whole-line `//` comments (which discuss the old naive parse)."""
    return "\n".join(
        ln for ln in script.splitlines() if not ln.strip().startswith("//")
    )


def csv_helpers(script: str) -> str:
    """The parseCsv/csvCell/serialiseCsv block, for cross-workflow drift checks."""
    start = script.index("const parseCsv")
    end = script.index("\n", script.index("const serialiseCsv"))
    return script[start:end]


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


@pytest.mark.parametrize("rel,job", sorted(CSV_WORKFLOWS.items()))
def test_csv_is_parsed_with_quote_aware_helpers_not_split(rel, job):
    # A quoted field containing a comma (a name like "Doe, Jane") is legal CSV that
    # Python's csv module writes and reads happily; line.split(',') would shift every
    # column right of it and silently write github_handle/github_id into wrong cells.
    script = script_of(rel, job)
    assert "const parseCsv" in script
    assert "const serialiseCsv" in script
    code = code_of(script)
    assert "split(',')" not in code, "naive comma split still parses a CSV row"
    assert "split('\\n')" not in code, "CSV is still split into lines before parsing"
    # Escaped quotes ("" -> ") on read, and QUOTE_MINIMAL-equivalent quoting on write.
    assert "'\"\"'" in script
    assert '/[",\\r\\n]/' in script


def test_csv_helpers_do_not_drift_between_workflows():
    # Both workflows write the same roster/teams CSVs, so the two hand-rolled copies
    # (no shared module - these files ship verbatim) must stay byte-identical.
    onboard, formation = (
        csv_helpers(script_of(rel, job)) for rel, job in sorted(CSV_WORKFLOWS.items())
    )
    assert onboard == formation


def test_onboard_addresses_roster_columns_declared_in_python():
    script = script_of("onboard.yml", "onboard")
    named = set(re.findall(r"indexOf\('([a-z_]+)'\)", script))
    assert named == {"github_handle", "github_id", "enrol_code", "role"}
    assert named <= set(roster.FIELDS)  # the contract with dsl_course.roster


def test_onboard_routes_auditors_to_the_auditors_team():
    # The role column decides the team: auditors are read-only (released materials, no
    # assignment repos), enrolled students go to `students`. Nothing else about the flow
    # differs, so the team slug must be a variable, not a hardcoded 'students'.
    script = script_of("onboard.yml", "onboard")
    code = code_of(script)
    assert f"=== '{roster.ROLE_AUDITOR}'" in code  # matches the Python spelling
    assert "'auditors' : 'students'" in code
    assert "team_slug: team" in code
    assert "team_slug: 'students'" not in code


def test_onboard_treats_a_missing_role_column_as_enrolled():
    # A cohort whose roster predates the column has no `role` header at all - it must
    # keep onboarding (blank/absent = enrolled, per roster.normalise_role), so `role` is
    # never part of the required-column guard.
    script = script_of("onboard.yml", "onboard")
    code = code_of(script)
    guard = re.search(r"if \((iHandle < 0[^)]*)\)", code).group(1)
    assert "iRole" not in guard, "role must not be a required roster column"
    # every read of the role cell is guarded on the column existing
    assert "iRole >= 0" in code


def test_team_formation_addresses_columns_declared_in_python():
    script = script_of("team-formation.yml", "form-team")
    named = set(re.findall(r"indexOf\('([a-z_]+)'\)", script))
    assert named == set(teams.FIELDS) | {"github_handle"}
    assert named <= set(teams.FIELDS) | set(roster.FIELDS)
    # The header it writes on first use must match teams.FIELDS exactly, in order.
    literal = re.search(r"const FIELDS = \[(.*?)\];", script).group(1)
    assert tuple(re.findall(r"'([a-z_]+)'", literal)) == teams.FIELDS
