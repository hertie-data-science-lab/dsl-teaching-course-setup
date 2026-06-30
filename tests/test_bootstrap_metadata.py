"""bootstrap_course metadata builders: people + schedule live per-cohort (they vary
by year), never in the persistent course org's dsl-course.yml."""

from __future__ import annotations

from dsl_course import bootstrap_course as bc


def test_course_metadata_is_identity_only():
    md = bc._course_metadata("My-Course-E1", "My Course", "Deep Learning", "E1")
    assert "org: My-Course-E1" in md
    assert "course_name: Deep Learning" in md
    assert "course_code: E1" in md
    # people + schedule are cohort-specific - they must NOT be templated course-side
    assert "people:" not in md
    assert "schedule:" not in md


def test_cohort_metadata_carries_people_and_schedule():
    md = bc._cohort_metadata("My-Course-f2026", "My-Course-E1")
    assert "org: My-Course-f2026" in md
    assert "course: My-Course-E1" in md  # pointer to the parent course org
    # the (commented) per-cohort blocks faculty fill in
    assert "# people:" in md
    assert "# schedule:" in md
    # identity stays course-side; the cohort file must not redeclare it
    assert "course_name:" not in md
    assert "course_code:" not in md


def test_cohort_metadata_without_course_pointer_omits_the_line():
    md = bc._cohort_metadata("My-Course-f2026", "")
    assert "org: My-Course-f2026" in md
    assert "course:" not in md
    assert "# people:" in md and "# schedule:" in md
