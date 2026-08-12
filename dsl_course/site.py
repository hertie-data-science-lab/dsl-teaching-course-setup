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
  starting with `_`) and links to site-relative URLs. Every section the source repo has
  (`lectures`, `labs`, ... - discovered, not hardcoded) is hosted; `readings` is special,
  being either a text-only list (`reading-list`) or hosted+linked (`actual-readings`).
  Session materials only - no assignments/events. Opt-in: the first publish is a manual
  click, which persists its settings into the site repo (`_publish-config.yml`); the daily
  cron then re-syncs from those (`public-sync` with no source args).

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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import yaml

from . import schedule, seed
from .assign import assignment_slug
from .utils import (
    GIT_ENV,
    active_today,
    discover_sections,
    find_session_dir,
    gh,
    get_default_branch,
    get_file_content,
    git,
    log,
    log_err,
    session_number,
    log_ok,
    log_step,
    repo_exists,
)

# Public course site: served folder for the hosted section files, and the text-file
# extensions treated as the (publishable) reading list rather than copyrighted material.
PUBLIC_MATERIALS_DIR = "public-materials"
READING_LIST_EXTS = {".md", ".markdown", ".txt", ".bib"}
# The one section with copyright semantics of its own (--readings-mode); every OTHER
# section a repo happens to have is published as files, whatever it's called.
READINGS_SECTION = "readings"
# The settings of the last manual publish, committed into the site repo so the daily cron
# can re-sync unattended. Leading `_`, so Jekyll ignores it rather than serving it.
PUBLISH_CONFIG = "_publish-config.yml"
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


def _site_repo(org: str) -> str:
    """The GitHub Pages org site repo for an org - pushing it redeploys the site."""
    return f"{org.lower()}.github.io"


