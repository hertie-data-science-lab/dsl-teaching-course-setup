"""dsl-course site -- regenerate a course/cohort website from the live org structure.

Two sites, two audiences, one Jekyll template (course-website-template):

- **cohort site** (`<cohort>.github.io`, `sync_site`) - student-facing. Its lecture links
  point at the cohort's PRIVATE `materials` repo, so they 404 for non-members (the gate is
  deliberate). Regenerates `_lectures/`, `_assignments/`, `_events/` from the release state.
  Releases call it; the Sync site action runs it on demand.

- **course site** (`<course-org>.github.io`, `sync_public_site`) - PUBLIC open courseware,
  opt-in. The course `course-materials-*` repos are private, so public links to them 404;
  instead this HOSTS the shared files in the public site repo (Jekyll serves any path not
  starting with `_`) and links to site-relative URLs. Lecture files are always hosted;
  readings are either a text-only list (`reading-list`) or hosted+linked (`actual-readings`).
  Lectures + readings only - no assignments/events. Button-only; never auto-synced.

Pushing the site repo redeploys it either way.

Usage:
    python3 -m dsl_course.site sync --course-org TEST-HERTIE-COURSE \\
        --cohort-org TEST-HERTIE-COHORT-f2026
    python3 -m dsl_course.site public-sync --course-org TEST-HERTIE-COURSE \\
        --source-repo course-materials-f2026 --readings-mode reading-list
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import yaml

from . import seed
from .utils import (
    GIT_ENV,
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
# Public course site: served folder for hosted lecture/reading files, and the text-file
# extensions treated as the (publishable) reading list rather than copyrighted material.
PUBLIC_MATERIALS_DIR = "public-materials"
READING_LIST_EXTS = {".md", ".markdown", ".txt", ".bib"}
_GIT_ENV = GIT_ENV


def _cohort_tag(cohort_org: str) -> str | None:
    """The fYYYY / sYYYY semester tag in a cohort org name (e.g. 'f2026'), or None."""
    m = re.search(r"[fs]\d{4}", cohort_org.lower())
    return m.group(0) if m else None


def _semester_start(cohort_org: str) -> date:
    """Best-effort semester start from a fYYYY / sYYYY tag (for schedule ordering)."""
    tag = _cohort_tag(cohort_org)
    if tag:
        return date(int(tag[1:]), 9 if tag[0] == "f" else 2, 1)
    return date(2026, 1, 1)


def _coerce_date(value: object) -> date | None:
    """A YAML date/datetime or an ISO `YYYY-MM-DD` string -> date (None if unparseable)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "exam"


def _schedule(
    meta: dict,
) -> tuple[date | None, dict[str, date], list[tuple[str, date]]]:
    """Faculty schedule overrides from a `.github/dsl-course.yml` `schedule:` block
    (the cohort's, for a cohort site).

    Returns `(semester_start, {assignment_slug: due_date}, [(exam_name, date), ...])`.
    Any missing/blank field falls back to the synthesised date at the call site, so the
    block is fully optional - a course with no `schedule:` behaves exactly as before.
    """
    sched = meta.get("schedule") if isinstance(meta, dict) else None
    sched = sched if isinstance(sched, dict) else {}
    start = _coerce_date(sched.get("semester_start"))
    due = {
        str(slug): d
        for slug, raw in (sched.get("assignments") or {}).items()
        if (d := _coerce_date(raw))
    }
    exams = [
        (str(e.get("name", "Exam")), d)
        for e in (sched.get("exams") or [])
        if isinstance(e, dict) and (d := _coerce_date(e.get("date")))
    ]
    return start, due, exams


def _semester_label(cohort_org: str) -> str:
    """fYYYY -> 'Fall YYYY', sYYYY -> 'Spring YYYY' (for site.course_semester)."""
    tag = _cohort_tag(cohort_org)
    return f"{'Fall' if tag[0] == 'f' else 'Spring'} {tag[1:]}" if tag else ""


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


