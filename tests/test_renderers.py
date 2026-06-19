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
    "release": seed.render_release(["Cohort-f2026"], ["materials"], ["1", "2"]),
    "central_release": seed.render_central_release(
        ["course-materials-f2026"], ["Cohort-f2026"], ["materials"]
    ),
    "provision": seed.render_provision(["Cohort-f2026"], ["assignment-1-f2026"]),
    "release_code": seed.render_release_code(["Cohort-f2026"], ["materials"]),
    "enroll": seed.render_enroll(["Cohort-f2026"]),
    "sync_gradebooks": seed.render_sync_gradebooks(["Cohort-f2026"]),
    "render_grades": seed.render_render_grades(["Cohort-f2026"]),
    "distribute_grades": seed.render_distribute_grades(["Cohort-f2026"]),
    "bootstrap_cohort": seed.render_bootstrap_cohort(),
    "refresh": seed.render_refresh(),
    "new_materials": seed.render_new_materials(),
    "new_assignment": seed.render_new_assignment(),
    "sync_site": seed.render_sync_site(["Cohort-f2026"]),
    "publish_site": seed.render_publish_site(["course-materials-f2026"]),
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


def test_choice_falls_back_when_empty():
    # An empty dropdown must still be valid YAML (a placeholder option), never blank.
    assert "(none-yet)" in seed._choice([])
    inp = workflow_inputs(seed.render_publish_site([]))
    assert inp["source_repo"]["options"] == ["(none-yet)"]
