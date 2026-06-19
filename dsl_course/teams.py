"""dsl-course teams -- per-assignment group membership from classroom-config/teams.csv.

`teams.csv` (private, in the cohort's `classroom-config` repo) is the single source of
truth for who is in which team for which assignment:

    assignment,team,github_handle
    assignment-4-project,team-x,anna-adams
    assignment-4-project,team-x,ben-baker
    assignment-4-project,team-y,carla-cohen

Students self-select by opening a "Join team" issue in `welcome` (the workflow appends a
row - authenticated author, size-capped); faculty override by editing the CSV directly. This
CSV is the only writer surface for membership. `sync_teams` then materialises a GitHub Team
`<assignment>-<team>` from it (one-way, idempotent), and group-assignment provisioning grants
that team its shared repo. Because the Team is a downstream projection of the CSV - never
authoritative - it can't drift out of sync the way a Classroom-managed team does.
"""

from __future__ import annotations

import csv
import io

from .utils import get_file_content, log_err

CONFIG_REPO = "classroom-config"
TEAMS_PATH = "teams.csv"
FIELDS = ("assignment", "team", "github_handle")


def parse(text: str) -> dict[str, dict[str, list[str]]]:
    """Parse teams.csv into {assignment: {team: [handles]}}.

    Blank rows are skipped; a handle listed twice in a team is de-duplicated; member
    order follows first appearance so provisioning is deterministic."""
    out: dict[str, dict[str, list[str]]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        assignment = (row.get("assignment") or "").strip()
        team = (row.get("team") or "").strip()
        handle = (row.get("github_handle") or "").strip()
        if not (assignment and team and handle):
            continue
        members = out.setdefault(assignment, {}).setdefault(team, [])
        if handle not in members:
            members.append(handle)
    return out


def load(cohort_org: str) -> dict[str, dict[str, list[str]]]:
    """Fetch + parse teams.csv from the cohort's PRIVATE classroom-config repo."""
    content = get_file_content(cohort_org, CONFIG_REPO, TEAMS_PATH)
    if content is None:
        log_err(
            f"Could not find {TEAMS_PATH} in {cohort_org}/{CONFIG_REPO} - "
            f"no teams defined yet (students self-select via the welcome 'Join team' "
            f"issue, or faculty seed the CSV)."
        )
        return {}
    return parse(content)


def teams_for(
    per: dict[str, dict[str, list[str]]], assignment: str
) -> dict[str, list[str]]:
    """The {team: [handles]} map for one assignment (empty if none)."""
    return per.get(assignment, {})
