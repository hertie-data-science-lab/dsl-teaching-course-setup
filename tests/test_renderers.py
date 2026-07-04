"""The workflow renderers must emit GitHub-parseable YAML with the right inputs/jobs.

A typo in any of these silently breaks a faculty button for every course, so the cheapest
useful guard is: render -> yaml.safe_load -> assert the contract. No network.
"""

from __future__ import annotations

import pytest
import yaml

from conftest import workflow_inputs, workflow_jobs
from dsl_course import seed

# Renderers that take no args (or only simple lists) -> a quick "it parses" sweep.
ALL_RENDERED = {
    "release": seed.render_release(
        ["Cohort-f2026"], ["1", "2"], ["lectures", "labs"]
    ),
    "central_release": seed.render_central_release(
        ["course-materials-f2026"], ["Cohort-f2026"]
    ),
    "provision": seed.render_provision(["Cohort-f2026"], ["assignment-1-f2026"]),
    "grade_assignment": seed.render_grade_assignment(
        ["Cohort-f2026"], ["assignment-1-f2026"]
    ),
    "release_code": seed.render_release_code(["Cohort-f2026"], ["materials"]),
    "sync_membership": seed.render_sync_membership(["Cohort-f2026"]),
    "send_codes": seed.render_send_codes(["Cohort-f2026"]),
    "sync_gradebooks": seed.render_sync_gradebooks(["Cohort-f2026"]),
    "render_grades": seed.render_render_grades(["Cohort-f2026"]),
    "distribute_grades": seed.render_distribute_grades(["Cohort-f2026"]),
    "bootstrap_cohort": seed.render_bootstrap_cohort(),
    "refresh": seed.render_refresh(),
    "new_materials": seed.render_new_materials(),
    "new_assignment": seed.render_new_assignment(),
    "sync_site": seed.render_sync_site(["Cohort-f2026"]),
    "publish_site": seed.render_publish_site(["course-materials-f2026"]),
    "status": seed.render_status(["Cohort-f2026"]),
}


@pytest.mark.parametrize("name", sorted(ALL_RENDERED))
def test_renders_valid_yaml(name):
    doc = yaml.safe_load(ALL_RENDERED[name])
    assert isinstance(doc, dict) and doc.get("name")
    # Every faculty workflow is a workflow_dispatch with a check-team gate.
    assert "check-team" in workflow_jobs(ALL_RENDERED[name])


def test_publish_site_inputs():
    inp = workflow_inputs(
        seed.render_publish_site(["course-materials-f2026", "course-materials-f2025"])
    )
    assert set(inp) == {"source_repo", "readings_mode", "include_lectures"}
    assert inp["source_repo"]["options"] == [
        "course-materials-f2026",
        "course-materials-f2025",
    ]
    assert inp["readings_mode"]["options"] == [
        "reading-list",
        "actual-readings",
        "none",
    ]
    assert inp["readings_mode"]["default"] == "reading-list"
    assert inp["include_lectures"]["type"] == "boolean"


def test_publish_site_has_publish_job_running_public_sync():
    rendered = seed.render_publish_site(["course-materials-f2026"])
    assert "publish" in workflow_jobs(rendered)
    assert "dsl_course.site public-sync" in rendered
    # include_lectures off must map to the CLI flag.
    assert "--no-include-lectures" in rendered


def test_provision_has_group_toggle():
    inp = workflow_inputs(
        seed.render_provision(["Cohort-f2026"], ["assignment-4-project-f2026"])
    )
    assert inp["group"]["type"] == "boolean"
    assert inp["group"]["default"] is False
    assert "--group" in seed.render_provision(["Cohort-f2026"], [])


