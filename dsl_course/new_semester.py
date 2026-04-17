"""dsl-course new-semester -- set up a course org for a new semester.

Implements Option H (ADR 0009): course org holds materials; a per-cohort
satellite org (e.g. hertie-dl-f2026) holds student submission repos.

This command seeds the COURSE ORG (materials, templates, website, instructor
teams). If --satellite-org is passed AND it exists, it also seeds the satellite
(students team, sync workflow). If the satellite doesn't exist yet, we print
instructions for creating it (GitHub.com does not expose a "create org" API).

Usage:
    python3 -m dsl_course.new_semester \\
        --org Hertie-School-Deep-Learning-E1394 \\
        --satellite-org hertie-dl-f2026 \\
        --semester f2026 \\
        --course-name "Deep Learning" \\
        --course-code "GRAD-E1394" \\
        --instructors simonmunzert,conjugateprior \\
        --content-visibility public
"""

from __future__ import annotations

import argparse
import sys
import time

from .utils import (
    add_team_member,
    create_repo,
    create_team,
    get_file_content,
    gh,
    log,
    log_err,
    log_ok,
    log_step,
    put_file,
    semester_label,
    set_repo_topics,
)

TEMPLATE_REPO = "hertie-data-science-lab/course-website-template"
MAIN_ORG = "hertie-data-science-lab"
CONTENT_FOLDERS = ("lectures", "labs", "readings", "resources")


def create_course_org_teams(
    org: str, semester: str, instructors: list[str], tas: list[str]
) -> None:
    """Instructor-facing teams live in the course org (stable identity)."""
    log_step(f"Creating course-org teams in {org} for {semester}")
    label = semester_label(semester)
    create_team(org, f"instructors-{semester}", f"Instructors and TAs - {label}")
    create_team(org, "course-admin", "Course administrators - DSL team")

    slug = f"instructors-{semester}"
    for login in instructors + tas:
        if login and add_team_member(org, slug, login):
            log_ok(f"  added {login} to {slug}")


def create_satellite_teams(
    satellite_org: str,
    semester: str,
    instructors: list[str],
    tas: list[str],
) -> None:
    """Students + auditors live in the per-cohort satellite (submissions live here)."""
    log_step(f"Creating satellite-org teams in {satellite_org} for {semester}")
    label = semester_label(semester)
    create_team(satellite_org, f"students-{semester}", f"Enrolled students - {label}")
    create_team(
        satellite_org,
        f"auditors-{semester}",
        f"Course auditors - {label} (read-only)",
    )
    # Instructors also need access to the satellite for grading
    create_team(
        satellite_org,
        f"instructors-{semester}",
        f"Instructors and TAs - {label}",
    )
    slug = f"instructors-{semester}"
    for login in instructors + tas:
        if login and add_team_member(satellite_org, slug, login):
            log_ok(f"  added {login} to {satellite_org}/{slug}")


def create_content_repo(
    org: str, semester: str, course_code: str, public: bool
) -> None:
    log_step(f"Creating content-{semester}")
    name = f"content-{semester}"
    label = semester_label(semester)
    created = create_repo(
        org,
        name,
        private=not public,
        description=f"Course materials - {label}",
    )
    if not created:
        return

    access_line = (
        "This repository is public."
        if public
        else "Access is restricted to enrolled students and auditors."
    )
    readme = f"""# Course Materials - {label}

This repository contains the course materials for {label}.

## Structure

| Folder | Contents |
| --- | --- |
| `lectures/` | Lecture slides and notes |
| `labs/` | Lab notebooks and exercises |
| `readings/` | Reading list and materials |
| `resources/` | Datasets, helper scripts, references |

## Access

{access_line}
"""
    put_file(
        org, name, "README.md", readme.encode(), "init: add course materials structure"
    )
    for folder in CONTENT_FOLDERS:
        put_file(org, name, f"{folder}/.gitkeep", b"", f"init: add {folder}/")

    set_repo_topics(
        org,
        name,
        [
            f"cohort-{semester}",
            f"course-{_code_slug(course_code)}",
            "course-content",
        ],
    )
    log_ok(f"content-{semester} initialised with standard structure")


def _code_slug(course_code: str) -> str:
    return course_code.lower().replace("grad-", "").replace("_", "-")


