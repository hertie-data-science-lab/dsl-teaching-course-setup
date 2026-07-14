"""dsl-course site -- regenerate a course/cohort website from the live org structure.

Two sites, two audiences, one Jekyll template (course-website-template):

- **cohort site** (`<cohort>.github.io`, `sync_site`) - student-facing. Its lecture links
  point at the cohort's PRIVATE content repos (wherever a release actually landed each
  section - see `seed.discover_release_sources`), so they 404 for non-members (the gate is
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

from . import schedule, seed
from .utils import (
    GIT_ENV,
    active_today,
    find_session_dir,
    gh,
    get_file_content,
    git,
    log,
    log_err,
    session_number,
    log_ok,
    log_step,
    repo_exists,
)

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


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "exam"


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
    """Declared people from the COURSE org's `.github/dsl-course.yml` `people:` block -
    the single source of truth for instructors/TAs, both for GitHub access
    (sync_faculty) and for website display (used for the cohort site AND the public
    course site).

    Returns `(instructors, teaching_assistants)` as lists of `(name, photo, url,
    title)` for entries active today (per optional start/end dates) that also declare
    a display `name`, or None when there is no `people:` block at all (then fall back
    to the GitHub teams). Schema (bootstrap_course._FACULTY_BLOCK):

        people:
          instructors:
            - {github_handle: ..., start: ..., end: ..., name: ..., photo: <img-url>, url: <bio-link>, title: ...}
          teaching_assistants:
            - {github_handle: ..., name: ..., photo: ..., url: ..., title: ...}
    """
    people = meta.get("people") if isinstance(meta, dict) else None
    if not isinstance(people, dict):
        return None
    today = date.today().isoformat()

    def rows(key: str) -> list[tuple]:
        out = []
        for p in people.get(key) or []:
            if not isinstance(p, dict) or not p.get("name"):
                continue
            if not active_today(p.get("start"), p.get("end"), today):
                continue
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
    dsl-course.yml meta; else fall back to the GitHub `instructors` team of
    `course_org` (GitHub display name + avatar + profile link).

    Instructors and TAs share that one GitHub team (there's no separate
    `teaching-assistants` team - see bootstrap_course.FACULTY_TEAMS), so the fallback
    can't distinguish TAs from instructors; declare a `people:` block to get separate
    TA cards."""
    override = _people_from_meta(meta or {})
    if override is not None:
        instructors, tas = override
        note = "declared in the .github/dsl-course.yml `people:` block"
    else:
        instructors = [(*t, "") for t in _team_people(course_org, "instructors")]
        tas = []
        note = "auto-generated from the course org's instructors team"

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