def _people_from_meta(meta: dict) -> tuple[list[tuple], list[tuple]] | None:
    """Declared people from a `.github/dsl-course.yml` `people:` block (the cohort's,
    for a cohort site; the course org's for the public course site).

    The block is the canonical input for who appears on the site (name + photo + bio
    link + optional title), so cards carry institutional headshots/profiles rather than
    GitHub avatars. Returns `(instructors, teaching_assistants)` as lists of
    `(name, photo, url, title)`, or None when there is no `people:` block (then fall
    back to the GitHub teams). Schema:

        people:
          instructors:
            - {name: ..., photo: <img-url>, url: <bio-link>, title: ...}
          teaching_assistants:
            - {name: ..., photo: ..., url: ..., title: ...}
    """
    people = meta.get("people") if isinstance(meta, dict) else None
    if not isinstance(people, dict):
        return None

    def rows(key: str) -> list[tuple]:
        out = []
        for p in people.get(key) or []:
            if isinstance(p, dict) and p.get("name"):
                out.append(
                    (
                        str(p["name"]),
                        str(p.get("photo", "")),
                        str(p.get("url", "")),
                        str(p.get("title", "")),
                    )
                )
        return out

    return rows("instructors"), rows("teaching_assistants")


def _people_yaml(course_org: str, meta: dict | None = None) -> str:
    """Build _data/people.yml. Prefer the declared `people:` block in the supplied
    dsl-course.yml meta; else fall back to the GitHub instructors / teaching-assistants
    teams of `course_org` (GitHub display name + avatar + profile link)."""
    override = _people_from_meta(meta or {})
    if override is not None:
        instructors, tas = override
        note = "declared in the .github/dsl-course.yml `people:` block"
    else:
        instructors = [(*t, "") for t in _team_people(course_org, "instructors")]
        tas = [(*t, "") for t in _team_people(course_org, "teaching-assistants")]
        note = "auto-generated from the course org's instructors / teaching-assistants teams"

    def block(items: list[tuple]) -> str:
        if not items:
            return " []"
        rows = []
        for n, p, w, t in items:
            row = f'  - name: "{_q(n)}"\n    profile_pic: "{_q(p)}"\n    webpage: "{_q(w)}"'
            if t:
                row += f'\n    title: "{_q(t)}"'
            rows.append(row)
        return "\n" + "\n".join(rows)

    featured = instructors[0] if instructors else ("Course staff", "", "", "")
    return (
        f"# {note}.\n\n"
        f'instructor:\n  name: "{_q(featured[0])}"\n'
        f'  profile_pic: "{_q(featured[1])}"\n  webpage: "{_q(featured[2])}"\n\n'
        f"instructors:{block(instructors)}\n\n"
        f"teaching_assistants:{block(tas)}\n"
    )


def _week_files(org: str, repo: str, section: str, week: str) -> list[tuple[str, str]]:
    """(name, blob-url) for each file under <section>/week-<week>/ in a repo.

    discover_weeks reports the UNPADDED number (its regex tolerates `week-0*N`), so a
    zero-padded folder (`week-01`) would otherwise be queried here as `week-1` and 404 -
    the week appears on the schedule but its links come back empty. Try the padded name
    too, matching release._week_dir's tolerance, so the three readers stay in step.
    """
    folders = [f"week-{week}"]
    if week.isdigit():
        folders.append(f"week-{int(week):02d}")
    for folder in folders:
        code, out = gh(
            "api",
            f"repos/{org}/{repo}/contents/{section}/{folder}",
            "--jq",
            '.[] | select(.type=="file") | .name + "\\t" + .html_url',
        )
        if code != 0:
            continue
        pairs = []
        for line in out.splitlines():
            if "\t" in line:
                name, url = line.split("\t", 1)
                pairs.append((name, url))
        return pairs
    return []


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


def _exam_entry(title: str, when: date) -> str:
    """A red exam row (the template's schedule_row_exam.html styles `type: exam`)."""
    return (
        f"---\n"
        f"type: exam\n"
        f"date: {when.isoformat()}T09:00:00\n"
        f'description: "{title}"\n'
        f"---\n"
        f"Details to be confirmed.\n"
    )


