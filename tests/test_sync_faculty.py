"""sync_faculty parses the course org's `people:` block and flattens it into desired
GitHub team membership per role. The gh wiring (reconcile_org's add/remove calls) is
not tested here - only the pure parsing and role->team flattening, which decides what
gets reconciled.
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