def create_assignment_template(
    org: str, semester: str, course_code: str, satellite_org: str | None
) -> None:
    log_step(f"Creating assignment-1-{semester} template repo")
    name = f"assignment-1-{semester}"
    label = semester_label(semester)
    created = create_repo(
        org,
        name,
        private=True,
        description=f"Assignment 1 template - {label}",
        is_template=True,
    )
    if not created:
        return

    destination = f" in `{satellite_org}`" if satellite_org else ""
    readme = f"""# Assignment 1 - {label}

> **Template repository**. Submissions are created from this template
> via `dsl-course assign`{destination}.

## Instructions

*Replace this section with the assignment instructions.*

## Submission

Submit by pushing to your assigned repository before the deadline.

## Setup

```bash
git clone <your-repo-url>
cd <your-repo>
# follow setup instructions here
```
"""
    put_file(org, name, "README.md", readme.encode(), "init: assignment template")
    set_repo_topics(
        org,
        name,
        [
            f"cohort-{semester}",
            f"course-{_code_slug(course_code)}",
            "template",
        ],
    )
    log_ok(f"{name} created and marked as template")


def generate_website_from_template(
    org: str,
    website_repo: str,
    course_name: str,
) -> bool:
    """Create the website repo from the template via the Generate API."""
    template_owner, template_name = TEMPLATE_REPO.split("/")
    code, out = gh(
        "api",
        "--method",
        "POST",
        f"repos/{template_owner}/{template_name}/generate",
        "--field",
        f"owner={org}",
        "--field",
        f"name={website_repo}",
        "--field",
        "private=false",
        "--field",
        f"description=Course website - {course_name}",
        "--field",
        "include_all_branches=false",
        "-H",
        "Accept: application/vnd.github+json",
    )
    if code == 0:
        log_ok(f"website generated from template: {org}/{website_repo}")
        return True
    if "name already exists" in out.lower():
        log_ok(f"{website_repo} already exists - skipping generate")
        return True
    log_err(f"failed to generate website from template: {out[:200]}")
    return False


def render_website_semester_roster(
    org: str,
    website_repo: str,
    semester: str,
    course_name: str,
    course_code: str,
    instructor_logins: list[str],
) -> None:
    """Write semesters/{semester}/hertie-semester.yml in the website repo."""
    instructor_entries = (
        "\n".join(
            f'  - github: {login}\n    name: ""\n    email: ""'
            for login in instructor_logins
        )
        or "  []"
    )
    roster = f"""# Hertie DSL - Semester configuration for {semester_label(semester)}
# Auto-generated by dsl-course new-semester. Edit freely.
#
# Maps to GitHub teams in the course org:
#   instructors-{semester}  -> instructors + teaching_assistants
#   students-{semester}     -> students (typically managed by GitHub Classroom)
#   auditors-{semester}     -> auditors (read-only access to content)

semester: {semester}
org: {org}
course_code: {course_code}
course_name: "{course_name}"

instructors:
{instructor_entries}

teaching_assistants: []

auditors: []

students: []   # usually empty - GitHub Classroom manages enrolled students
"""
    put_file(
        org,
        website_repo,
        f"semesters/{semester}/hertie-semester.yml",
        roster.encode(),
        f"init: roster for {semester}",
    )


def render_website_config(
    org: str,
    website_repo: str,
    semester: str,
    course_name: str,
    course_code: str,
) -> None:
    """Patch _config.yml with course-specific values.

    The template ships with placeholders (course_name, course_semester,
    course_code, github_org, content_repo). We overwrite those exact keys.
    """
    current = get_file_content(org, website_repo, "_config.yml")
    if current is None:
        log_err(f"could not read _config.yml from {website_repo}")
        return

    label = semester_label(semester)
    substitutions = {
        'course_name: "Course Name (Code)"': f'course_name: "{course_name} ({course_code})"',
        'course_semester: "Fall 2025"': f'course_semester: "{label}"',
        'course_code: "GRAD-E1394"': f'course_code: "{course_code}"',
        'github_org: "Hertie-School-Deep-Learning-E1394"': f'github_org: "{org}"',
        (
            '# content_repo: "https://github.com/'
            'Hertie-School-Deep-Learning-E1394/content-f2025"'
        ): f'content_repo: "https://github.com/{org}/content-{semester}"',
    }
    # Check whether the _config.yml is already patched for this course
    # (idempotent rerun), otherwise look for the template placeholders.
    already_configured = (
        f'course_name: "{course_name} ({course_code})"' in current
        and f'github_org: "{org}"' in current
    )
    if already_configured:
        log_ok("_config.yml already configured for this course (skipping)")
        return

    updated = current
    missing = []
    for old, new in substitutions.items():
        if old in updated:
            updated = updated.replace(old, new)
        else:
            missing.append(old[:40])
    if missing:
        log_err(
            f"template placeholders not found in _config.yml: {missing}. "
            f"Template may have drifted - please update dsl_course/new_semester.py"
        )
        return

    if put_file(
        org,
        website_repo,
        "_config.yml",
        updated.encode(),
        f"init: set _config.yml for {semester}",
    ):
        log_ok("_config.yml patched for course")