def sync_site(course_org: str, cohort_org: str) -> int:
    site = f"{cohort_org.lower()}.github.io"
    if not repo_exists(cohort_org, site):
        log(f"  (no site repo {cohort_org}/{site} - skipping site sync)")
        return 0
    weeks = seed.discover_weeks(cohort_org, MATERIALS_REPO)
    assignments = seed.discover_assignments(course_org)
    # A persistent course org holds per-year templates (assignment-*-fYYYY); a cohort site
    # should list only its own year's, matched on the cohort's fYYYY/sYYYY tag.
    tag = _cohort_tag(cohort_org)
    if tag:
        assignments = [a for a in assignments if a.lower().endswith(tag)]
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
        meta = meta if isinstance(meta, dict) else {}
        # People + schedule are cohort-specific (they vary by year), so they come from the
        # cohort's own .github/dsl-course.yml, not the persistent course org's.
        cohort_raw = get_file_content(cohort_org, ".github", "dsl-course.yml") or ""
        cohort_meta = yaml.safe_load(cohort_raw) if cohort_raw else {}
        cohort_meta = cohort_meta if isinstance(cohort_meta, dict) else {}
        # Faculty schedule overrides (all optional; blanks keep the synthesised dates).
        sched_start, due_overrides, exam_overrides = _schedule(cohort_meta)
        if sched_start:
            start = sched_start
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

        # People: regenerate _data/people.yml from the cohort's declared `people:` block
        # (else fall back to the course org's instructors / teaching-assistants teams).
        data_dir = wd / "_data"
        data_dir.mkdir(exist_ok=True)
        (data_dir / "people.yml").write_text(_people_yaml(course_org, cohort_meta))

        # Exam rows render red via the template's schedule_row_exam.html. Use faculty
        # dates from the schedule block; else stub mid/end dates of a ~15-week semester.
        if exam_overrides:
            exam_entries = {
                f"{i + 1:02d}-{_slug(name)}.md": _exam_entry(name, when)
                for i, (name, when) in enumerate(exam_overrides)
            }
        else:
            exam_entries = {
                "midterm.md": _exam_entry("MidTerm Exam", start + timedelta(weeks=8)),
                "final.md": _exam_entry("Final Exam", start + timedelta(weeks=15)),
            }

        # Regenerate the generated collections; leave everything else (layouts, _data,
        # pages) as the template provides. Assignment due dates come from the schedule
        # block when set (keyed on the assignment slug), else a synthesised fortnightly
        # cadence.
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
                        course_org,
                        a,
                        due_overrides.get(
                            re.sub(r"-[fs]\d{4}$", "", a),
                            start + timedelta(days=(i + 1) * 14),
                        ),
                    )
                    for i, a in enumerate(assignments)
                },
            ),
            ("_events", exam_entries),
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


