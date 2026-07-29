"""dsl-course seed -- render + place the run-from-repo faculty & instructors workflows.

The Release / Provision actions live INSIDE course content (and assignment-template)
repos, so faculty & instructors trigger them from the repo they're working in. The repo the workflow
runs in is the SOURCE; the action pushes into a chosen cohort org/repo.

The cohort org input is a GitHub `choice` dropdown. GitHub can't populate a dropdown
live, so its options are rendered into the YAML from the cohort registry and
refreshed on demand: `refresh` reads the course org's .github/cohort-courses-pages.yml
`cohorts:` list (maintained by `bootstrap --cohort --course X`, or by hand), lists
their repos, and re-pushes the content actions to every course repo. No cron, no app.

This module is the placement + CLI layer; the three jobs it used to also do live next to
it, and are re-exported below so `dsl_course.seed.<name>` keeps working:

- workflows_render - the workflow YAML templates and every render_* function;
- discovery       - the cohort registry and all live org/repo/section/session discovery;
- profile_readme  - the org landing page + `.github` repo README;
- release_budget  - GitHub's 10-input cap and how many section checkboxes fit under it.

CLI:
  refresh --course-org X   re-render the content actions into every course repo with
                           fresh cohort/session/assignment dropdowns, and rebuild the
                           org profile README. (Run by the Refresh-actions and
                           Bootstrap-cohort workflows.)
"""

from __future__ import annotations

import argparse
import os
import sys

from .central import CENTRAL, CENTRAL_REF
from .discovery import (
    COHORTS_PATH,
    INFRA_REPOS,
    INFRA_TOPICS,
    _is_infra_repo,
    _repo_tree_dirs,
    discover_assignments,
    discover_cohort_repos,
    discover_cohorts,
    discover_content_repos,
    discover_release_sources,
    discover_sections,
    discover_sections_and_sessions,
    discover_sections_union,
    discover_sessions,
    list_org_repos,
    register_cohort,
)
from .profile_readme import (
    COURSE_CONFIG,
    render_dotgithub_readme,
    render_profile_readme,
    update_profile_readme,
)
from .release_budget import MAX_RELEASE_SECTIONS, cap_sections
from .utils import delete_file, gh, log_ok, log_step, put_file
from .workflows_render import (
    _CHECK_TEAM,
    _FACULTY_ONLY,
    _choice,
    _cohort_dropdown,
    _section_release_inputs,
    _sessions_input,
    render_bootstrap_cohort,
    render_central_release,
    render_distribute_grades,
    render_grade_assignment,
    render_new_assignment,
    render_new_materials,
    render_provision,
    render_publish_site,
    render_refresh,
    render_release,
    render_release_code,
    render_render_grades,
    render_scheduler,
    render_send_codes,
    render_status,
    render_sync_gradebooks,
    render_sync_membership,
    render_sync_site,
)

# Historic name for release_budget.cap_sections, kept so `seed._cap_sections` (docs,
# tests, any pinned caller) still resolves.
_cap_sections = cap_sections

# The facade: `dsl_course.seed.<name>` resolves for everything the module ever exposed,
# so the split above is invisible to callers (site, scaffold, bootstrap_course,
# sync_faculty, sync_membership, scheduler, the seeded workflows' CLI) - new code should
# import from the owning module instead.
__all__ = [
    # placement + CLI (this module's own job)
    "WORKFLOWS",
    "main",
    "refresh",
    "seed_github_workflows",
    "_propagate_repo_secret",
    "_push_workflows",
    # central.py
    "CENTRAL",
    "CENTRAL_REF",
    # release_budget.py
    "MAX_RELEASE_SECTIONS",
    "cap_sections",
    "_cap_sections",
    # discovery.py
    "COHORTS_PATH",
    "INFRA_REPOS",
    "INFRA_TOPICS",
    "discover_assignments",
    "discover_cohort_repos",
    "discover_cohorts",
    "discover_content_repos",
    "discover_release_sources",
    "discover_sections",
    "discover_sections_and_sessions",
    "discover_sections_union",
    "discover_sessions",
    "list_org_repos",
    "register_cohort",
    "_is_infra_repo",
    "_repo_tree_dirs",
    # profile_readme.py
    "COURSE_CONFIG",
    "render_dotgithub_readme",
    "render_profile_readme",
    "update_profile_readme",
    # workflows_render.py
    "render_bootstrap_cohort",
    "render_central_release",
    "render_distribute_grades",
    "render_grade_assignment",
    "render_new_assignment",
    "render_new_materials",
    "render_provision",
    "render_publish_site",
    "render_refresh",
    "render_release",
    "render_release_code",
    "render_render_grades",
    "render_scheduler",
    "render_send_codes",
    "render_status",
    "render_sync_gradebooks",
    "render_sync_membership",
    "render_sync_site",
    "_CHECK_TEAM",
    "_FACULTY_ONLY",
    "_choice",
    "_cohort_dropdown",
    "_section_release_inputs",
    "_sessions_input",
]

# The run-from-repo workflows _push_workflows places in every content repo.
WORKFLOWS = (
    ".github/workflows/release-materials.yml",
    ".github/workflows/release-assignment.yml",
    ".github/workflows/release-code.yml",
)


