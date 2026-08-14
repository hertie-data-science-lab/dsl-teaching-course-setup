"""dsl-course seed -- render + place the run-from-repo faculty & instructors workflows.

The Release / Provision actions live INSIDE course content (and assignment-template)
repos, so faculty & instructors trigger them from the repo they're working in. The repo the workflow
runs in is the default SOURCE; the action pushes into a chosen cohort org/repo.

The cohort org input is a GitHub `choice` dropdown. GitHub can't populate a dropdown
live, so its options are rendered into the YAML from the cohort registry and
refreshed on demand: `refresh` reads the course org's .github/cohort-courses-pages.yml
`cohorts:` list (maintained by `bootstrap --cohort --course X`, or by hand) and re-pushes
the content actions to every course repo. No cron, no app.

This module is the placement + CLI layer; the three jobs it used to also do live next to
it, and are imported from there (see `__all__` for the few names still reached for as
`seed.<name>`):

- workflows_render - the workflow YAML templates and every render_* function;
- discovery       - the cohort registry and all live org/repo/section/session discovery;
- profile_readme  - the org landing page + `.github` repo README.

CLI:
  refresh --course-org X   re-render the content actions into every course repo with
                           fresh cohort/course-source-repo/assignment dropdowns, rebuild
                           the org profile README, and re-push each registered cohort's
                           welcome workflows. (Run by the Bootstrap-cohort workflow, and by
                           Refresh actions - on demand and on its nightly cron, which is
                           how an org converges on central without anyone pressing
                           anything.)
"""

from __future__ import annotations

import argparse
import os
import sys

from .discovery import (
    COHORTS_PATH,
    discover_assignments,
    discover_cohort_repos,
    discover_cohorts,
    discover_content_repos,
    discover_release_sources,
    discover_sessions,
    register_cohort,
)
from .profile_readme import update_profile_readme
from .utils import delete_file, gh, log_err, log_ok, log_step, put_file
from .welcome import refresh_welcome_workflows
from .workflows_render import (
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
    render_render_grades,
    render_scheduler,
    render_send_codes,
    render_status,
    render_sync_gradebooks,
    render_sync_membership,
    render_sync_site,
)

# What the rest of the package reaches for as `seed.<name>`: this module's own jobs, plus
# the handful of discovery/profile names its callers (site, scaffold, bootstrap_course,
# sync_faculty, sync_membership) grew up importing from here. Everything else the split
# moved out is imported from its owning module (workflows_render, discovery,
# profile_readme, central) - so should new code be.
__all__ = [  # noqa: RUF022 - grouped by owning module, sorting would lose the grouping
    # placement + CLI (this module's own job)
    "seed_github_workflows",
    "_push_workflows",
    # discovery.py
    "COHORTS_PATH",
    "discover_assignments",
    "discover_cohort_repos",
    "discover_cohorts",
    "discover_content_repos",
    "discover_release_sources",
    "discover_sessions",
    "register_cohort",
    # profile_readme.py
    "update_profile_readme",
]

# The run-from-repo workflows _push_workflows places in every content repo.
WORKFLOWS = (
    ".github/workflows/release-materials.yml",
    ".github/workflows/release-assignment.yml",
)

# Retired in favour of the consolidated Release materials button (whose course_source_path
# takes any folder or file, which is all Release code ever did) - removed from content repos
# seeded before that change, so no repo keeps a button whose CLI no longer exists.
RETIRED_WORKFLOWS = (".github/workflows/release-code.yml",)


