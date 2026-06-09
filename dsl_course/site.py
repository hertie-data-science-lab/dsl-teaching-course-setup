"""dsl-course site -- regenerate a cohort website from the live org structure.

The cohort site (`<cohort>.github.io`, from course-website-template) renders Jekyll
collections: `_lectures/` and `_assignments/`. This module regenerates those entries
from what actually exists:

- **lectures** - one entry per released week in the cohort's `materials` repo
  (`lectures/week-N/`, `readings/week-N/`), linking to the released files;
- **assignments** - one entry per `assignment-*` template repo in the course org,
  with the assignment's README as the body.

So the site stops being placeholder content and tracks the real release state. Run after
each release (release/assign call it) or via the Sync site action. Pushing the site repo
redeploys it.

Usage:
    python3 -m dsl_course.site sync --course-org TEST-HERTIE-COURSE \\
        --cohort-org TEST-HERTIE-COHORT-f2026
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import yaml

from . import seed
from .utils import (
    gh,
    get_file_content,
    git,
    log,
    log_err,
    log_ok,
    log_step,
    repo_exists,
)

MATERIALS_REPO = "materials"
_GIT_ENV = [
    "-c",
    "user.email=bot@dsl.local",
    "-c",
    "user.name=dsl-bot",
    "-c",
    "core.hooksPath=/dev/null",
]


def _semester_start(cohort_org: str) -> date:
    """Best-effort semester start from a fYYYY / sYYYY tag (for schedule ordering)."""
    m = re.search(r"([fs])(\d{4})", cohort_org.lower())
    if m:
        season, year = m.group(1), int(m.group(2))
        return date(year, 9 if season == "f" else 2, 1)
    return date(2026, 1, 1)


def _semester_label(cohort_org: str) -> str:
    """fYYYY -> 'Fall YYYY', sYYYY -> 'Spring YYYY' (for site.course_semester)."""
    m = re.search(r"([fs])(\d{4})", cohort_org.lower())
    if m:
        return f"{'Fall' if m.group(1) == 'f' else 'Spring'} {m.group(2)}"
    return ""


def _q(value: str) -> str:
    """Quote-safe a value for a double-quoted YAML scalar."""
    return value.replace('"', "'")


def _set_config(text: str, key: str, value: str) -> str:
    """Replace a top-level `key: ...` line in _config.yml, preserving the rest."""
    return re.sub(
        rf"(?m)^({re.escape(key)}:\s*).*$", rf'\1"{_q(value)}"', text, count=1
    )


def _team_people(course_org: str, team: str) -> list[tuple[str, str, str]]:
    """(display-name, avatar-url, profile-url) for each member of a course-org team."""
    code, out = gh(
        "api",
        "--paginate",
        f"orgs/{course_org}/teams/{team}/members",
        "--jq",
        ".[].login",
    )
    if code != 0:
        return []
    people = []
    for login in out.splitlines():
        if not login.strip():
            continue
        c, u = gh(
            "api",
            f"users/{login}",
            "--jq",
            "[(.name // .login), .avatar_url, .html_url] | @tsv",
        )
        if c == 0 and u.strip():
            parts = (u.rstrip("\n").split("\t") + ["", "", ""])[:3]
            people.append(tuple(parts))
    return people


def _people_yaml(course_org: str) -> str:
    """Build _data/people.yml from the course org's instructors / teaching-assistants
    teams (GitHub display name + avatar as the photo + profile link)."""
    instructors = _team_people(course_org, "instructors")
    tas = _team_people(course_org, "teaching-assistants")

    def block(items: list[tuple[str, str, str]]) -> str:
        if not items:
            return " []"
        return "\n" + "\n".join(
            f'  - name: "{_q(n)}"\n    profile_pic: "{_q(p)}"\n    webpage: "{_q(w)}"'
            for n, p, w in items
        )

    featured = instructors[0] if instructors else ("Course staff", "", "")
    return (
        "# Auto-generated from the course org's teams by `dsl_course.site` - add people\n"
        "# to the instructors / teaching-assistants teams, then re-sync.\n\n"
        f'instructor:\n  name: "{_q(featured[0])}"\n'
        f'  profile_pic: "{_q(featured[1])}"\n  webpage: "{_q(featured[2])}"\n\n'
        f"instructors:{block(instructors)}\n\n"
        f"teaching_assistants:{block(tas)}\n"
    )


def _week_files(org: str, repo: str, section: str, week: str) -> list[tuple[str, str]]:
    """(name, blob-url) for each file under <section>/week-<week>/ in a repo."""
    code, out = gh(
        "api",
        f"repos/{org}/{repo}/contents/{section}/week-{week}",
        "--jq",
        '.[] | select(.type=="file") | .name + "\\t" + .html_url',
    )
    if code != 0:
        return []
    pairs = []
    for line in out.splitlines():
        if "\t" in line:
            name, url = line.split("\t", 1)
            pairs.append((name, url))
    return pairs


def _lecture_entry(cohort_org: str, week: str, when: date) -> str:
    links = []
    for section in ("lectures", "readings"):
        for name, url in _week_files(cohort_org, MATERIALS_REPO, section, week):
            safe = name.replace('"', "'")
            links.append(f'    - url: {url}\n      name: "{section[:-1]} - {safe}"')
    links_block = ("links:\n" + "\n".join(links)) if links else "links: []"
    return (
        f"---\n"
        f"type: lecture\n"
        f"date: {when.isoformat()}T09:00:00\n"
        f'title: "Week {week}"\n'
        f'tldr: "Released materials for week {week} (enrolled students only)."\n'
        f"{links_block}\n"
        f"---\n"
        f"Lectures and readings for week {week}. Open the links above (you must be an "
        f"enrolled member of `{cohort_org}`).\n"
    )


def _assignment_entry(course_org: str, repo: str, when: date) -> str:
    slug = re.sub(r"-[fs]\d{4}$", "", repo)
    readme = get_file_content(course_org, repo, "README.md") or ""
    title = slug.replace("-", " ").title()
    for line in readme.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    title = title.replace('"', "'")
    body = "\n".join(
        ln for ln in readme.splitlines() if not ln.startswith("# ")
    ).strip()
    due = f"{when.isoformat()}T23:59:00"
    return (
        f"---\n"
        f"type: assignment\n"
        f"date: {due}\n"
        f'title: "{title}"\n'
        f"due_event:\n"
        f"    type: due\n"
        f"    date: {due}\n"
        f'    description: "{title} due"\n'
        f"---\n"
        f"{body or 'Assignment brief.'}\n\n"
        f"_Your private `{slug}-<your-handle>` repo appears in `{course_org}`'s cohort "
        f"org once the teaching team provisions it._\n"
    )


def sync_site(course_org: str, cohort_org: str) -> int:
    site = f"{cohort_org.lower()}.github.io"
    if not repo_exists(cohort_org, site):
        log(f"  (no site repo {cohort_org}/{site} - skipping site sync)")
        return 0
    weeks = seed.discover_weeks(cohort_org, MATERIALS_REPO)
    assignments = seed.discover_assignments(course_org)
    log_step(
        f"Syncing {cohort_org}/{site}: {len(weeks)} released week(s), "
        f"{len(assignments)} assignment(s)"
    )
    start = _semester_start(cohort_org)

    with tempfile.TemporaryDirectory() as work:
        wd = Path(work) / "site"
        if gh("repo", "clone", f"{cohort_org}/{site}", str(wd), "--", "-q")[0] != 0:
            log_err(f"could not clone {cohort_org}/{site}")
            return 1

        # Course identity: pull name/code from the course org metadata, semester from the
        # cohort tag, into _config.yml (site.course_name / _semester / _code).
        meta_raw = get_file_content(course_org, ".github", "dsl-course.yml") or ""
        meta = yaml.safe_load(meta_raw) if meta_raw else {}
        cfg_path = wd / "_config.yml"
        if cfg_path.is_file() and isinstance(meta, dict):
            cfg = cfg_path.read_text()
            if meta.get("course_name"):
                cfg = _set_config(cfg, "course_name", str(meta["course_name"]))
            if _semester_label(cohort_org):
                cfg = _set_config(cfg, "course_semester", _semester_label(cohort_org))
            if meta.get("course_code"):
                cfg = _set_config(cfg, "course_code", str(meta["course_code"]))
            cfg_path.write_text(cfg)

        # People: regenerate _data/people.yml from the course org's teams.
        data_dir = wd / "_data"
        data_dir.mkdir(exist_ok=True)
        (data_dir / "people.yml").write_text(_people_yaml(course_org))

        # Regenerate the two generated collections; leave everything else (layouts,
        # _data, pages) as the template provides.
        for coll, gen in (
            (
                "_lectures",
                {
                    f"week-{int(w):02d}.md": _lecture_entry(
                        cohort_org, w, start + timedelta(days=(int(w) - 1) * 7)
                    )
                    for w in weeks
                    if w.isdigit()
                },
            ),
            (
                "_assignments",
                {
                    f"{i + 1:02d}-{a}.md": _assignment_entry(
                        course_org, a, start + timedelta(days=(i + 1) * 14)
                    )
                    for i, a in enumerate(assignments)
                },
            ),
        ):
            d = wd / coll
            if d.is_dir():
                shutil.rmtree(d)
            d.mkdir(parents=True)
            (d / ".gitkeep").write_text("")
            for fname, content in gen.items():
                (d / fname).write_text(content)

        git("-C", str(wd), *_GIT_ENV, "add", "-A")
        code, _ = git(
            "-C",
            str(wd),
            *_GIT_ENV,
            "commit",
            "-q",
            "--no-verify",
            "-m",
            "site: sync from org structure",
        )
        if code != 0:
            log_ok("site already up to date")
            return 0
        if git("-C", str(wd), *_GIT_ENV, "push", "-q", "origin", "HEAD")[0] != 0:
            log_err("site push failed")
            return 1
    log_ok(f"site synced + redeploying -> https://{cohort_org.lower()}.github.io/")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("sync")
    ps.add_argument("--course-org", required=True)
    ps.add_argument("--cohort-org", required=True)
    args = parser.parse_args()
    return sync_site(args.course_org, args.cohort_org)


if __name__ == "__main__":
    sys.exit(main())
