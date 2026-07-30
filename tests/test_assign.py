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
        "COURSE", "assignment-1-f2026", "COHORT", roster_path=path, dry_run=True
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
        "COURSE", "assignment-1-f2026", "COHORT", roster_path=str(path), dry_run=True
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
        "COURSE", "assignment-1-f2026", "COHORT", roster_path=path, dry_run=True
    )
    out = capsys.readouterr().out
    assert "1 not-yet-onboarded row(s) skipped" in out
    assert "1 auditor row(s) skipped" in out
