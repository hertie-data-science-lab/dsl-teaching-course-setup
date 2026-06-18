"""grades pure core -- the CSV -> per-student gradebook pivot is the bit that must be
right (a wrong row silently emails a student someone else's mark). The gh/git fan-out is
deliberately not mocked, per the testing strategy. No network here.
"""

from __future__ import annotations

import yaml

from dsl_course import grades


def test_parse_grades_tolerates_blank_and_missing_columns():
    text = (
        "github_handle,team,team_grade,adjustment,final,comments\n"
        "ada-lovelace,,,,88,Strong work\n"
        "alan-turing, wizards , 85 , +4 , 89 , Good lead \n"
    )
    rows = grades.parse_grades(text)
    assert [r.github_handle for r in rows] == ["ada-lovelace", "alan-turing"]
    # values are stripped, never coerced
    assert rows[1].team == "wizards" and rows[1].adjustment == "+4"
    assert rows[0].team == "" and rows[0].final == "88"


def test_individual_entry_drops_group_fields():
    row = grades.GradeRow(github_handle="ada", final="88", comments="Nice")
    assert grades.gradebook_entry(row) == {"final": "88", "comments": "Nice"}


def test_auto_and_manual_are_internal_not_in_gradebook():
    # auto/manual are faculty working columns - the student sees only the published final
    row = grades.GradeRow(
        github_handle="ada", auto="70", manual="18", final="88", comments="Nice"
    )
    entry = grades.gradebook_entry(row)
    assert entry == {"final": "88", "comments": "Nice"}
    assert "auto" not in entry and "manual" not in entry


def test_group_entry_keeps_team_grade_private_adjustment_and_shared_comment():
    row = grades.GradeRow(
        github_handle="alan",
        team="wizards",
        team_grade="85",
        adjustment="+4",
        final="89",
        comments="Led the model work",
        team_comments="Strong project; thin evaluation",
    )
    assert grades.gradebook_entry(row) == {
        "team": "wizards",
        "team_grade": "85",
        "adjustment": "+4",
        "team_comments": "Strong project; thin evaluation",
        "final": "89",
        "comments": "Led the model work",
    }


def test_build_gradebooks_pivots_per_student_across_assignments():
    per = {
        "assignment-1": [grades.GradeRow(github_handle="ada", final="88")],
        "assignment-4": [
            grades.GradeRow(
                github_handle="ada", team="wizards", team_grade="85", adjustment="0", final="85"
            ),
            grades.GradeRow(
                github_handle="alan", team="wizards", team_grade="85", adjustment="+4", final="89"
            ),
        ],
    }
    books = grades.build_gradebooks(per)
    assert set(books) == {"ada", "alan"}
    assert set(books["ada"]["assignments"]) == {"assignment-1", "assignment-4"}
    # one team-mate never sees the other's private adjustment: it lives in their own book
    assert books["alan"]["assignments"]["assignment-4"]["adjustment"] == "+4"
    assert "adjustment" not in books["ada"]["assignments"]["assignment-1"]


def test_build_gradebooks_skips_blank_handles():
    per = {"assignment-1": [grades.GradeRow(github_handle="", final="50", comments="ghost row")]}
    assert grades.build_gradebooks(per) == {}


def test_render_yaml_roundtrips_and_is_student_scoped():
    per = {"assignment-1": [grades.GradeRow(github_handle="ada", final="88", comments="Nice")]}
    book = grades.build_gradebooks(per)["ada"]
    parsed = yaml.safe_load(grades.render_yaml(book))
    assert parsed["student"] == "ada"
    assert parsed["assignments"]["assignment-1"]["final"] == "88"
