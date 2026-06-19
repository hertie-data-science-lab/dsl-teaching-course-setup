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
        "anna-adams,,,,88,Strong work\n"
        "ben-baker, team-x , 85 , +4 , 89 , Good lead \n"
    )
    rows = grades.parse_grades(text)
    assert [r.github_handle for r in rows] == ["anna-adams", "ben-baker"]
    # values are stripped, never coerced
    assert rows[1].team == "team-x" and rows[1].adjustment == "+4"
    assert rows[0].team == "" and rows[0].final == "88"


def test_individual_entry_drops_group_fields():
    row = grades.GradeRow(github_handle="anna", final="88", comments="Nice")
    assert grades.gradebook_entry(row) == {"final": "88", "comments": "Nice"}


def test_auto_and_manual_are_internal_not_in_gradebook():
    # auto/manual are faculty working columns - the student sees only the published final
    row = grades.GradeRow(
        github_handle="anna", auto="70", manual="18", final="88", comments="Nice"
    )
    entry = grades.gradebook_entry(row)
    assert entry == {"final": "88", "comments": "Nice"}
    assert "auto" not in entry and "manual" not in entry


def test_group_entry_keeps_team_grade_private_adjustment_and_shared_comment():
    row = grades.GradeRow(
        github_handle="ben",
        team="team-x",
        team_grade="85",
        adjustment="+4",
        final="89",
        comments="Led the model work",
        team_comments="Strong project; thin evaluation",
    )
    assert grades.gradebook_entry(row) == {
        "team": "team-x",
        "team_grade": "85",
        "adjustment": "+4",
        "team_comments": "Strong project; thin evaluation",
        "final": "89",
        "comments": "Led the model work",
    }


def test_build_gradebooks_pivots_per_student_across_assignments():
    per = {
        "assignment-1": [grades.GradeRow(github_handle="anna", final="88")],
        "assignment-4": [
            grades.GradeRow(
                github_handle="anna",
                team="team-x",
                team_grade="85",
                adjustment="0",
                final="85",
            ),
            grades.GradeRow(
                github_handle="ben",
                team="team-x",
                team_grade="85",
                adjustment="+4",
                final="89",
            ),
        ],
    }
    books = grades.build_gradebooks(per)
    assert set(books) == {"anna", "ben"}
    assert set(books["anna"]["assignments"]) == {"assignment-1", "assignment-4"}
    # one team-mate never sees the other's private adjustment: it lives in their own book
    assert books["ben"]["assignments"]["assignment-4"]["adjustment"] == "+4"
    assert "adjustment" not in books["anna"]["assignments"]["assignment-1"]


def test_build_gradebooks_skips_blank_handles():
    per = {
        "assignment-1": [
            grades.GradeRow(github_handle="", final="50", comments="ghost row")
        ]
    }
    assert grades.build_gradebooks(per) == {}


def test_render_yaml_roundtrips_and_is_student_scoped():
    per = {
        "assignment-1": [
            grades.GradeRow(github_handle="anna", final="88", comments="Nice")
        ]
    }
    book = grades.build_gradebooks(per)["anna"]
    parsed = yaml.safe_load(grades.render_yaml(book))
    assert parsed["student"] == "anna"
    assert parsed["assignments"]["assignment-1"]["final"] == "88"


def test_merge_auto_upserts_without_clobbering_manual():
    existing = grades.dump_grades(
        [grades.GradeRow(github_handle="anna", manual="18", comments="Nice")]
    )
    out = grades.merge_auto(
        existing, [("anna", {"auto": "70"}), ("ben", {"auto": "60"})]
    )
    rows = {r.github_handle: r for r in grades.parse_grades(out)}
    # the collector's auto score lands without touching the faculty's manual mark/comment
    assert rows["anna"].auto == "70" and rows["anna"].manual == "18"
    assert rows["anna"].comments == "Nice"
    assert rows["ben"].auto == "60"  # a not-yet-listed student is appended


def test_merge_auto_group_sets_team_grade_per_member():
    out = grades.merge_auto(
        "",
        [
            ("anna", {"team": "team-x", "team_grade": "85"}),
            ("ben", {"team": "team-x", "team_grade": "85"}),
        ],
    )
    rows = {r.github_handle: r for r in grades.parse_grades(out)}
    assert rows["anna"].team == "team-x" and rows["anna"].team_grade == "85"
    assert rows["ben"].team_grade == "85"