def _session_files(org: str, repo: str, subpath: str, folder: str) -> list[tuple[str, str]]:
    """(name, blob-url) for each file directly under `folder` (already confirmed by
    seed.discover_release_sources to match a session's ordinal prefix), at `subpath`
    in a repo (or the repo root when `subpath` is empty - a release destination left
    at its default)."""
    listing_path = f"{subpath}/{folder}" if subpath else folder
    code, out = gh(
        "api",
        f"repos/{org}/{repo}/contents/{listing_path}",
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


def _lecture_entry(
    cohort_org: str,
    session: str,
    when: date | datetime,
    sources: list[tuple[str, str, str]],
) -> str:
    """`sources` is (repo, subpath, folder) triples already confirmed (by
    seed.discover_release_sources) to hold this exact session - callers pass only the
    sources known to match, so every call here is a real hit, not a probe. `when` is the
    release datetime from schedule.yml (its real time is shown) or a synthesised date
    fallback (rendered at 09:00) when the session isn't in the release plan."""
    links = []
    for repo, subpath, folder in sources:
        label = subpath or repo
        for name, url in _session_files(cohort_org, repo, subpath, folder):
            safe = name.replace('"', "'")
            links.append(f'    - url: {url}\n      name: "{label[:-1]} - {safe}"')
    links_block = ("links:\n" + "\n".join(links)) if links else "links: []"
    date_str = (
        when.strftime("%Y-%m-%dT%H:%M:%S")
        if isinstance(when, datetime)
        else f"{when.isoformat()}T09:00:00"
    )
    return (
        f"---\n"
        f"type: lecture\n"
        f"date: {date_str}\n"
        f'title: "Session {session}"\n'
        f'tldr: "Released materials for session {session} (enrolled students only)."\n'
        f"{links_block}\n"
        f"---\n"
        f"Materials for session {session}. Open the links above (you must be an "
        f"enrolled member of `{cohort_org}`).\n"
    )


def _assignment_entry(course_org: str, repo: str, when: date | datetime) -> str:
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
    # `when` is a datetime (real due time from schedule.yml) or a bare date (synthesised
    # fallback) - render a stable, local (offset-free) ISO the site template can display.
    due = (
        when.strftime("%Y-%m-%dT%H:%M:%S")
        if isinstance(when, datetime)
        else f"{when.isoformat()}T23:59:00"
    )
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


def _due_date(sched: schedule.Schedule, repo: str, fallback: date) -> date | datetime:
    """This assignment's due date from schedule.yml (keyed on the slug, repo minus its
    -fYYYY/-sYYYY tag), or `fallback` if unscheduled."""
    entry = sched.assignments.get(re.sub(r"-[fs]\d{4}$", "", repo))
    return entry.due if entry else fallback


def _session_dates(sched: schedule.Schedule) -> dict[str, datetime]:
    """Map a session ordinal (e.g. '2') to its real release datetime from schedule.yml's
    `materials_releases`, keyed by the ordinal of each deploy's destination folder (so the
    site can date a released session from the plan that released it). Earliest wins when
    several releases touch the same ordinal."""
    out: dict[str, datetime] = {}
    for release in sched.releases:
        for d in release.deploy:
            folder = (d.dest_path or d.source_path).rstrip("/").rsplit("/", 1)[-1]
            n = session_number(folder)
            if n is None:
                continue
            key = str(n)
            if key not in out or release.when < out[key]:
                out[key] = release.when
    return out


def sync_site(course_org: str, cohort_org: str) -> int:
    site = f"{cohort_org.lower()}.github.io"
    if not repo_exists(cohort_org, site):
        log(f"  (no site repo {cohort_org}/{site} - skipping site sync)")
        return 0
    content_repos = seed.discover_cohort_repos([cohort_org])
    release_sources = seed.discover_release_sources(cohort_org, content_repos)
    sources_by_session: dict[str, list[tuple[str, str, str]]] = {}
    for repo, subpath, folder, n in release_sources:
        sources_by_session.setdefault(str(n), []).append((repo, subpath, folder))
    sessions = sorted(sources_by_session, key=int)
    assignments = seed.discover_assignments(course_org)
    # A persistent course org holds per-year templates (assignment-*-fYYYY); a cohort site
    # should list only its own year's, matched on the cohort's fYYYY/sYYYY tag.
    tag = _cohort_tag(cohort_org)
    if tag:
        assignments = [a for a in assignments if a.lower().endswith(tag)]
    log_step(
        f"Syncing {cohort_org}/{site}: {len(sessions)} released session(s), "
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
        # Schedule is cohort-specific (it varies by year), so it comes from the cohort's
        # own classroom-config/schedule.yml. People (instructors/TAs) no longer live
        # here - see the COURSE org's `meta` above, read by _people_yaml below.
        sched = schedule.load(cohort_org)
        if sched.semester_start:
            start = sched.semester_start
        # Real per-session release datetimes from schedule.yml's materials_releases; a
        # session not in the plan falls back to a synthesised weekly date below.
        session_when = _session_dates(sched)
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

        # People: regenerate _data/people.yml from the COURSE org's declared `people:`
        # block (instructors/TAs are the course org's SSOT, not per-cohort - see
        # bootstrap_course._FACULTY_BLOCK), else fall back to its instructors team.
        data_dir = wd / "_data"
        data_dir.mkdir(exist_ok=True)
        (data_dir / "people.yml").write_text(_people_yaml(course_org, meta))

        # Exam rows render red via the template's schedule_row_exam.html. Use faculty
        # dates from schedule.yml; else stub mid/end dates of a ~15-week semester
        # (bounded by semester_end when set).
        end = sched.semester_end or start + timedelta(weeks=15)
        if sched.exams:
            exam_entries = {
                f"{i + 1:02d}-{_slug(exam.name)}.md": _exam_entry(exam.name, exam.date)
                for i, exam in enumerate(sched.exams)
            }
        else:
            exam_entries = {
                "midterm.md": _exam_entry("MidTerm Exam", start + timedelta(weeks=8)),
                "final.md": _exam_entry("Final Exam", end),
            }

        # Regenerate the generated collections; leave everything else (layouts, _data,
        # pages) as the template provides. Assignment due dates come from schedule.yml
        # when set (keyed on the assignment slug), else a synthesised fortnightly cadence.
        for coll, gen in (
            (
                "_lectures",
                {
                    f"session-{int(s):02d}.md": _lecture_entry(
                        cohort_org,
                        s,
                        session_when.get(s, start + timedelta(days=int(s) * 7)),
                        sources_by_session[s],
                    )
                    for s in sessions
                    if s.isdigit()
                },
            ),
            (
                "_assignments",
                {
                    f"{i + 1:02d}-{a}.md": _assignment_entry(
                        course_org,
                        a,
                        _due_date(sched, a, start + timedelta(days=(i + 1) * 14)),
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
    """(display-name, site-relative URL) for every file under a copied session folder.

    URLs are relative to the public site root (`/PUBLIC_MATERIALS_DIR/...`), so they
    resolve for the public - never blob/raw URLs into the private source repo. Names are
    URL-encoded so spaces etc. survive."""
    out = []
    for p in sorted(local_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(local_dir).as_posix()
            out.append((p.name, f"{url_prefix}/{quote(rel)}"))
    return out


def _reading_list_md(readings_session_dir: Path) -> str:
    """The readings rendered as TEXT for `reading-list` mode (no files hosted, no links).

    Text/citation files (`.md/.txt/.bib/.markdown`) are inlined verbatim - that is the
    faculty-written reading list. Any other file (a PDF, say) is listed by name only, so
    the public sees WHAT to read without the copyrighted bytes being published."""
    parts = []
    for p in sorted(readings_session_dir.rglob("*")):
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
    session: str,
    when: date,
    lecture_links: list[tuple[str, str]],
    reading_links: list[tuple[str, str]],
    reading_list_md: str,
) -> str:
    """A public session entry: hosted lecture (and, in actual-readings mode, reading)
    links, plus the reading list as inline text when in reading-list mode. Public-facing
    body - no 'enrolled students only' gate."""
    links = []
    for label, pairs in (("lecture", lecture_links), ("reading", reading_links)):
        for name, url in pairs:
            safe = name.replace('"', "'")
            links.append(f'    - url: {url}\n      name: "{label} - {safe}"')
    links_block = ("links:\n" + "\n".join(links)) if links else "links: []"
    body = f"Lecture materials and readings for session {session}."
    if reading_list_md:
        body += "\n\n### Reading list\n\n" + reading_list_md
    return (
        f"---\n"
        f"type: lecture\n"
        f"date: {when.isoformat()}T09:00:00\n"
        f'title: "Session {session}"\n'
        f'tldr: "Materials for session {session}."\n'
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

    sessions = seed.discover_sessions(course_org, source_repo)
    log_step(
        f"Publishing {course_org}/{site} from {source_repo}: {len(sessions)} session(s), "
        f"readings={readings_mode}, lectures={'on' if include_lectures else 'off'}"
    )

    meta_raw = get_file_content(course_org, ".github", "dsl-course.yml") or ""
    meta = yaml.safe_load(meta_raw) if meta_raw else {}
    if not isinstance(meta, dict):
        meta = {}
    # A course site spans years and has no per-cohort schedule.yml to read (that's
    # cohort-scoped), so the date is a neutral fallback that only orders the session
    # entries.
    start = date(2025, 1, 1)

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
        for s in sessions:
            if not s.isdigit():
                continue
            site_session = served_root / f"session-{s}"
            url_base = f"/{PUBLIC_MATERIALS_DIR}/{source_repo}/session-{s}"
            lecture_links, reading_links, reading_list_md = [], [], ""

            if include_lectures:
                lec_src = find_session_dir(src / "lectures", s)
                if lec_src is not None:
                    dest = site_session / "lectures"
                    shutil.copytree(lec_src, dest, dirs_exist_ok=True)
                    lecture_links = _public_links(dest, f"{url_base}/lectures")

            read_src = find_session_dir(src / "readings", s)
            if read_src is not None:
                if readings_mode == "actual-readings":
                    dest = site_session / "readings"
                    shutil.copytree(read_src, dest, dirs_exist_ok=True)
                    reading_links = _public_links(dest, f"{url_base}/readings")
                elif readings_mode == "reading-list":
                    reading_list_md = _reading_list_md(read_src)

            when = start + timedelta(days=int(s) * 7)
            lecture_entries[f"session-{int(s):02d}.md"] = _public_lecture_entry(
                s, when, lecture_links, reading_links, reading_list_md
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
