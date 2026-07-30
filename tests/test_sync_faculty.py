"""sync_faculty parses a `people:` block (course org's or a cohort's) and flattens it
into desired GitHub team membership per role. The gh wiring (the reconcile/grant
calls) is not tested here - only the pure parsing, role->team flattening, and the
cohort-scoping/tag-matching helpers, which decide what gets reconciled.
"""

from __future__ import annotations

from dsl_course import sync_faculty


def test_parse_faculty_skips_entries_without_github_handle():
    raw = """
people:
  instructors:
    - github_handle: janedoe
      name: "Prof. Jane Doe"
    - name: "No Handle"
  teaching_assistants:
    - github_handle: anOther
  course_admins:
    - github_handle: adminhandle
"""
    faculty = sync_faculty.parse_faculty(raw)
    assert [p["github_handle"] for p in faculty["instructors"]] == ["janedoe"]
    assert [p["github_handle"] for p in faculty["teaching_assistants"]] == ["anOther"]
    assert [p["github_handle"] for p in faculty["course_admins"]] == ["adminhandle"]


def test_parse_faculty_with_no_people_block_is_empty():
    assert sync_faculty.parse_faculty("org: My-Course-E1\n") == {}


def test_desired_team_members_maps_roles_and_filters_by_date():
    faculty = {
        "instructors": [{"github_handle": "janedoe"}],
        "teaching_assistants": [
            {"github_handle": "active-ta", "start": "2026-09-01", "end": "2027-01-31"},
            {"github_handle": "lapsed-ta", "start": "2025-09-01", "end": "2026-01-31"},
        ],
        "course_admins": [{"github_handle": "adminhandle"}],
    }
    desired = sync_faculty.desired_team_members(faculty, today="2026-10-01")
    assert desired == {
        "instructors": {"janedoe", "active-ta"},
        "course-admin": {"adminhandle"},
    }


def test_cohort_roles_only_drops_course_admins():
    faculty = {
        "instructors": [{"github_handle": "janedoe"}],
        "teaching_assistants": [{"github_handle": "anOther"}],
        "course_admins": [{"github_handle": "adminhandle"}],
    }
    cohort_faculty = sync_faculty._cohort_roles_only(faculty)
    assert "course_admins" not in cohort_faculty
    assert cohort_faculty["instructors"] == faculty["instructors"]
    assert cohort_faculty["teaching_assistants"] == faculty["teaching_assistants"]


def test_cohort_roles_only_is_safe_without_course_admins():
    faculty = {"instructors": [{"github_handle": "janedoe"}]}
    assert sync_faculty._cohort_roles_only(faculty) == faculty


def test_cohort_people_yml_declaring_course_admins_grants_nothing():
    # a stray course_admins: entry in a cohort's people.yml must not grant admin -
    # that role is exclusively course-level.
    raw = """
people:
  course_admins:
    - github_handle: sneaky
"""
    faculty = sync_faculty._cohort_roles_only(sync_faculty.parse_faculty(raw))
    desired = sync_faculty.desired_team_members(faculty, today="2026-10-01")
    assert desired == {"instructors": set(), "course-admin": set()}


def test_matches_tag_requires_exact_suffix_with_hyphen():
    assert sync_faculty._matches_tag("course-materials-f2026", "f2026") is True
    assert sync_faculty._matches_tag("assignment-1-s2026", "s2026") is True
    assert sync_faculty._matches_tag("course-materials-f2025", "f2026") is False
    # no hyphen before the tag-like substring - must not false-positive
    assert sync_faculty._matches_tag("course-materials-sf2026", "f2026") is False
    assert sync_faculty._matches_tag("welcome", "f2026") is False


def test_tag_repos_filters_and_always_includes_dotgithub():
    content_repos = ["course-materials-f2026", "course-materials-f2025", "welcome"]
    assignments = ["assignment-1-f2026", "assignment-2-s2026"]
    repos = sync_faculty._tag_repos(content_repos, assignments, "f2026")
    assert repos == [".github", "course-materials-f2026", "assignment-1-f2026"]


def test_tag_repos_empty_lists_still_includes_dotgithub():
    assert sync_faculty._tag_repos([], [], "f2026") == [".github"]


def test_desired_for_filters_to_one_team():
    faculty = {
        "instructors": [{"github_handle": "janedoe"}],
        "course_admins": [{"github_handle": "adminhandle"}],
    }
    assert sync_faculty._desired_for(faculty, "instructors", "2026-10-01") == {"janedoe"}
    assert sync_faculty._desired_for(faculty, "course-admin", "2026-10-01") == {"adminhandle"}