def create_course_website(
    org: str,
    semester: str,
    course_name: str,
    course_code: str,
    instructor_logins: list[str],
) -> None:
    log_step(f"Creating course website for {org}")
    website_repo = org.lower() + ".github.io"

    if not generate_website_from_template(org, website_repo, course_name):
        return

    # Template generation is async — poll until _config.yml is readable
    # (the repo may appear before the initial commit is in place)
    for _ in range(20):
        code, _ = gh(
            "api",
            f"repos/{org}/{website_repo}/contents/_config.yml",
            "--jq",
            ".sha",
        )
        if code == 0:
            break
        time.sleep(2)
    else:
        log_err(
            f"{website_repo} _config.yml not readable after template generation — "
            f"rerun the command in a minute."
        )
        return

    render_website_config(org, website_repo, semester, course_name, course_code)
    render_website_semester_roster(
        org,
        website_repo,
        semester,
        course_name,
        course_code,
        instructor_logins,
    )
    # The template currently ships without Gemfile.lock so Bundler resolves
    # fresh on each build — just double-check it's gone from this repo.
    delete_file_if_exists(
        org, website_repo, "Gemfile.lock", "init: ensure fresh gem resolution"
    )
    enable_pages_actions(org, website_repo)


def delete_file_if_exists(
    org: str,
    repo: str,
    path: str,
    message: str,
) -> None:
    code, sha = gh(
        "api",
        f"repos/{org}/{repo}/contents/{path}",
        "--jq",
        ".sha",
    )
    if code != 0 or not sha:
        return
    gh(
        "api",
        "--method",
        "DELETE",
        f"repos/{org}/{repo}/contents/{path}",
        "--field",
        f"message={message}",
        "--field",
        f"sha={sha}",
    )


def enable_pages_actions(org: str, website_repo: str) -> None:
    """Enable GitHub Pages with the 'workflow' build type (Actions)."""
    code, out = gh(
        "api",
        "--method",
        "POST",
        f"repos/{org}/{website_repo}/pages",
        "--field",
        "build_type=workflow",
    )
    if code == 0:
        log_ok("Pages enabled (build type: GitHub Actions)")
        return
    if "already exists" in out.lower() or "409" in out:
        # Already enabled — make sure build type is set to workflow
        code, _ = gh(
            "api",
            "--method",
            "PUT",
            f"repos/{org}/{website_repo}/pages",
            "--field",
            "build_type=workflow",
        )
        if code == 0:
            log_ok("Pages already enabled (build type updated to Actions)")
        else:
            log_ok("Pages already enabled")
        return
    log_err(f"could not enable Pages automatically: {out[:200]}")
    log(
        f"  enable manually: https://github.com/{org}/{website_repo}/"
        f"settings/pages -> Source: GitHub Actions"
    )


def org_exists(org: str) -> bool:
    code, _ = gh("api", f"orgs/{org}")
    return code == 0


