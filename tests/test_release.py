"""release_code.parse_path_pairs turns the Release materials button's two
comma-separated inputs into (source_path, dest_path) pairs, and the read grant covers
both cohort role teams.

(Session-directory discovery/matching lives in utils.py - see test_utils.py; the deploy
batching itself is exercised in test_scheduler.py, which drives the same
`deploy_many` the button now goes through.)"""

from __future__ import annotations

import pytest

from dsl_course import release_code, utils


def test_a_single_path_with_no_comma_still_works():
    # The overwhelmingly common case: one folder, mirrored.
    assert release_code.parse_path_pairs("lectures/02_intro") == [
        ("lectures/02_intro", None)
    ]
    # ...and one folder with an explicit destination.
    assert release_code.parse_path_pairs("lectures/02_intro", "week02") == [
        ("lectures/02_intro", "week02")
    ]


def test_blank_dest_path_mirrors_every_source_path():
    # Blank dest_path means the same thing here as an omitted `dest_path:` in
    # schedule.yml: mirror the source path (None = let deploy_many mirror it).
    assert release_code.parse_path_pairs("lectures/02,labs/02,readings/02") == [
        ("lectures/02", None),
        ("labs/02", None),
        ("readings/02", None),
    ]


def test_equal_length_lists_are_paired_by_index():
    assert release_code.parse_path_pairs(
        "lectures/02,labs/02,readings/02", "week02/lecture,week02/lab,week02/reading"
    ) == [
        ("lectures/02", "week02/lecture"),
        ("labs/02", "week02/lab"),
        ("readings/02", "week02/reading"),
    ]


def test_mismatched_counts_fail_loudly_naming_both_counts():
    # A manual button run has an operator watching it, so a short dest list is an
    # error naming both counts - not a silently truncated release (the schedule, on an
    # unattended cron, is the one that drops what it can't pair).
    with pytest.raises(ValueError, match="3 source_paths but 2 dest_paths"):
        release_code.parse_path_pairs("a,b,c", "x,y")
    with pytest.raises(ValueError, match="2 source_paths but 3 dest_paths"):
        release_code.parse_path_pairs("a,b", "x,y,z")


def test_whitespace_and_trailing_commas_are_tolerated():
    # Faculty type these into a GitHub text box: spaces after commas and a stray
    # trailing comma must not change the pairing (or trip the count check).
    assert release_code.parse_path_pairs(
        " lectures/02 , labs/02 ,", "week02/lecture , week02/lab , "
    ) == [
        ("lectures/02", "week02/lecture"),
        ("labs/02", "week02/lab"),
    ]


def test_an_empty_source_path_is_an_error_not_an_empty_batch():
    with pytest.raises(ValueError, match="source-path is empty"):
        release_code.parse_path_pairs("  ,  ")


def test_cli_rejects_a_count_mismatch_with_a_nonzero_exit(monkeypatch, capsys):
    # End to end through the button's own entry point: no clone is attempted, and the
    # run fails visibly rather than releasing a partial batch.
    monkeypatch.setattr(
        release_code, "deploy_many", lambda *a, **k: pytest.fail("must not deploy")
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "release_code",
            "--source-org", "Course",
            "--source-repo", "course-materials-f2026",
            "--cohort-org", "Cohort-f2026",
            "--source-path", "a,b,c",
            "--dest-path", "x,y",
        ],
    )
    assert release_code.main() == 1
    assert "3 source_paths but 2 dest_paths" in capsys.readouterr().err


def test_cli_builds_one_deploy_per_pair_and_one_batch(monkeypatch):
    # Every pair becomes a Deploy against the SAME source/dest repo, and they all go
    # through ONE deploy_many call - so each repo is cloned once for the whole batch.
    seen = {}

    def fake_deploy_many(source_org, cohort_org, deploys, sync=True):
        seen.update(
            source_org=source_org, cohort_org=cohort_org, deploys=deploys, sync=sync
        )
        return 0, True

    monkeypatch.setattr(release_code, "deploy_many", fake_deploy_many)
    monkeypatch.setattr(
        "sys.argv",
        [
            "release_code",
            "--source-org", "Course",
            "--source-repo", "course-materials-f2026",
            "--cohort-org", "Cohort-f2026",
            "--dest-repo", "materials",
            "--source-path", "lectures/02,labs/02",
            "--dest-path", "week02/lecture,",
        ],
    )
    assert release_code.main() == 1  # unpaired counts (2 sources, 1 dest)

    monkeypatch.setattr(
        "sys.argv",
        [
            "release_code",
            "--source-org", "Course",
            "--source-repo", "course-materials-f2026",
            "--cohort-org", "Cohort-f2026",
            "--source-path", "lectures/02,labs/02",
        ],
    )
    assert release_code.main() == 0
    assert seen["source_org"] == "Course" and seen["cohort_org"] == "Cohort-f2026"
    assert [(d.source_repo, d.source_path, d.dest_repo, d.dest_path) for d in seen["deploys"]] == [
        ("course-materials-f2026", "lectures/02", "materials", None),
        ("course-materials-f2026", "labs/02", "materials", None),
    ]
    # The button syncs the site itself (unlike the scheduler, which batches and syncs once).
    assert seen["sync"] is True


def test_dest_repo_defaults_to_materials(monkeypatch):
    captured = []
    monkeypatch.setattr(
        release_code,
        "deploy_many",
        lambda *a, **k: (captured.append(a[2]), (0, True))[1],
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "release_code",
            "--source-org", "Course",
            "--source-repo", "course-materials-f2026",
            "--cohort-org", "Cohort-f2026",
            "--dest-repo", "   ",  # a blank text box must not create a repo named ""
            "--source-path", "lectures/02",
        ],
    )
    assert release_code.main() == 0
    assert captured[0][0].dest_repo == "materials"


def test_released_repos_are_read_by_both_cohort_role_teams():
    # Auditors see exactly what enrolled students see once it's released - the read grant
    # is one helper covering both teams, so no release site can grant only `students`.
    assert utils.READ_TEAMS == ("students", "auditors")
    assert release_code.grant_read_teams is utils.grant_read_teams
