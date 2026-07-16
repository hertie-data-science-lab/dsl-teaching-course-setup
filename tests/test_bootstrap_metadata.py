"""bootstrap_course metadata builders: instructors/TAs/course-admins live on the
persistent course org (the SSOT, mirrored into every cohort by sync_faculty). A
cohort org gets no dsl-course.yml at all - its schedule lives in
classroom-config/schedule.yml (seeded by _SCHEDULE_YML) instead."""

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
    # instructors get an OPTIONAL open-courseware card scaffold; TAs never do - they
    # change every cohort, so they're declared per cohort, not course-level.
    assert "# instructors:" in md
    assert "teaching_assistants" not in md


def test_course_metadata_seeds_admins_live_when_given():
    # --admins at bootstrap must land in the SSOT itself (uncommented), not just get a
    # one-time direct team invite (add_course_admins) - otherwise the next sync_faculty
    # run sees them as undeclared and prunes them right back out.
    md = bc._course_metadata(
        "My-Course-E1", "My Course", "Deep Learning", "E1", admins=["alice", "bob"]
    )
    assert "# people:" not in md  # live, not commented out
    assert "people:" in md
    assert '- github_handle: "alice"' in md
    assert '- github_handle: "bob"' in md


def test_parse_handles_splits_comma_and_space():
    assert bc._parse_handles("alice, bob   carol") == ["alice", "bob", "carol"]
    assert bc._parse_handles("") == []
    assert bc._parse_handles("   ") == []


def test_schedule_yml_seed_is_commented_and_covers_every_field():
    # Mostly-commented, like the old cohort dsl-course.yml schedule block - faculty
    # uncomment what they want to pin.
    assert all(
        line.startswith("#") or not line.strip()
        for line in bc._SCHEDULE_YML.splitlines()
    )
    for key in (
        "timezone", "materials_releases", "when", "deploy",
        "source_repo", "source_path", "dest_repo", "dest_path",
        "assignment", "grade", "semester_start", "semester_end",
        "assignments", "grace_days", "exams",
    ):
        assert key in bc._SCHEDULE_YML


def test_classroom_readme_points_to_course_org_for_people():
    # There is no cohort dsl-course.yml any more - the README is the one place that
    # still tells faculty where people/instructors are actually managed.
    assert "course org" in bc._CLASSROOM_README
    assert "schedule.yml" in bc._CLASSROOM_README
    assert "schedule.csv" not in bc._CLASSROOM_README


def test_cohort_metadata_carries_course_pointer():
    # The cohort .github/dsl-course.yml must carry a `course:` line - the classroom-config
    # dispatchers grep it to find where to fire Sync membership / Sync site.
    md = bc._cohort_metadata("My-Cohort-f2026", "My-Course-E1")
    assert "course: My-Course-E1" in md
    assert "org: My-Cohort-f2026" in md
    # the dispatchers do: grep '^course:' | cut -d: -f2- | xargs
    course = next(
        ln.split(":", 1)[1].strip()
        for ln in md.splitlines()
        if ln.startswith("course:")
    )
    assert course == "My-Course-E1"