def _public_links(local_dir: Path, url_prefix: str) -> list[tuple[str, str]]:
    """(display-name, site-relative URL) for every file under a copied week folder.

    URLs are relative to the public site root (`/PUBLIC_MATERIALS_DIR/...`), so they
    resolve for the public - never blob/raw URLs into the private source repo. Names are
    URL-encoded so spaces etc. survive."""
    out = []
    for p in sorted(local_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(local_dir).as_posix()
            out.append((p.name, f"{url_prefix}/{quote(rel)}"))
    return out


def _reading_list_md(readings_week_dir: Path) -> str:
    """The readings rendered as TEXT for `reading-list` mode (no files hosted, no links).

    Text/citation files (`.md/.txt/.bib/.markdown`) are inlined verbatim - that is the
    faculty-written reading list. Any other file (a PDF, say) is listed by name only, so
    the public sees WHAT to read without the copyrighted bytes being published."""
    parts = []
    for p in sorted(readings_week_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() in READING_LIST_EXTS:
            text = p.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                parts.append(text)
        else:
            parts.append(f"- {p.name}")
    return "\n\n".join(parts)


def _public_lecture_entry(
    week: str,
    when: date,
    lecture_links: list[tuple[str, str]],
    reading_links: list[tuple[str, str]],
    reading_list_md: str,
) -> str:
    """A public week entry: hosted lecture (and, in actual-readings mode, reading) links,
    plus the reading list as inline text when in reading-list mode. Public-facing body -
    no 'enrolled students only' gate."""
    links = []
    for label, pairs in (("lecture", lecture_links), ("reading", reading_links)):
        for name, url in pairs:
            safe = name.replace('"', "'")
            links.append(f'    - url: {url}\n      name: "{label} - {safe}"')
    links_block = ("links:\n" + "\n".join(links)) if links else "links: []"
    body = f"Lecture materials and readings for week {week}."
    if reading_list_md:
        body += "\n\n### Reading list\n\n" + reading_list_md
    return (
        f"---\n"
        f"type: lecture\n"
        f"date: {when.isoformat()}T09:00:00\n"
        f'title: "Week {week}"\n'
        f'tldr: "Materials for week {week}."\n'
        f"{links_block}\n"
        f"---\n"
        f"{body}\n"
    )


def sync_public_site(
    course_org: str,
    source_repo: str,
    readings_mode: str = "reading-list",
    include_lectures: bool = True,
) -> int:
    """Build/refresh the PUBLIC course site `<course-org>.github.io` (open courseware).

    Opt-in + manual: the first run scaffolds the site (Pages), later runs re-sync it.
    Hosts the chosen `course-materials-*` repo's lecture files (and, in `actual-readings`
    mode, reading files) in the public site repo and links to them with site-relative
    URLs. `reading-list` mode publishes the citation text only. Lectures + readings only -
    no assignments/events. Served files are namespaced per source repo so several years
    can coexist on one site."""
    if not include_lectures and readings_mode == "none":
        log_err("nothing to publish - lectures off and readings set to none.")
        return 1

    site = f"{course_org.lower()}.github.io"
    if not repo_exists(course_org, site):
        from . import scaffold

        log_step(f"No public site yet - scaffolding {course_org}/{site}")
        if scaffold.scaffold_site(course_org) != 0:
            return 1

    # Local import: _week_dir padding tolerance, without a module-load import cycle.
    from . import release

    weeks = seed.discover_weeks(course_org, source_repo)
    log_step(
        f"Publishing {course_org}/{site} from {source_repo}: {len(weeks)} week(s), "
        f"readings={readings_mode}, lectures={'on' if include_lectures else 'off'}"
    )

    meta_raw = get_file_content(course_org, ".github", "dsl-course.yml") or ""
    meta = yaml.safe_load(meta_raw) if meta_raw else {}
    if not isinstance(meta, dict):
        meta = {}
    # Only the semester_start matters here (a course site has no per-cohort schedule);
    # reuse _schedule's parsing rather than re-deriving it. Neutral fallback - the site
    # spans years, so the date only orders the week entries.
    start = _schedule(meta)[0] or date(2025, 1, 1)

    with tempfile.TemporaryDirectory() as work:
        src, site_wd = Path(work) / "src", Path(work) / "site"
        if (
            gh("repo", "clone", f"{course_org}/{source_repo}", str(src), "--", "-q")[0]
            != 0
        ):
            log_err(f"could not clone {course_org}/{source_repo}")
            return 1
        # A just-generated site repo can lag the template-generate call, so retry the clone.
        for _ in range(6):
            if (
                gh("repo", "clone", f"{course_org}/{site}", str(site_wd), "--", "-q")[0]
                == 0
            ):
                break
            time.sleep(5)
        else:
            log_err(f"could not clone {course_org}/{site}")
            return 1

        # Wipe only THIS source's served subtree (idempotent re-publish; multi-repo safe).
        served_root = site_wd / PUBLIC_MATERIALS_DIR / source_repo
        if served_root.exists():
            shutil.rmtree(served_root)

        lecture_entries = {}
        for w in weeks:
            if not w.isdigit():
                continue
            site_week = served_root / f"week-{w}"
            url_base = f"/{PUBLIC_MATERIALS_DIR}/{source_repo}/week-{w}"
            lecture_links, reading_links, reading_list_md = [], [], ""

            if include_lectures:
                lec_src = release._week_dir(src / "lectures", w)
                if lec_src is not None:
                    dest = site_week / "lectures"
                    shutil.copytree(lec_src, dest, dirs_exist_ok=True)
                    lecture_links = _public_links(dest, f"{url_base}/lectures")

            read_src = release._week_dir(src / "readings", w)
            if read_src is not None:
                if readings_mode == "actual-readings":
                    dest = site_week / "readings"
                    shutil.copytree(read_src, dest, dirs_exist_ok=True)
                    reading_links = _public_links(dest, f"{url_base}/readings")
                elif readings_mode == "reading-list":
                    reading_list_md = _reading_list_md(read_src)

            when = start + timedelta(days=(int(w) - 1) * 7)
            lecture_entries[f"week-{int(w):02d}.md"] = _public_lecture_entry(
                w, when, lecture_links, reading_links, reading_list_md
            )

        # Course identity into _config.yml; semester is neutral (the site is multi-year).
        cfg_path = site_wd / "_config.yml"
        if cfg_path.is_file():
            cfg = cfg_path.read_text()
            if meta.get("course_name"):
                cfg = _set_config(cfg, "course_name", str(meta["course_name"]))
            if meta.get("course_code"):
                cfg = _set_config(cfg, "course_code", str(meta["course_code"]))
            cfg = _set_config(cfg, "course_semester", "Open Courseware")
            cfg_path.write_text(cfg)

        # People from the declared `people:` block (else the GitHub teams).
        data_dir = site_wd / "_data"
        data_dir.mkdir(exist_ok=True)
        (data_dir / "people.yml").write_text(_people_yaml(course_org, meta))

        # Lectures + readings only: regen _lectures, and clear _assignments/_events so any
        # template placeholders (and content from a previous run) don't appear publicly.
        for coll, gen in (
            ("_lectures", lecture_entries),
            ("_assignments", {}),
            ("_events", {}),
        ):
            d = site_wd / coll
            if d.is_dir():
                shutil.rmtree(d)
            d.mkdir(parents=True)
            (d / ".gitkeep").write_text("")
            for fname, content in gen.items():
                (d / fname).write_text(content)

        git("-C", str(site_wd), *_GIT_ENV, "add", "-A")
        code, _ = git(
            "-C",
            str(site_wd),
            *_GIT_ENV,
            "commit",
            "-q",
            "--no-verify",
            "-m",
            f"site: publish public course site from {source_repo}",
        )
        if code != 0:
            log_ok("public site already up to date")
            return 0
        if git("-C", str(site_wd), *_GIT_ENV, "push", "-q", "origin", "HEAD")[0] != 0:
            log_err("public site push failed")
            return 1
    log_ok(f"public site published -> https://{course_org.lower()}.github.io/")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("sync")
    ps.add_argument("--course-org", required=True)
    ps.add_argument("--cohort-org", required=True)
    pp = sub.add_parser("public-sync")
    pp.add_argument("--course-org", required=True)
    pp.add_argument(
        "--source-repo", required=True, help="Course materials repo to publish"
    )
    pp.add_argument(
        "--readings-mode",
        choices=["reading-list", "actual-readings", "none"],
        default="reading-list",
    )
    pp.add_argument(
        "--no-include-lectures", action="store_true", help="Skip lecture files"
    )
    args = parser.parse_args()
    if args.cmd == "public-sync":
        return sync_public_site(
            args.course_org,
            args.source_repo,
            args.readings_mode,
            include_lectures=not args.no_include_lectures,
        )
    return sync_site(args.course_org, args.cohort_org)


if __name__ == "__main__":
    sys.exit(main())