def _push_workflows(
    org: str,
    repo: str,
    cohort_orgs: list[str],
    assignments: list[str],
) -> int:
    """Place the run-from-repo buttons in one content repo. Returns the number of writes
    that failed, so refresh can report a run that didn't converge."""
    results = [
        put_file(
            org,
            repo,
            WORKFLOWS[0],
            render_release(cohort_orgs, repo).encode(),
            "ci: release-materials wrapper",
        ),
        put_file(
            org,
            repo,
            WORKFLOWS[1],
            render_provision(cohort_orgs, assignments).encode(),
            "ci: release-assignment wrapper",
        ),
    ]
    results += [
        delete_file(
            org,
            repo,
            retired,
            f"ci: retire {retired.split('/')[-1]} (folded into release-materials.yml)",
        )
        for retired in RETIRED_WORKFLOWS
    ]
    failures = results.count(False)
    if failures:
        log_err(f"{failures} workflow file(s) not written to {org}/{repo}")
    else:
        log_ok(f"workflows -> {org}/{repo}")
    return failures


def seed_github_workflows(course_org: str) -> int:
    """Seed/refresh the org-level workflows into the course org's .github repo: the
    CENTRAL Release materials (course-source-repo dropdown), Release assignment, plus Sync
    enrolment / Bootstrap cohort / Refresh.

    Returns the number of writes that failed - a button that didn't land is exactly the
    thing a green run must not hide."""
    cohorts = discover_cohorts(course_org)
    source_repos = discover_content_repos(course_org)
    assignments = discover_assignments(course_org)
    files = {
        ".github/workflows/release-materials.yml": render_central_release(
            source_repos, cohorts
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
        ".github/workflows/check-cohort-setup.yml": render_status(cohorts),
        ".github/workflows/refresh-actions.yml": render_refresh(),
        ".github/workflows/scheduled-release.yml": render_scheduler(),
    }
    log_step(f"Seeding org-level workflows into {course_org}/.github")
    failures = 0
    for path, content in files.items():
        if put_file(
            course_org, ".github", path, content.encode(), f"ci: {path.split('/')[-1]}"
        ):
            log_ok(f".github <- {path.split('/')[-1]}")
        else:
            failures += 1

    # Retired buttons - remove any copies already seeded into orgs bootstrapped before
    # the change, so faculty never see two buttons for one job. sync-enrolment/sync-teams
    # were consolidated into sync-membership.yml; status.yml was renamed to
    # check-cohort-setup.yml (same workflow, a name that says what it checks).
    for retired in (
        ".github/workflows/sync-enrolment.yml",
        ".github/workflows/sync-teams.yml",
        ".github/workflows/status.yml",
    ):
        if not delete_file(
            course_org,
            ".github",
            retired,
            f"ci: retire {retired.split('/')[-1]} (superseded by sync-membership.yml)",
        ):
            failures += 1
    return failures


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
    org profile README; re-push every registered cohort's welcome workflows; and
    (Free-plan workaround) propagate the token as a repo secret so private content repos
    can authenticate.

    Non-zero if any file could not be written: this runs nightly on a cron, so a run that
    silently failed to converge an org would go unnoticed until someone clicked a button
    that was never seeded."""
    cohorts = discover_cohorts(course_org)
    targets = discover_content_repos(course_org)
    assignments = discover_assignments(
        course_org
    )  # org-wide; discover once, not per repo
    log_step(
        f"Refreshing {len(targets)} content repo(s) in {course_org} with cohorts {cohorts or 'none'}"
    )
    failures = 0
    for repo in sorted(targets):
        failures += _push_workflows(course_org, repo, cohorts, assignments)
    _propagate_repo_secret(course_org, targets)
    failures += seed_github_workflows(course_org)
    update_profile_readme(course_org)
    # A cohort's onboarding workflows are seeded once, at Bootstrap cohort, and would
    # otherwise stay frozen for the whole semester while the engine they call moves on.
    log_step(f"Refreshing welcome workflows in {len(cohorts)} cohort org(s)")
    for cohort in cohorts:
        failures += refresh_welcome_workflows(cohort)
    if failures:
        log_err(f"refresh incomplete: {failures} file(s) could not be written")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("refresh")
    pr.add_argument("--course-org", required=True)
    args = parser.parse_args()
    # A read helper that couldn't reach the API raises; in an Actions log a one-line
    # error beats a traceback, and the run still goes red.
    try:
        return refresh(args.course_org)
    except RuntimeError as exc:
        log_err(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