def test_grade_assignment_calls_collect_with_no_deadline_input():
    # SSOT: the grading deadline comes from the cohort schedule, so the button has no
    # deadline input and never passes --deadline (collect derives it).
    rendered = seed.render_grade_assignment(["Cohort-f2026"], ["assignment-1-f2026"])
    inp = workflow_inputs(rendered)
    assert "deadline" not in inp and inp["group"]["type"] == "boolean"
    assert "dsl_course.collect" in rendered
    assert "--group" in rendered and "--deadline" not in rendered


def test_sync_membership_is_a_consolidated_reconcile():
    # One consolidated, fully-automatic reconcile (roster + teams + faculty) - no
    # --prune toggle at this level, config is always the live truth.
    rendered = seed.render_sync_membership(["Cohort-f2026"])
    inp = workflow_inputs(rendered)
    assert set(inp) == {"cohort_org"}
    assert inp["cohort_org"]["default"] == seed._FACULTY_ONLY
    assert inp["cohort_org"]["options"] == [seed._FACULTY_ONLY, "Cohort-f2026"]
    assert "dsl_course.sync_membership" in rendered
    assert "--prune" not in rendered
    jobs = workflow_jobs(rendered)
    assert {"check-team", "sync-dispatch", "sync-auto"} <= set(jobs)
    trigger = yaml.safe_load(rendered).get("on", yaml.safe_load(rendered).get(True))
    assert set(trigger) == {"push", "repository_dispatch", "schedule", "workflow_dispatch"}


def test_dotgithub_readme_orients_faculty():
    # The .github repo's own README points faculty at the Actions tab where the buttons live.
    course = seed.render_dotgithub_readme("My-Course-E1", "My Course", is_cohort=False)
    assert "control panel" in course
    assert "My-Course-E1/.github/actions" in course
    # A cohort org sends faculty to the parent course org for the buttons instead.
    cohort = seed.render_dotgithub_readme(
        "My-Course-f2026", "My Course", is_cohort=True
    )
    assert "parent course org" in cohort


def test_release_has_one_destination_field_per_section():
    rendered = seed.render_release(["Cohort-f2026"], ["1", "2"], ["lectures", "labs"])
    inp = workflow_inputs(rendered)
    assert set(inp) == {
        "cohort_org",
        "dest_lectures",
        "dest_labs",
        "sessions",
        "include_syllabus",
        "include_readme",
    }
    # Defaults to the section's own name - each section gets its own repo out of the box.
    assert inp["dest_lectures"]["default"] == "lectures"
    assert inp["dest_labs"]["default"] == "labs"
    # Sessions is free text (no multi-select widget in workflow_dispatch), with the
    # discovered sessions surfaced in the description for reference.
    assert "type" not in inp["sessions"]
    assert "1, 2" in inp["sessions"]["description"]
    # No standalone cohort_repo dropdown - destination routing replaces it.
    assert "cohort_repo" not in inp


def test_release_builds_destinations_from_dest_fields():
    rendered = seed.render_release(["Cohort-f2026"], ["1"], ["lectures", "labs"])
    assert "DEST_LECTURES: ${{ inputs.dest_lectures }}" in rendered
    assert '[ -n "$DEST_LECTURES" ] && destinations="$destinations,lectures=$DEST_LECTURES"' in rendered
    assert '--destinations "$destinations"' in rendered
    assert "--sessions \"$SESSIONS\"" in rendered


def test_central_release_has_single_cohort_repo_and_exclude():
    rendered = seed.render_central_release(["course-materials-f2026"], ["Cohort-f2026"])
    inp = workflow_inputs(rendered)
    assert {"source_repo", "cohort_org", "cohort_repo", "exclude", "sessions"} <= set(inp)
    assert inp["cohort_repo"]["required"] is True
    assert "--default-repo \"$COHORT_REPO\"" in rendered


def test_choice_falls_back_when_empty():
    # An empty dropdown must still be valid YAML (a placeholder option), never blank.
    assert "(none-yet)" in seed._choice([])
    inp = workflow_inputs(seed.render_publish_site([]))
    assert inp["source_repo"]["options"] == ["(none-yet)"]