def _push_workflows(
    org: str,
    repo: str,
    cohort_orgs: list[str],
    cohort_repos: list[str],
    assignments: list[str],
) -> None:
    sections, sessions = discover_sections_and_sessions(org, repo)
    sections = cap_sections(sections, f"{org}/{repo}")
    put_file(
        org,
        repo,
        WORKFLOWS[0],
        render_release(cohort_orgs, sessions, sections).encode(),
        "ci: release-materials wrapper",
    )
    put_file(
        org,
        repo,
        WORKFLOWS[1],
        render_provision(cohort_orgs, assignments).encode(),
        "ci: release-assignment wrapper",
    )
    put_file(
        org,
        repo,
        WORKFLOWS[2],
        render_release_code(cohort_orgs, cohort_repos).encode(),
        "ci: release-code wrapper",
    )
    log_ok(f"workflows -> {org}/{repo}")


def seed_github_workflows(course_org: str) -> None:
    """Seed/refresh the org-level workflows into the course org's .github repo: the
    CENTRAL Release materials (source-repo dropdown), Release assignment, plus Sync
    enrolment / Bootstrap cohort / Refresh."""
    cohorts = discover_cohorts(course_org)
    source_repos = discover_content_repos(course_org)
    assignments = discover_assignments(course_org)
    central_sections = cap_sections(
        discover_sections_union(course_org, source_repos),
        f"{course_org}/.github central Release materials button",
    )
    files = {
        ".github/workflows/release-materials.yml": render_central_release(
            source_repos, cohorts, central_sections
        ),
        ".github/workflows/release-assignment.yml": render_provision(
            cohorts, assignments
        ),
        ".github/workflows/grade-assignment.yml": render_grade_assignment(
            cohorts, assignments
        ),
        ".github/workflows/new-materials.yml": render_new_materials(),
        ".github/workflows/new-assignment.yml": render_new_assignment(),
        ".github/workflows/sync-site.yml": render_sync_site(cohorts),
        ".github/workflows/publish-site.yml": render_publish_site(source_repos),
        ".github/workflows/sync-membership.yml": render_sync_membership(cohorts),
        ".github/workflows/send-codes.yml": render_send_codes(cohorts),
        ".github/workflows/sync-gradebooks.yml": render_sync_gradebooks(cohorts),
        ".github/workflows/render-grades.yml": render_render_grades(cohorts),
        ".github/workflows/distribute-grades.yml": render_distribute_grades(cohorts),
        ".github/workflows/bootstrap-cohort.yml": render_bootstrap_cohort(),
        ".github/workflows/status.yml": render_status(cohorts),
        ".github/workflows/refresh-actions.yml": render_refresh(),
        ".github/workflows/scheduled-release.yml": render_scheduler(),
    }
    log_step(f"Seeding org-level workflows into {course_org}/.github")
    for path, content in files.items():
        if put_file(
            course_org, ".github", path, content.encode(), f"ci: {path.split('/')[-1]}"
        ):
            log_ok(f".github <- {path.split('/')[-1]}")

    # Retired in favour of sync-membership.yml (one consolidated button) - remove any
    # copies already seeded into orgs bootstrapped before this change.
    for retired in (
        ".github/workflows/sync-enrolment.yml",
        ".github/workflows/sync-teams.yml",
    ):
        delete_file(course_org, ".github", retired, f"ci: retire {retired.split('/')[-1]} (superseded by sync-membership.yml)")


def _propagate_repo_secret(course_org: str, repos: list[str]) -> None:
    """On GitHub Free, org secrets don't reach PRIVATE repos - so set DSL_BOT_TOKEN as a
    repo secret on each content repo (from the token this run already holds), letting
    their run-from-repo workflows authenticate."""
    token = os.environ.get("DSL_BOT_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return
    for repo in repos:
        code, _ = gh(
            "secret",
            "set",
            "DSL_BOT_TOKEN",
            "--repo",
            f"{course_org}/{repo}",
            "--body",
            token,
        )
        if code == 0:
            log_ok(f"repo secret -> {repo}")


def refresh(course_org: str) -> int:
    """Refresh both layers: the run-from-repo content actions in every content repo,
    AND the central org-level workflows in .github; repopulate dropdowns; rebuild the
    org profile README; and (Free-plan workaround) propagate the token as a repo secret
    so private content repos can authenticate."""
    cohorts = discover_cohorts(course_org)
    cohort_repos = discover_cohort_repos(cohorts)
    targets = discover_content_repos(course_org)
    assignments = discover_assignments(
        course_org
    )  # org-wide; discover once, not per repo
    log_step(
        f"Refreshing {len(targets)} content repo(s) in {course_org} with cohorts {cohorts or 'none'}"
    )
    for repo in sorted(targets):
        _push_workflows(course_org, repo, cohorts, cohort_repos, assignments)
    _propagate_repo_secret(course_org, targets)
    seed_github_workflows(course_org)
    update_profile_readme(course_org)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("refresh")
    pr.add_argument("--course-org", required=True)
    args = parser.parse_args()
    return refresh(args.course_org)


if __name__ == "__main__":
    sys.exit(main())