def print_checklist(org: str, satellite_org: str | None, semester: str) -> None:
    label = semester_label(semester)
    website = org.lower() + ".github.io"
    satellite_block = ""
    if satellite_org:
        if org_exists(satellite_org):
            satellite_block = f"""- Satellite org teams: students-{semester}, auditors-{semester}, instructors-{semester}
  -> https://github.com/{satellite_org}"""
        else:
            satellite_block = f"""- Satellite org `{satellite_org}` NOT FOUND.
  Create it at https://github.com/account/organizations/new
  (Free plan, add yourself as Owner), then rerun this command to seed its teams."""
    else:
        satellite_block = (
            "- No satellite org specified (--satellite-org). Assignments will land\n"
            f"  in the course org ({org}). Recommended: pass --satellite-org per ADR 0009."
        )

    log(f"""
============================================================
Semester setup complete: {label}

DONE (automated):
============================================================
- Course-org teams: instructors-{semester}, course-admin
- Content repo: https://github.com/{org}/content-{semester}
- Assignment template: https://github.com/{org}/assignment-1-{semester}
- Course website: https://github.com/{org}/{website}
- GitHub Pages enabled (deploy via Actions, site will be live shortly)
  -> https://{website}
{satellite_block}

NEXT STEPS (manual):
============================================================

1. Customise the course website:
   - _config.yml: add course_description
   - _data/people.yml: instructor photos + bios
   - schedule.md: weekly schedule
   - index.md: welcome text

2. Populate course materials in:
   https://github.com/{org}/content-{semester}

3. Create student submission repos (per ADR 0007/0009):
   python3 -m dsl_course.assign \\
     --org {satellite_org or org} --semester {semester} \\
     --assignment assignment-1 --template assignment-1-{semester}
   (The template lives in the course org; submissions land in the satellite.)

4. Add roster members via semesters/{semester}/hertie-semester.yml:
   https://github.com/{org}/{website}/blob/HEAD/semesters/{semester}/hertie-semester.yml
   (Sync runs weekly or on push — teams update automatically)

5. Optional: add sync workflow to the website repo for on-push sync
   (copy dsl_course/course-org-sync-template.yml)

============================================================
""")


def validate_org_bootstrap(org: str, satellite_org: str | None) -> bool:
    """Check that org and (if present) satellite org have DSL_BOT_TOKEN set."""
    orgs_to_check = [org]
    if satellite_org:
        orgs_to_check.append(satellite_org)

    log_step("Validating org bootstrap (DSL_BOT_TOKEN)")
    all_ok = True
    for check_org in orgs_to_check:
        code, _ = gh("api", f"orgs/{check_org}/actions/secrets/DSL_BOT_TOKEN")
        if code == 0:
            log_ok(f"{check_org}: DSL_BOT_TOKEN found")
        else:
            log_err(f"{check_org}: DSL_BOT_TOKEN missing")
            all_ok = False

    if not all_ok:
        log_err(
            "Bootstrap not complete. Run:\n"
            "  python3 -m dsl_course.bootstrap_course --org <org> --set-secret <path-to-token>"
        )
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True, help="Course org (materials live here)")
    parser.add_argument(
        "--satellite-org",
        default=None,
        help="Per-cohort satellite org (submissions live here). "
        "If not set, no satellite is seeded. "
        "If set and doesn't yet exist, you'll be prompted to create it.",
    )
    parser.add_argument("--semester", required=True, help="e.g. f2025 or s2026")
    parser.add_argument(
        "--course-name",
        required=True,
        help='Course name e.g. "Deep Learning"',
    )
    parser.add_argument(
        "--course-code",
        required=True,
        help="Hertie course code e.g. GRAD-E1394",
    )
    parser.add_argument(
        "--instructors",
        default="",
        help="Comma-separated GitHub logins",
    )
    parser.add_argument(
        "--tas",
        default="",
        help="Comma-separated GitHub logins for TAs",
    )
    parser.add_argument(
        "--content-visibility",
        default="private",
        choices=["public", "private"],
    )
    args = parser.parse_args()

    instructors = [i.strip() for i in args.instructors.split(",") if i.strip()]
    tas = [t.strip() for t in args.tas.split(",") if t.strip()]

    log(f"Setting up {args.org} for {semester_label(args.semester)}")
    log(f"Course: {args.course_name} ({args.course_code})")
    log(f"Instructors: {instructors}")
    log(f"TAs: {tas}")

    if not validate_org_bootstrap(args.org, args.satellite_org):
        return 1

    create_course_org_teams(args.org, args.semester, instructors, tas)
    create_content_repo(
        args.org,
        args.semester,
        args.course_code,
        public=(args.content_visibility == "public"),
    )
    create_assignment_template(
        args.org, args.semester, args.course_code, args.satellite_org
    )
    create_course_website(
        args.org,
        args.semester,
        args.course_name,
        args.course_code,
        instructors,
    )

    # Satellite org teams (only if the satellite exists)
    if args.satellite_org:
        if org_exists(args.satellite_org):
            create_satellite_teams(args.satellite_org, args.semester, instructors, tas)
        else:
            log_err(
                f"Satellite org {args.satellite_org} does not exist — "
                f"skipping satellite team creation. Create it via the web UI "
                f"then rerun."
            )

    print_checklist(args.org, args.satellite_org, args.semester)

    return 0


if __name__ == "__main__":
    sys.exit(main())
