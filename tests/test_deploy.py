"""deploy.parse_path_pairs turns the Release materials button's two
comma-separated inputs into (course_source_path, cohort_dest_path) pairs, and the read
grant covers both cohort role teams.

(Session-directory discovery/matching lives in utils.py - see test_utils.py; the deploy
batching itself is exercised in test_scheduler.py, which drives the same
`deploy_many` the button now goes through.)"""

from __future__ import annotations

import pytest

from dsl_course import deploy, utils


def test_a_single_path_with_no_comma_still_works():
    # The overwhelmingly common case: one folder, mirrored.
    assert deploy.parse_path_pairs("lectures/02_intro") == [("lectures/02_intro", None)]
    # ...and one folder with an explicit destination.
    assert deploy.parse_path_pairs("lectures/02_intro", "week02") == [
        ("lectures/02_intro", "week02")
    ]


def test_blank_dest_path_mirrors_every_source_path():
    # Blank dest path means the same thing here as an omitted `cohort_dest_path:` in
    # schedule.yml: mirror the source path (None = let deploy_many mirror it).
    assert deploy.parse_path_pairs("lectures/02,labs/02,readings/02") == [
        ("lectures/02", None),
        ("labs/02", None),
        ("readings/02", None),
    ]


def test_equal_length_lists_are_paired_by_index():
    assert deploy.parse_path_pairs(
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
    with pytest.raises(
        ValueError, match="3 course_source_paths but 2 cohort_dest_paths"
    ):
        deploy.parse_path_pairs("a,b,c", "x,y")
    with pytest.raises(
        ValueError, match="2 course_source_paths but 3 cohort_dest_paths"
    ):
        deploy.parse_path_pairs("a,b", "x,y,z")


def test_whitespace_and_trailing_commas_are_tolerated():
    # Faculty type these into a GitHub text box: spaces after commas and a stray
    # trailing comma must not change the pairing (or trip the count check).
    assert deploy.parse_path_pairs(
        " lectures/02 , labs/02 ,", "week02/lecture , week02/lab , "
    ) == [
        ("lectures/02", "week02/lecture"),
        ("labs/02", "week02/lab"),
    ]


def test_an_empty_source_path_is_an_error_not_an_empty_batch():
    with pytest.raises(ValueError, match="course-source-path is empty"):
        deploy.parse_path_pairs("  ,  ")


def test_cli_rejects_a_count_mismatch_with_a_nonzero_exit(monkeypatch, capsys):
    # End to end through the button's own entry point: no clone is attempted, and the
    # run fails visibly rather than releasing a partial batch.
    monkeypatch.setattr(
        deploy, "deploy_many", lambda *a, **k: pytest.fail("must not deploy")
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "deploy",
            "--source-org",
            "Course",
            "--course-source-repo",
            "course-materials-f2026",
            "--cohort-org",
            "Cohort-f2026",
            "--course-source-path",
            "a,b,c",
            "--cohort-dest-path",
            "x,y",
        ],
    )
    assert deploy.main() == 1
    assert "3 course_source_paths but 2 cohort_dest_paths" in capsys.readouterr().err


def test_cli_builds_one_deploy_per_pair_and_one_batch(monkeypatch):
    # Every pair becomes a Deploy against the SAME source/dest repo, and they all go
    # through ONE deploy_many call - so each repo is cloned once for the whole batch.
    seen = {}

    def fake_deploy_many(source_org, cohort_org, deploys, sync=True):
        seen.update(
            source_org=source_org, cohort_org=cohort_org, deploys=deploys, sync=sync
        )
        return 0, True

    monkeypatch.setattr(deploy, "deploy_many", fake_deploy_many)
    monkeypatch.setattr(
        "sys.argv",
        [
            "deploy",
            "--source-org",
            "Course",
            "--course-source-repo",
            "course-materials-f2026",
            "--cohort-org",
            "Cohort-f2026",
            "--cohort-dest-repo",
            "materials",
            "--course-source-path",
            "lectures/02,labs/02",
            "--cohort-dest-path",
            "week02/lecture,",
        ],
    )
    assert deploy.main() == 1  # unpaired counts (2 sources, 1 dest)

    monkeypatch.setattr(
        "sys.argv",
        [
            "deploy",
            "--source-org",
            "Course",
            "--course-source-repo",
            "course-materials-f2026",
            "--cohort-org",
            "Cohort-f2026",
            "--course-source-path",
            "lectures/02,labs/02",
        ],
    )
    assert deploy.main() == 0
    assert seen["source_org"] == "Course" and seen["cohort_org"] == "Cohort-f2026"
    assert [
        (
            d.course_source_repo,
            d.course_source_path,
            d.cohort_dest_repo,
            d.cohort_dest_path,
        )
        for d in seen["deploys"]
    ] == [
        ("course-materials-f2026", "lectures/02", "materials", None),
        ("course-materials-f2026", "labs/02", "materials", None),
    ]
    # The button syncs the site itself (unlike the scheduler, which batches and syncs once).
    assert seen["sync"] is True


def test_cohort_dest_repo_defaults_to_materials(monkeypatch):
    captured = []
    monkeypatch.setattr(
        deploy,
        "deploy_many",
        lambda *a, **k: (captured.append(a[2]), (0, True))[1],
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "deploy",
            "--source-org",
            "Course",
            "--course-source-repo",
            "course-materials-f2026",
            "--cohort-org",
            "Cohort-f2026",
            "--cohort-dest-repo",
            "   ",  # a blank text box must not create a repo named ""
            "--course-source-path",
            "lectures/02",
        ],
    )
    assert deploy.main() == 0
    assert captured[0][0].cohort_dest_repo == "materials"


