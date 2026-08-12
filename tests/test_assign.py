"""assign -- the slug transform, and WHO gets a repo. Auditors are read-only: handing one
an assignment repo (and, downstream, a grade) is the failure this guards. Exercised through
the dry-run path, which is pure: it reads a local roster and prints the planned units
without touching gh/git.
"""

from __future__ import annotations

from dsl_course import assign

HEADER = "student_id,hertie_email,name,github_handle,github_id,section,enrol_code,role"


def _roster_file(tmp_path, *rows: str):
    path = tmp_path / "students.csv"
    path.write_text("\n".join((HEADER, *rows)) + "\n")
    return str(path)


def test_assignment_slug_drops_the_cohort_suffix():
    assert assign.assignment_slug("assignment-1-f2026") == "assignment-1"
    assert assign.assignment_slug("assignment-4-project") == "assignment-4-project"


def test_provisioning_skips_auditors(tmp_path, capsys):
    path = _roster_file(
        tmp_path,
        "1,ada@uni.edu,Ada,ada-l,42,A,dsl-abc,enrolled",
        "2,eve@uni.edu,Eve,eve-e,43,B,dsl-xyz,auditor",
        "3,bob@uni.edu,Bob,bob-b,44,B,dsl-def,",  # blank role -> enrolled
    )
    rc = assign.provision_all(
        "COURSE", "assignment-1-f2026", "COHORT", roster_path=path, group=False, dry_run=True
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "assignment-1-ada-l" in out and "assignment-1-bob-b" in out
    assert "eve-e" not in out  # the auditor gets no repo
    assert "1 auditor row(s) skipped" in out
    assert "2 student(s)" in out


def test_provisioning_still_works_for_a_roster_without_a_role_column(tmp_path, capsys):
    path = tmp_path / "students.csv"
    path.write_text(
        "student_id,hertie_email,name,github_handle,github_id,section\n"
        "1,ada@uni.edu,Ada,ada-l,42,A\n"
    )
    rc = assign.provision_all(
        "COURSE", "assignment-1-f2026", "COHORT", roster_path=str(path), group=False, dry_run=True
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "assignment-1-ada-l" in out
    assert "auditor row(s) skipped" not in out


def test_not_yet_onboarded_rows_are_still_skipped_separately(tmp_path, capsys):
    path = _roster_file(
        tmp_path,
        "1,ada@uni.edu,Ada,ada-l,42,A,dsl-abc,enrolled",
        "2,bob@uni.edu,Bob,,,B,dsl-def,enrolled",  # no handle yet
        "3,eve@uni.edu,Eve,eve-e,43,B,dsl-xyz,auditor",
    )
    assign.provision_all(
        "COURSE", "assignment-1-f2026", "COHORT", roster_path=path, group=False, dry_run=True
    )
    out = capsys.readouterr().out
    assert "1 not-yet-onboarded row(s) skipped" in out
    assert "1 auditor row(s) skipped" in out


def test_group_none_infers_per_team_from_the_templates_grading_yml(
    tmp_path, capsys, monkeypatch
):
    # group=None (the default - scheduler and untick'd button alike) asks the template's
    # own grading.yml: `type: group` provisions per TEAM without anyone force-ticking.
    monkeypatch.setattr(
        "dsl_course.collect.assignment_is_group", lambda org, cohort, template: True
    )
    monkeypatch.setattr(assign.teams, "load", lambda cohort_org: {"unused": {}})
    monkeypatch.setattr(
        assign.teams,
        "teams_for",
        lambda rows, slug: {"team-1": ["ada-l", "bob-b"], "team-2": ["cid-c"]},
    )
    path = _roster_file(
        tmp_path,
        "1,ada@uni.edu,Ada,ada-l,42,A,dsl-abc,enrolled",
        "2,bob@uni.edu,Bob,bob-b,43,A,dsl-def,enrolled",
        "3,cid@uni.edu,Cid,cid-c,44,B,dsl-ghi,enrolled",
    )
    rc = assign.provision_all(
        "COURSE", "assignment-4-project-f2026", "COHORT", roster_path=path, dry_run=True
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "provisioning per team" in out
    assert "assignment-4-project-team-1" in out
    assert "assignment-4-project-team-2" in out
    assert "2 team(s)" in out


def test_group_false_forces_individual_even_for_a_group_template(
    tmp_path, capsys, monkeypatch
):
    # An explicit False never consults grading.yml - the caller decided.
    monkeypatch.setattr(
        "dsl_course.collect.assignment_is_group",
        lambda org, cohort, template: (_ for _ in ()).throw(
            AssertionError("must not be read")
        ),
    )
    path = _roster_file(tmp_path, "1,ada@uni.edu,Ada,ada-l,42,A,dsl-abc,enrolled")
    rc = assign.provision_all(
        "COURSE",
        "assignment-4-project-f2026",
        "COHORT",
        roster_path=path,
        group=False,
        dry_run=True,
    )
    assert rc == 0
    assert "assignment-4-project-ada-l" in capsys.readouterr().out
