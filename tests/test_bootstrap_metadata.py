"""bootstrap_course metadata builders: instructors/TAs/course-admins live on the
persistent course org (the SSOT, mirrored into every cohort by sync_faculty); the
schedule stays per-cohort (it varies by year)."""

from __future__ import annotations

from dsl_course import bootstrap_course as bc


def test_course_metadata_carries_faculty_block():
    md = bc._course_metadata("My-Course-E1", "My Course", "Deep Learning", "E1")
    assert "org: My-Course-E1" in md
    assert "course_name: Deep Learning" in md
    assert "course_code: E1" in md
    # the (commented) faculty block faculty fill in - schedule stays cohort-side
    assert "# people:" in md
    assert "github_handle" in md
    assert "schedule:" not in md


def test_cohort_metadata_carries_schedule_not_people():
    md = bc._cohort_metadata("My-Course-f2026", "My-Course-E1")
    assert "org: My-Course-f2026" in md
    assert "course: My-Course-E1" in md  # pointer to the parent course org
    # people are managed at the course org level - only a pointer note here
    assert "# people:" not in md
    assert "managed at the COURSE org level" in md
    assert "# schedule:" in md
    # identity stays course-side; the cohort file must not redeclare it
    assert "course_name:" not in md
    assert "course_code:" not in md


def test_cohort_metadata_without_course_pointer_omits_the_line():
    md = bc._cohort_metadata("My-Course-f2026", "")
    assert "org: My-Course-f2026" in md
    assert "course:" not in md
    assert "# people:" not in md
    assert "# schedule:" in md