def _yaml_file(org: str, repo: str, path: str) -> dict:
    """A YAML config file from a repo as a mapping - `{}` when absent, empty or not a
    mapping (every caller here treats a malformed file as 'nothing declared')."""
    raw = get_file_content(org, repo, path) or ""
    data = yaml.safe_load(raw) if raw else {}
    return data if isinstance(data, dict) else {}


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
    """Declared people from a `people:` block - either the COURSE org's
    `.github/dsl-course.yml` (course site: instructors only, TAs are never declared
    there) or a cohort's own `classroom-config/people.yml` (cohort site: instructors
    AND TAs). Same schema either way.

    Returns `(instructors, teaching_assistants)` as lists of `(name, photo, url,
    title)` for entries active today (per optional start/end dates) that also declare
    a display `name`, or None when there is no `people:` block at all (then fall back
    to the GitHub teams). Schema (templates/course/people-header.yml +
    people-cards.yml for the course org's block, templates/classroom-config/people.yml
    for a cohort's):

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


def _people_yaml(org: str, meta: dict | None = None, *, include_tas: bool = True) -> str:
    """Build _data/people.yml. Prefer the declared `people:` block in the supplied meta
    (the course org's dsl-course.yml for the course site, a cohort's classroom-config/
    people.yml for the cohort site); else fall back to the GitHub `instructors` team of
    `org` (GitHub display name + avatar + profile link).

    `include_tas=False` (the course site) drops TA cards entirely - TAs are cohort-only,
    so the multi-year open-courseware site shows instructors only. Instructors and TAs
    share one GitHub team (there's no separate `teaching-assistants` team - see
    bootstrap_course.FACULTY_TEAMS), so the fallback can't distinguish TAs from
    instructors; declare a `people:` block to get separate TA cards."""
    override = _people_from_meta(meta or {})
    if override is not None:
        instructors, tas = override
        note = "declared in the `people:` block"
    else:
        instructors = [(*t, "") for t in _team_people(org, "instructors")]
        tas = []
        note = "auto-generated from the org's instructors team"
    if not include_tas:
        tas = []

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


@lru_cache(maxsize=None)
def _repo_tree(org: str, repo: str) -> tuple[str, tuple[str, ...]]:
    """(default branch, every blob path in it) for a repo - one recursive tree fetch,
    memoised for the run. A cohort site asks for the files of EVERY released session, and
    they nearly all live in the same repo, so without the memo the identical tree got
    fetched once per session. Paths come back sorted, so callers filtering them keep a
    stable diff. `()` when the tree can't be read (the caller then simply finds no files).

    Unbounded cache: this is a one-shot CLI process, and the trees it reads are the
    handful of repos one cohort released into."""
    branch = get_default_branch(org, repo)
    code, out = gh(
        "api",
        f"repos/{org}/{repo}/git/trees/{branch}?recursive=1",
        "--jq",
        '.tree[] | select(.type=="blob") | .path',
    )
    if code != 0:
        return branch, ()
    return branch, tuple(sorted(out.splitlines()))


def _session_files(org: str, repo: str, subpath: str, folder: str) -> list[tuple[str, str]]:
    """(name, blob-url) for every file at ANY depth under `folder` (already confirmed by
    seed.discover_release_sources to match a session's ordinal prefix), at `subpath`
    in a repo (or the repo root when `subpath` is empty - a release destination left
    at its default).

    Recursive, because a release copies a session folder wholesale (release.py's
    copytree), so `03_week-3/handouts/notes.pdf` is just as released as a file sitting
    directly in `03_week-3/` - a non-recursive listing would silently drop it from the
    site. Filters the repo's one memoised recursive tree (`_repo_tree`) client-side, so
    no API call per session or per subfolder; names are the path relative to the session
    folder, so nested files stay distinguishable, and the ordering is by path for a
    stable diff."""
    prefix = f"{subpath}/{folder}" if subpath else folder
    branch, paths = _repo_tree(org, repo)
    base = f"https://github.com/{org}/{repo}/blob/{branch}"
    return [
        (path[len(prefix) + 1 :], f"{base}/{quote(path)}")
        for path in paths
        if path.startswith(f"{prefix}/")
    ]


def _singular(label: str) -> str:
    """A section label as a single-item noun for a link name: 'lectures' -> 'lecture',
    'labs' -> 'lab', 'faq' -> 'faq'. Sections are free-form directory names, so a bare
    `[:-1]` chopped a real character off every label that isn't a plural ('faq' -> 'fa').
    Deliberately no inflection library: strip one trailing 's', else leave it alone."""
    return label[:-1] if len(label) > 1 and label.endswith("s") else label


def _iso_when(when: date | datetime, fallback_time: str = "09:00:00") -> str:
    """`when` as the offset-free local ISO stamp a front-matter `date:` wants.

    A datetime (a real time from schedule.yml) keeps its own clock time; a bare date (a
    synthesised fallback, or a whole-day schedule entry) gets `fallback_time`."""
    if isinstance(when, datetime):
        return when.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{when.isoformat()}T{fallback_time}"


def _links_block(sections: list[tuple[str, list[tuple[str, str]]]]) -> str:
    """A front-matter `links:` block from `(section-label, [(file-name, url), ...])` pairs
    in publication order, each link named `<section-singular> - <file>` (both sites label
    them identically), or `links: []` when there is nothing to link."""
    rows = []
    for label, pairs in sections:
        for name, url in pairs:
            safe = name.replace('"', "'")
            rows.append(f'    - url: {url}\n      name: "{_singular(label)} - {safe}"')
    return ("links:\n" + "\n".join(rows)) if rows else "links: []"


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
    links_block = _links_block(
        [
            (subpath or repo, _session_files(cohort_org, repo, subpath, folder))
            for repo, subpath, folder in sources
        ]
    )
    return (
        f"---\n"
        f"type: lecture\n"
        f"date: {_iso_when(when)}\n"
        f'title: "Session {session}"\n'
        f'tldr: "Released materials for session {session} (enrolled students only)."\n'
        f"{links_block}\n"
        f"---\n"
        f"Materials for session {session}. Open the links above (you must be an "
        f"enrolled member of `{cohort_org}`).\n"
    )


def _assignment_entry(course_org: str, repo: str, when: date | datetime) -> str:
    slug = assignment_slug(repo)
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
    # An unscheduled assignment's synthesised fallback date is due end-of-day.
    due = _iso_when(when, "23:59:00")
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


def _exam_entry(title: str, when: date | datetime) -> str:
    """A red exam row (the template's schedule_row_exam.html styles `type: exam`).

    `when` is a datetime when schedule.yml gave the exam a real start time, or a bare date
    (whole-day entry, or the synthesised mid/end-of-semester fallback) - which keeps the
    09:00 placeholder. Rendered offset-free, like `_assignment_entry`'s due time."""
    return (
        f"---\n"
        f"type: exam\n"
        f"date: {_iso_when(when)}\n"
        f'description: "{title}"\n'
        f"---\n"
        f"Details to be confirmed.\n"
    )


def _due_date(sched: schedule.Schedule, repo: str, fallback: date) -> date | datetime:
    """This assignment's due date from schedule.yml (keyed on the slug, repo minus its
    -fYYYY/-sYYYY tag), or `fallback` if unscheduled."""
    entry = sched.assignments.get(assignment_slug(repo))
    return entry.due if entry else fallback


def _session_dates(sched: schedule.Schedule) -> dict[str, datetime]:
    """Map a session ordinal (e.g. '2') to when that session HAPPENS - the entry's
    `calendar_event` from schedule.yml's `materials_releases`, keyed by the ordinal of
    each deploy's destination folder (so the site can date a released session from the
    plan that released it). Deploys may ship on their own `deploy_datetime` clocks; the
    site announces the class, not the copy. Earliest wins when several releases touch
    the same ordinal."""
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


def _raw_event_entry(release: schedule.Release) -> str:
    """A generic schedule row (the theme's schedule_row_raw_event.html) for a display-only
    entry - a `calendar_event` with no actions: a clinic, a guest lecture, a review
    session. Nothing is released; the site simply shows it."""
    title = (release.title or release.label.replace("-", " ").replace("_", " ").title())
    title = title.replace('"', "'")
    return (
        f"---\n"
        f"type: raw_event\n"
        f'name: "{title}"\n'
        f"date: {_iso_when(release.when, '09:00:00')}\n"
        f'description: ""\n'
        f"---\n"
    )


@dataclass
class _SitePlan:
    """What one sync wants its site repo to contain, handed back to `_sync_site_repo`.

    `config` are the `_config.yml` keys to overwrite (course identity); `collections` the
    collection dirs this sync OWNS, each cleared then rewritten from its `{filename:
    content}` (so an entry that is no longer generated - a de-released session, a template
    placeholder - disappears, and a collection the sync does not own is left alone);
    `files` every other tracked file to write, by repo-relative path (`_data/people.yml`,
    the publish config, ...); `commit` the commit subject; `label`/`done` the wording of
    this sync's log lines."""

    config: dict[str, str]
    collections: dict[str, dict[str, str]]
    commit: str
    files: dict[str, str] = field(default_factory=dict)
    label: str = "site"
    done: str = "synced + redeploying"


def _sync_site_repo(
    org: str,
    build: Callable[[Path], _SitePlan | None],
    *,
    scaffold_missing: bool = False,
) -> int:
    """The site-repo mechanics both syncs drive: ensure `<org>.github.io` exists, clone it,
    let `build` gather that sync's own data (writing into the working tree it is handed -
    the public site hosts files there) and declare a `_SitePlan`, apply the plan, then
    commit-if-changed and push. Pushing redeploys the site.

    `build` returns None to abort with exit 1, having logged its own reason. A missing site
    repo is a quiet no-op (a cohort that never opted into a site), unless
    `scaffold_missing` - the public course site's opt-in first publish, which creates it."""
    site = _site_repo(org)
    just_scaffolded = False
    if not repo_exists(org, site):
        if not scaffold_missing:
            log(f"  (no site repo {org}/{site} - skipping site sync)")
            return 0
        from . import scaffold

        log_step(f"No public site yet - scaffolding {org}/{site}")
        if scaffold.scaffold_site(org) != 0:
            return 1
        just_scaffolded = True

    with tempfile.TemporaryDirectory() as work:
        wd = Path(work) / "site"
        # A repo THIS run just created can lag its template-generate, so retry the clone;
        # an existing site repo either clones now or is a real failure.
        attempts = 6 if just_scaffolded else 1
        for attempt in range(attempts):
            if gh("repo", "clone", f"{org}/{site}", str(wd), "--", "-q")[0] == 0:
                break
            if attempt + 1 < attempts:
                time.sleep(5)
        else:
            log_err(f"could not clone {org}/{site}")
            return 1

        plan = build(wd)
        if plan is None:
            return 1

        # Course identity into _config.yml (site.course_name / _semester / _code).
        cfg_path = wd / "_config.yml"
        if cfg_path.is_file():
            cfg = cfg_path.read_text()
            for key, value in plan.config.items():
                cfg = _set_config(cfg, key, value)
            cfg_path.write_text(cfg)

        # Regenerate the owned collections; leave everything else (layouts, pages) as the
        # template provides.
        for coll, entries in plan.collections.items():
            d = wd / coll
            if d.is_dir():
                shutil.rmtree(d)
            d.mkdir(parents=True)
            (d / ".gitkeep").write_text("")
            for fname, content in entries.items():
                (d / fname).write_text(content)

        for rel, content in plan.files.items():
            (wd / rel).parent.mkdir(parents=True, exist_ok=True)
            (wd / rel).write_text(content)

        git("-C", str(wd), *_GIT_ENV, "add", "-A")
        code, _ = git(
            "-C", str(wd), *_GIT_ENV, "commit", "-q", "--no-verify", "-m", plan.commit
        )
        if code != 0:
            log_ok(f"{plan.label} already up to date")
            return 0
        if git("-C", str(wd), *_GIT_ENV, "push", "-q", "origin", "HEAD")[0] != 0:
            log_err(f"{plan.label} push failed")
            return 1
    log_ok(f"{plan.label} {plan.done} -> https://{site}/")
    return 0


def sync_site(course_org: str, cohort_org: str) -> int:
    """Regenerate the cohort's student-facing site from the live org state: released
    sessions (linked into the private content repos), this year's assignments and the
    exam rows."""

    def build(_wd: Path) -> _SitePlan:
        content_repos = seed.discover_cohort_repos([cohort_org])
        release_sources = seed.discover_release_sources(cohort_org, content_repos)
        sources_by_session: dict[str, list[tuple[str, str, str]]] = {}
        for repo, subpath, folder, n in release_sources:
            sources_by_session.setdefault(str(n), []).append((repo, subpath, folder))
        sessions = sorted(sources_by_session, key=int)
        assignments = seed.discover_assignments(course_org)
        # A persistent course org holds per-year templates (assignment-*-fYYYY); a cohort
        # site should list only its own year's, matched on the cohort's fYYYY/sYYYY tag.
        tag = _cohort_tag(cohort_org)
        if tag:
            assignments = [a for a in assignments if a.lower().endswith(tag)]
        log_step(
            f"Syncing {cohort_org}/{_site_repo(cohort_org)}: {len(sessions)} released "
            f"session(s), {len(assignments)} assignment(s)"
        )

        # Course identity comes from the course org metadata, semester from the cohort tag.
        meta = _yaml_file(course_org, ".github", "dsl-course.yml")
        # Schedule is cohort-specific (it varies by year), so it comes from the cohort's
        # own classroom-config/schedule.yml. So do this cohort's instructors/TAs - read
        # from its own classroom-config/people.yml below, NOT the course org (whose
        # dsl-course.yml carries only the multi-year instructor cards).
        sched = schedule.load(cohort_org)
        start = sched.semester_start or _semester_start(cohort_org)
        # Real per-session release datetimes from schedule.yml's materials_releases; a
        # session not in the plan falls back to a synthesised weekly date below.
        session_when = _session_dates(sched)

        config = {}
        if meta.get("course_name"):
            config["course_name"] = str(meta["course_name"])
        if _semester_label(cohort_org):
            config["course_semester"] = _semester_label(cohort_org)
        if meta.get("course_code"):
            config["course_code"] = str(meta["course_code"])
        # The footer's GitHub link (the site's only click-back). This is the COHORT site,
        # so it links the cohort org - where this year's materials and the students' own
        # repos live - never the course org (faculty-side) or the template's default.
        config["github_org"] = cohort_org

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
        # Display-only schedule rows: materials_releases entries with a when/event but no
        # actions (a clinic, a guest lecture). Nothing deploys; the site just shows them.
        exam_entries |= {
            f"ev-{_slug(r.label)}.md": _raw_event_entry(r)
            for r in sched.releases
            if r.is_event_only
        }

        return _SitePlan(
            config=config,
            # People: this cohort's own classroom-config/people.yml (instructors AND TAs -
            # the per-cohort teaching team; schema in
            # templates/classroom-config/people.yml), else its instructors team.
            files={
                "_data/people.yml": _people_yaml(
                    cohort_org, _yaml_file(cohort_org, "classroom-config", "people.yml")
                )
            },
            # Assignment due dates come from schedule.yml when set (keyed on the
            # assignment slug), else a synthesised fortnightly cadence.
            collections={
                "_lectures": {
                    f"session-{int(s):02d}.md": _lecture_entry(
                        cohort_org,
                        s,
                        session_when.get(s, start + timedelta(days=int(s) * 7)),
                        sources_by_session[s],
                    )
                    for s in sessions
                    if s.isdigit()
                },
                "_assignments": {
                    f"{i + 1:02d}-{a}.md": _assignment_entry(
                        course_org,
                        a,
                        _due_date(sched, a, start + timedelta(days=(i + 1) * 14)),
                    )
                    for i, a in enumerate(assignments)
                },
                "_events": exam_entries,
            },
            commit="site: sync from org structure",
        )

    return _sync_site_repo(cohort_org, build)


def _public_links(local_dir: Path, url_prefix: str) -> list[tuple[str, str]]:
    """(display-name, site-relative URL) for every file under a copied session folder.

    URLs are relative to the public site root (`/PUBLIC_MATERIALS_DIR/...`), so they
    resolve for the public - never blob/raw URLs into the private source repo. Names are
    the path relative to the session folder (so two nested `notes.pdf` stay
    distinguishable, as on the cohort site) and URL-encoded so spaces etc. survive."""
    out = []
    for p in sorted(local_dir.rglob("*")):
        if p.is_file():
            rel = p.relative_to(local_dir).as_posix()
            out.append((rel, f"{url_prefix}/{quote(rel)}"))
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
    section_links: list[tuple[str, list[tuple[str, str]]]],
    reading_list_md: str,
) -> str:
    """A public session entry: hosted links for every published section (whatever this
    repo's sections are - `lectures`, `labs`, ... - plus `readings` in actual-readings
    mode), plus the reading list as inline text when in reading-list mode. Public-facing
    body - no 'enrolled students only' gate.

    `section_links` is `(section, [(name, url), ...])` in publication order; each link is
    named `<section-singular> - <file>`, as on the cohort site."""
    links_block = _links_block(section_links)
    body = f"Materials for session {session}."
    if reading_list_md:
        body += "\n\n### Reading list\n\n" + reading_list_md
    return (
        f"---\n"
        f"type: lecture\n"
        f"date: {_iso_when(when)}\n"
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

    Opt-in: the first run scaffolds the site (Pages), later runs re-sync it. Every run
    records its settings in the site repo (`PUBLISH_CONFIG`) so the daily cron can repeat
    them unattended. Hosts the chosen `course-materials-*` repo's files - every section it
    actually has (see utils.discover_sections), plus, in `actual-readings` mode, `readings`
    - in the public site repo and links to them with site-relative URLs. `reading-list` mode
    publishes the citation text only. `include_lectures` toggles the file sections as a
    group (its name predates generic sections; the workflow input is unchanged). Session
    materials only - no assignments/events. Served files are namespaced per source repo
    so several years can coexist on one site."""
    if not include_lectures and readings_mode == "none":
        log_err("nothing to publish - file sections off and readings set to none.")
        return 1

    def build(site_wd: Path) -> _SitePlan | None:
        sessions = seed.discover_sessions(course_org, source_repo)
        log_step(
            f"Publishing {course_org}/{_site_repo(course_org)} from {source_repo}: "
            f"{len(sessions)} session(s), readings={readings_mode}, "
            f"file sections={'on' if include_lectures else 'off'}"
        )
        meta = _yaml_file(course_org, ".github", "dsl-course.yml")
        # A course site spans years and has no per-cohort schedule.yml to read (that's
        # cohort-scoped), so the date is a neutral fallback that only orders the session
        # entries.
        start = date(2025, 1, 1)

        # Wipe only THIS source's served subtree (idempotent re-publish; multi-repo safe).
        served_root = site_wd / PUBLIC_MATERIALS_DIR / source_repo
        if served_root.exists():
            shutil.rmtree(served_root)

        lecture_entries: dict[str, str] = {}
        with tempfile.TemporaryDirectory() as work:
            src, spec = Path(work) / "src", f"{course_org}/{source_repo}"
            if gh("repo", "clone", spec, str(src), "--", "-q")[0] != 0:
                log_err(f"could not clone {spec}")
                return None

            # Sections are whatever THIS repo has (the same discovery the release buttons
            # use), not a hardcoded lectures/readings pair - a course whose content lives
            # in `labs/` publishes labs. `readings` is the one section with special
            # semantics (--readings-mode, below); `include_lectures` gates all the others.
            file_sections = (
                [sec for sec in discover_sections(src) if sec != READINGS_SECTION]
                if include_lectures
                else []
            )
            log(f"  sections published as files: {', '.join(file_sections) or '(none)'}")

            for s in sessions:
                if not s.isdigit():
                    continue
                site_session = served_root / f"session-{s}"
                url_base = f"/{PUBLIC_MATERIALS_DIR}/{source_repo}/session-{s}"
                section_links: list[tuple[str, list[tuple[str, str]]]] = []
                reading_list_md = ""

                for section in file_sections:
                    sec_src = find_session_dir(src / section, s)
                    if sec_src is None:
                        continue
                    dest = site_session / section
                    shutil.copytree(sec_src, dest, dirs_exist_ok=True)
                    links = _public_links(dest, f"{url_base}/{section}")
                    if links:
                        section_links.append((section, links))

                read_src = find_session_dir(src / READINGS_SECTION, s)
                if read_src is not None:
                    if readings_mode == "actual-readings":
                        dest = site_session / READINGS_SECTION
                        shutil.copytree(read_src, dest, dirs_exist_ok=True)
                        links = _public_links(dest, f"{url_base}/{READINGS_SECTION}")
                        if links:
                            section_links.append((READINGS_SECTION, links))
                    elif readings_mode == "reading-list":
                        reading_list_md = _reading_list_md(read_src)

                # A session with nothing published in any section gets no page at all,
                # rather than an empty one the public would click through to.
                if not section_links and not reading_list_md:
                    log(f"  (session {s}: nothing to publish - no page)")
                    continue
                when = start + timedelta(days=int(s) * 7)
                lecture_entries[f"session-{int(s):02d}.md"] = _public_lecture_entry(
                    s, when, section_links, reading_list_md
                )

        config = {}
        if meta.get("course_name"):
            config["course_name"] = str(meta["course_name"])
        if meta.get("course_code"):
            config["course_code"] = str(meta["course_code"])
        config["course_semester"] = "Open Courseware"  # neutral: the site is multi-year
        # The public open-courseware site belongs to the COURSE org (multi-year), so its
        # footer links there - unlike a cohort site, which links its cohort org.
        config["github_org"] = course_org

        return _SitePlan(
            config=config,
            # Sessions only: regen _lectures, and clear _assignments/_events so any
            # template placeholders (and a previous run's content) stay off a public site.
            collections={
                "_lectures": lecture_entries,
                "_assignments": {},
                "_events": {},
            },
            files={
                # People from the course org's declared `people:` block (else the GitHub
                # teams). Instructors only - the open-courseware site is multi-year, and
                # TAs are declared per cohort (in each cohort's people.yml), never
                # course-level.
                "_data/people.yml": _people_yaml(course_org, meta, include_tas=False),
                # Persist the settings THIS publish used, in the site repo itself, so the
                # daily cron can repeat it with no inputs (see resync_public_site).
                PUBLISH_CONFIG: (
                    "# Written by `python3 -m dsl_course.site public-sync` - the settings of the\n"
                    "# last publish. The daily 'Publish course website' cron re-syncs from them;\n"
                    "# delete this file to stop the automatic refresh.\n"
                    f"source_repo: {source_repo}\n"
                    f"readings_mode: {readings_mode}\n"
                    f"include_lectures: {str(include_lectures).lower()}\n"
                ),
            },
            commit=f"site: publish public course site from {source_repo}",
            label="public site",
            done="published",
        )

    return _sync_site_repo(course_org, build, scaffold_missing=True)


def resync_public_site(course_org: str) -> int:
    """Re-publish the public course site from the settings the last publish persisted.

    The daily cron path: a materials edit then reaches the public site without anyone
    re-clicking the button. Opting in is still a deliberate manual publish, so a course org
    with no public site - or a site with no `PUBLISH_CONFIG` (published before this existed,
    or deliberately unhooked by deleting the file) - is a one-line no-op, NOT a failure:
    the cron ships in every course org's `.github`, and most never publish."""
    site = _site_repo(course_org)
    hint = "run the Publish course website action (or pass --source-repo) to publish"
    if not repo_exists(course_org, site):
        log(f"no public course site ({course_org}/{site}) - nothing to re-sync; {hint}")
        return 0
    raw = get_file_content(course_org, site, PUBLISH_CONFIG) or ""
    cfg = yaml.safe_load(raw) if raw.strip() else None
    if not isinstance(cfg, dict) or not cfg.get("source_repo"):
        log(f"no {PUBLISH_CONFIG} in {course_org}/{site} - nothing to re-sync; {hint}")
        return 0
    log_step(f"Re-syncing {course_org}/{site} from {PUBLISH_CONFIG}")
    return sync_public_site(
        course_org,
        str(cfg["source_repo"]),
        str(cfg.get("readings_mode") or "reading-list"),
        include_lectures=bool(cfg.get("include_lectures", True)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("sync")
    ps.add_argument("--course-org", required=True)
    ps.add_argument("--cohort-org", default=None, help="One cohort; omit with --all-cohorts")
    ps.add_argument(
        "--all-cohorts",
        action="store_true",
        help="Sync every registered cohort (a course-level change, e.g. dsl-course.yml)",
    )
    pp = sub.add_parser("public-sync")
    pp.add_argument("--course-org", required=True)
    pp.add_argument(
        "--source-repo",
        default=None,
        help="Course materials repo to publish; omit to re-sync from the settings the "
        f"last publish persisted in the site repo ({PUBLISH_CONFIG})",
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
        if not args.source_repo:
            return resync_public_site(args.course_org)
        return sync_public_site(
            args.course_org,
            args.source_repo,
            args.readings_mode,
            include_lectures=not args.no_include_lectures,
        )
    if args.all_cohorts:
        from .seed import discover_cohorts

        rc = 0
        for cohort in discover_cohorts(args.course_org):
            rc |= sync_site(args.course_org, cohort)
        return rc
    if not args.cohort_org:
        log_err("pass --cohort-org or --all-cohorts.")
        return 1
    return sync_site(args.course_org, args.cohort_org)


if __name__ == "__main__":
    sys.exit(main())