def test_dry_run_prints_the_resolved_pairs_without_deploying(monkeypatch, capsys):
    # The human-pressed release path gets the scheduler's dry-run: print the resolved
    # source -> dest pairs and exit, cloning/copying nothing (the cheapest guard against a
    # root-path release landing somewhere unexpected).
    monkeypatch.setattr(
        deploy,
        "deploy_many",
        lambda *a, **k: pytest.fail("must not deploy on --dry-run"),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "deploy",
            "--source-org",
            "Course",
            "--course-source-repo",
            "course-materials-f2026",
            "--cohort-org",
            "Cohort-f2026",
            "--course-source-path",
            "lectures/02,labs/02",
            "--cohort-dest-path",
            "week02/lecture,week02/lab",
            "--dry-run",
        ],
    )
    assert deploy.main() == 0
    out = capsys.readouterr().out
    assert "course-materials-f2026/lectures/02 -> materials/week02/lecture" in out
    assert "course-materials-f2026/labs/02 -> materials/week02/lab" in out


def test_dry_run_flags_an_unsafe_root_path(monkeypatch, capsys):
    # The cheapest guard, needing no clone: a source path that strips to the repo root (a
    # whole-repo release would drag the source's own .git/.github into the cohort tree) is
    # caught in the dry-run and reds the run, before anything is cloned or copied.
    monkeypatch.setattr(
        deploy, "deploy_many", lambda *a, **k: pytest.fail("must not deploy")
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "deploy",
            "--source-org",
            "Course",
            "--course-source-repo",
            "course-materials-f2026",
            "--cohort-org",
            "Cohort-f2026",
            "--course-source-path",
            "lectures/02,/",  # one safe path, one that names the repo root
            "--dry-run",
        ],
    )
    assert deploy.main() == 1
    out = capsys.readouterr().out
    assert "UNSAFE" in out and "names the repo root" in out
    # the safe pair is still shown, so the operator sees the whole batch
    assert "course-materials-f2026/lectures/02 -> materials/lectures/02" in out


def test_released_repos_are_read_by_both_cohort_role_teams():
    # Auditors see exactly what enrolled students see once it's released - the read grant
    # is one helper covering both teams, so no release site can grant only `students`.
    assert utils.READ_TEAMS == ("students", "auditors")
    assert deploy.grant_read_teams is utils.grant_read_teams


# --- releasing the whole repo -------------------------------------------------------
# `/` is the "release everything" spelling. The end-to-end proof that it flows through
# clone -> copytree -> `git add` lives in test_scheduler.py; what is pinned here is the two
# decisions it rests on - which spellings mean the root, and what never travels with a copy.

# The one definition of "this means the repo root". Blank is included because that is what
# an empty `cohort_dest_path` reduces to internally; neither front door accepts it as a
# SOURCE (parse_path_pairs and schedule.py both reject an empty course_source_path).
ROOT_SPELLINGS = ["/", ".", "", "./", "//"]


@pytest.mark.parametrize("spelling", ROOT_SPELLINGS)
def test_every_spelling_of_the_repo_root_resolves_to_the_clone_root(tmp_path, spelling):
    assert deploy._resolve_within(tmp_path, spelling) == tmp_path.resolve()


@pytest.mark.parametrize("escape", ["../outside", "labs/../../outside", "/../outside"])
def test_a_path_escaping_the_clone_is_still_refused(tmp_path, escape):
    # Allowing the root must not have widened the door to paths outside it.
    assert deploy._resolve_within(tmp_path, escape) is None


def test_a_normal_subpath_still_resolves_under_the_clone(tmp_path):
    (tmp_path / "labs").mkdir()
    assert deploy._resolve_within(tmp_path, "labs/") == (tmp_path / "labs").resolve()


def test_a_whole_repo_release_skips_the_faculty_side_of_the_repo(tmp_path):
    # MAINTAINING.md is written into every materials repo by scaffold as "never released";
    # `.github` is the Release buttons and their bot-token wiring. Both are faculty-side, so
    # neither may ride along with "give me everything".
    ignore = deploy._copy_ignore(tmp_path)
    names = [".git", ".github", "MAINTAINING.md", "labs", "SYLLABUS.md"]
    assert ignore(str(tmp_path), names) == {".git", ".github", "MAINTAINING.md"}


def test_the_faculty_side_is_skipped_only_at_the_repo_root(tmp_path):
    # The exclusion is root-ANCHORED, not a basename glob: a faculty member's own
    # `labs/.github/` or `labs/MAINTAINING.md` is content, not release plumbing, and must
    # travel. `.git` is the exception - it is never copyable, at any depth.
    ignore = deploy._copy_ignore(tmp_path)
    names = [".git", ".github", "MAINTAINING.md", "01.md"]
    assert ignore(str(tmp_path / "labs"), names) == {".git"}


def test_naming_the_faculty_side_explicitly_still_releases_it(tmp_path):
    # The skip is what "everything" means, not a ban: releasing `.github` as a named
    # course_source_path is a subpath copy, which excludes nothing but `.git`.
    ignore = deploy._copy_ignore(None)
    assert ignore(str(tmp_path), [".git", ".github", "MAINTAINING.md"]) == {".git"}
