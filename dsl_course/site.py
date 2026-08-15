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
from functools import cache
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
    get_default_branch,
    get_file_content,
    gh,
    git,
    is_missing_resource,
    load_yaml_config,
    log,
    log_err,
    log_ok,
    log_step,
    repo_exists,
    repo_tree,
    session_number,
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
    """Quote-safe a value for a ONE-LINE double-quoted YAML scalar: escape the two
    characters that are special inside one (`\\` and `"`), and fold newlines away - a
    multi-line value (a faculty `>` block in dsl-course.yml, say) would otherwise write a
    raw newline mid-scalar and break the file it lands in."""
    return " ".join(value.replace("\\", "\\\\").replace('"', "'").split())


def _liquid_raw(text: str) -> str:
    """Fence faculty-written text that is inlined verbatim into a Jekyll document. A `{{`
    or `{%` in it would otherwise run as Liquid, and a malformed tag fails the whole build;
    `{% raw %}` renders it literally."""
    return f"{{% raw %}}\n{text}\n{{% endraw %}}"


def _set_config(text: str, key: str, value: str) -> str:
    """Replace a top-level `key: ...` line in _config.yml, preserving the rest.

    The value is always written as a one-line double-quoted scalar (see `_q`). Any
    indented continuation lines are consumed with it, so replacing a key someone left as
    a `>`/`|` block scalar doesn't strand its body as invalid YAML.

    A key the template's `_config.yml` doesn't have is a no-op - logged, so template drift
    (a key the code sets that the site theme dropped) is visible rather than silent."""
    new, n = re.subn(
        rf"(?m)^({re.escape(key)}:[ \t]*).*(?:\n[ \t]+\S.*)*$",
        lambda m: f'{m.group(1)}"{_q(value)}"',
        text,
        count=1,
    )
    if n == 0:
        log(f"  (_config.yml has no `{key}:` key - not written; template drift?)")
    return new


def _site_repo(org: str) -> str:
    """The GitHub Pages org site repo for an org - pushing it redeploys the site."""
    return f"{org.lower()}.github.io"


def _yaml_file(org: str, repo: str, path: str) -> dict:
    """A YAML config file from a repo as a mapping - `{}` when it is genuinely absent or
    empty (nothing declared: the site renders its defaults, which is correct).

    A file that exists but does NOT parse - or parses to a list/scalar - raises out of
    here (via load_yaml_config), to the per-cohort isolation the callers already have. It
    used to be coerced to `{}`, so one bad indent in a cohort's people.yml republished the
    site with the whole teaching team's cards wiped, green - exactly the failure
    `_team_people` next door is hardened against."""
    return load_yaml_config(org, repo, path) or {}


def _team_people(course_org: str, team: str) -> list[tuple[str, str, str]]:
    """(display-name, avatar-url, profile-url) for each member of a course-org team.

    A missing team (404) is an empty list - the site falls back gracefully. Any OTHER
    failure RAISES rather than returning `[]`: a swallowed failure wrote `instructors: []`
    and republished the site with the whole teaching team wiped. Fail-loud, like
    get_team_members - and the same rule per MEMBER: a deleted account (404) is one card
    the site can't show, but a transient failure on one lookup must not quietly drop that
    instructor's card from the republished site."""
    code, out = gh(
        "api",
        "--paginate",
        f"orgs/{course_org}/teams/{team}/members",
        "--jq",
        ".[].login",
    )
    if code != 0:
        if is_missing_resource(out):
            return []  # no such team - fall back, don't wipe
        raise RuntimeError(
            f"could not read the members of {course_org}/{team}: {out[:200]}"
        )
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
        if c != 0:
            # A 404 is a genuinely gone account: one card fewer, said out loud rather than
            # silently. Anything else is a read failure, and dropping the card on it would
            # republish the site one instructor short with no sign anything went wrong.
            if is_missing_resource(u):
                log(f"  (no GitHub profile for {login} - no card on the site)")
                continue
            raise RuntimeError(
                f"could not read the GitHub profile of {login}: {u[:200]}"
            )
        if not u.strip():
            log(f"  (empty GitHub profile for {login} - no card on the site)")
            continue
        parts = (u.rstrip("\n").split("\t") + ["", "", ""])[:3]
        people.append(tuple(parts))
    return people


# A person entry mixes two concerns: who gets the GitHub grant, and what the website
# card shows. These keys drive the grant and are never rendered; everything else is
# display and is passed through to `_data/people.yml` as-is.
ACCESS_ONLY = ("github_handle", "start", "end")
# Our config spelling -> the key the Jekyll theme reads.
CARD_ALIASES = {"photo": "profile_pic", "url": "webpage"}
# Leading keys, so a generated file has a stable, readable order.
CARD_ORDER = ("name", "profile_pic", "webpage", "title")


def _card(entry: dict) -> dict:
    """One person entry -> the card dict written into `_data/people.yml`: drop the
    access-only keys, rename `photo`/`url` to the theme's names, keep everything else
    the course declared. Ordered by CARD_ORDER first, then the extras alphabetically."""
    card = {
        CARD_ALIASES.get(k, k): "" if v is None else str(v)
        for k, v in entry.items()
        if k not in ACCESS_ONLY
    }
    ordered = {k: card[k] for k in CARD_ORDER if k in card}
    ordered.update({k: card[k] for k in sorted(card) if k not in ordered})
    return ordered


def _people_from_meta(meta: dict) -> tuple[list[dict], list[dict]] | None:
    """Declared people from a `people:` block - either the COURSE org's
    `.github/dsl-course.yml` (course site: instructors only, TAs are never declared
    there) or a cohort's own `classroom-config/people.yml` (cohort site: instructors
    AND TAs). Same schema either way.

    Returns `(instructors, teaching_assistants)` as lists of **card dicts** keyed the way
    the Jekyll theme reads them, for entries active today (per optional start/end dates)
    that also declare a display `name`; or None when there is no `people:` block at all
    (then fall back to the GitHub teams). Schema (templates/course/people-header.yml +
    people-cards.yml for the course org's block, templates/classroom-config/people.yml
    for a cohort's):

        people:
          instructors:
            - github_handle: ...
              start: ...
              end: ...
              name: ...
              photo: <img-url>
              url: <bio-link>
              title: ...
          teaching_assistants:
            - github_handle: ...
              name: ...
              photo: ...
              url: ...
              title: ...

    Every declared field is passed through to the card: `photo`/`url` are renamed to the
    theme's `profile_pic`/`webpage`, ACCESS_ONLY keys are dropped (they govern the GitHub
    grant, not the display), and anything else a course chooses to add rides along
    verbatim, so a new field needs a theme change but no change here.
    """
    people = meta.get("people") if isinstance(meta, dict) else None
    if not isinstance(people, dict):
        return None
    today = date.today().isoformat()

    def rows(key: str) -> list[dict]:
        out = []
        for p in people.get(key) or []:
            if not isinstance(p, dict) or not p.get("name"):
                continue
            if not active_today(p.get("start"), p.get("end"), today):
                continue
            out.append(_card(p))
        return out

    return rows("instructors"), rows("teaching_assistants")


def _people_yaml(
    org: str, meta: dict | None = None, *, include_tas: bool = True
) -> str:
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
        instructors = [
            {"name": n, "profile_pic": p, "webpage": w}
            for n, p, w in _team_people(org, "instructors")
        ]
        tas = []
        note = "auto-generated from the org's instructors team"
    if not include_tas:
        tas = []

    def block(items: list[dict]) -> str:
        if not items:
            return " []"
        rows = []
        for card in items:
            # The theme's three core keys are always emitted, empty or not (a card the
            # theme can't find `profile_pic` on renders differently from one where it is
            # blank); optional fields appear only when they carry something.
            fields = [
                f'{k}: "{_q(card.get(k, ""))}"'
                for k in ("name", "profile_pic", "webpage")
            ] + [
                f'{k}: "{_q(v)}"'
                for k, v in card.items()
                if k not in ("name", "profile_pic", "webpage") and v != ""
            ]
            rows.append("  - " + "\n    ".join(fields))
        return "\n" + "\n".join(rows)

    featured = instructors[0] if instructors else {"name": "Course staff"}
    return (
        f"# {note}.\n\n"
        f'instructor:\n  name: "{_q(featured.get("name", ""))}"\n'
        f'  profile_pic: "{_q(featured.get("profile_pic", ""))}"\n'
        f'  webpage: "{_q(featured.get("webpage", ""))}"\n\n'
        f"instructors:{block(instructors)}\n\n"
        f"teaching_assistants:{block(tas)}\n"
    )


@cache
def _repo_tree(org: str, repo: str) -> tuple[str, tuple[str, ...]]:
    """(default branch, every blob path in it) for a repo - one recursive tree fetch,
    memoised for the run. A cohort site asks for the files of EVERY released session, and
    they nearly all live in the same repo, so without the memo the identical tree got
    fetched once per session. Paths come back sorted, so callers filtering them keep a
    stable diff.

    Unbounded cache: this is a one-shot CLI process, and the trees it reads are the
    handful of repos one cohort released into.

    The fetch itself is utils.repo_tree (shared with discovery's directory-side twin, so
    the absent-vs-failed discrimination is written once): a genuinely absent/empty tree is
    `()` and the caller simply finds no files, while any other failure RAISES rather than
    reporting an empty tree - swallowed, it republished the site with every material link
    stripped."""
    branch = get_default_branch(org, repo)
    return branch, repo_tree(org, repo, branch, "blob")


def _session_files(
    org: str, repo: str, subpath: str, folder: str
) -> list[tuple[str, str]]:
    """(name, blob-url) for every file at ANY depth under `folder` (already confirmed by
    seed.discover_release_sources to match a session's ordinal prefix), at `subpath`
    in a repo (or the repo root when `subpath` is empty - a release destination left
    at its default).

    Recursive, because a release copies a session folder wholesale (deploy's
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


# A week's lecture and its lab are two separate rows of the theme's schedule table, and
# the labs page selects `type: lab` out of the `_lectures` collection - so which row a
# released folder lands in is decided by its section (the directory it was released into),
# never by anything faculty declare. Everything that isn't `labs` is lecture material.
LAB_SECTION = "labs"
_ROW_NOUN = {"lecture": "Session", "lab": "Lab"}


def _row_kind(section: str) -> str:
    """The schedule-row type a released section belongs to: 'lab' or 'lecture'."""
    return "lab" if section == LAB_SECTION else "lecture"


def _row_file(session: str, kind: str) -> str:
    """The collection filename for one session row - lecture and lab rows of the same
    week are distinct files (`session-02.md`, `lab-02.md`) in the same collection."""
    return f"{'lab' if kind == 'lab' else 'session'}-{int(session):02d}.md"


def _singular(label: str) -> str:
    """A section label as a single-item noun for a link name: 'lectures' -> 'lecture',
    'labs' -> 'lab', 'faq' -> 'faq'. Sections are free-form directory names, so a bare
    `[:-1]` chopped a real character off every label that isn't a plural ('faq' -> 'fa').
    Deliberately no inflection library: strip one trailing 's', else leave it alone."""
    return label[:-1] if len(label) > 1 and label.endswith("s") else label


def _iso_when(when: date | datetime, fallback_time: str = "09:00:00") -> str:
    """`when` as the offset-free local ISO stamp a front-matter `date:` wants.

    A datetime from schedule.yml is ALREADY in the cohort timezone - the parser converts
    an entry written with an explicit offset (`...T10:00+00:00`) into the cohort's own
    clock - so printing it needs no conversion here, only the offset dropped. A bare date
    (a synthesised fallback, or a whole-day schedule entry) has no clock and gets
    `fallback_time`."""
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
            # Route the name through _q (escapes `\` AND `"`): a filename with a backslash
            # (`\sigma.pdf`) is an invalid YAML escape and fails the whole Jekyll build.
            safe = _q(f"{_singular(label)} - {name}")
            rows.append(f'    - url: {url}\n      name: "{safe}"')
    return ("links:\n" + "\n".join(rows)) if rows else "links: []"


def _lecture_entry(
    cohort_org: str,
    session: str,
    when: date | datetime,
    sources: list[tuple[str, str, str]],
    kind: str = "lecture",
) -> str:
    """One row of a teaching week: the lecture (`kind='lecture'`) or the lab
    (`kind='lab'`), which the theme renders as separate schedule lines out of the same
    `_lectures` collection.

    `sources` is (repo, subpath, folder) triples already confirmed (by
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
    title = f"{_ROW_NOUN[kind]} {session}"
    return (
        f"---\n"
        f"type: {kind}\n"
        f"date: {_iso_when(when)}\n"
        f'title: "{title}"\n'
        f'tldr: "Released materials for {title.lower()} (enrolled students only)."\n'
        f"{links_block}\n"
        f"---\n"
        f"Materials for {title.lower()}. Open the links above (you must be an "
        f"enrolled member of `{cohort_org}`).\n"
    )


def _assignment_entry(
    course_org: str,
    repo: str,
    when: date | datetime,
    handout: datetime | None = None,
    sched: schedule.Schedule | None = None,
) -> str:
    """An assignment's page, plus the two schedule rows it drives: the entry's own
    `date:` is the "released!" row and its `due_event:` sub-block the due row.

    `when` is the due date (a real one from schedule.yml, or a synthesised fallback);
    `handout` the scheduled provisioning moment when there is one. A handout dates the
    released-row where it belongs - at hand-out, not at the deadline - while an
    unscheduled assignment keeps both rows on the due date (the only date known).

    `sched` supplies the cohort-side repo name: resolved exactly as assign.py / collect.py
    do (`cohort_dest_repo` or the schedule slug when the schedule keys this repo, else the
    course repo minus its -fYYYY/-sYYYY tag), so the page names the repo students actually
    get. Deriving it from the course repo alone named the wrong repo - and titled the page
    wrong - whenever an entry set `cohort_dest_repo`."""
    found = schedule.entry_for_repo(sched, repo) if sched is not None else None
    slug = schedule.cohort_name(*found) if found else assignment_slug(repo)
    readme = get_file_content(course_org, repo, "README.md") or ""
    title = slug.replace("-", " ").title()
    for line in readme.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    title = _q(title)
    body = "\n".join(
        ln for ln in readme.splitlines() if not ln.startswith("# ")
    ).strip()
    # An unscheduled assignment's synthesised fallback date is due end-of-day.
    due = _iso_when(when, "23:59:00")
    released = _iso_when(handout) if handout is not None else due
    return (
        f"---\n"
        f"type: assignment\n"
        f"date: {released}\n"
        f'title: "{title}"\n'
        f"due_event:\n"
        f"    type: due\n"
        f"    date: {due}\n"
        f'    description: "{title}"\n'
        f"---\n"
        f"{_liquid_raw(body or 'Assignment brief.')}\n\n"
        f"_Your private `{slug}-<your-handle>` repo appears in `{course_org}`'s cohort "
        f"org once the teaching team provisions it._\n"
    )


def _exam_entry(
    title: str,
    when: date | datetime,
    tbc: bool = False,
    dateless: bool = False,
) -> str:
    """A red exam row (the template's schedule_row_exam.html styles `type: exam`).

    `when` is a datetime when schedule.yml gave the exam a real start time, or a bare date
    (whole-day entry, or the synthesised mid/end-of-semester fallback) - which keeps the
    09:00 placeholder.

    TBC: an undated exam (`date: tbc`) still needs a sortable date for the theme, so the
    caller passes end-of-term as `when` with `dateless=True` - the theme then prints
    "TBC" instead; `tbc=True` with a real date adds the "(TBC)" marker."""
    flags = ""
    if tbc or dateless:
        flags = "tbc: true\n" + ("dateless: true\n" if dateless else "")
    return (
        f"---\n"
        f"type: exam\n"
        f"date: {_iso_when(when)}\n"
        f"{flags}"
        f'description: "{_q(title)}"\n'
        f"---\n"
        f"Details to be confirmed.\n"
    )


def _assignment_dates(
    sched: schedule.Schedule, repo: str, fallback: date
) -> tuple[date | datetime, datetime | None]:
    """(due, handout) for an assignment from schedule.yml (keyed on the slug, repo minus
    its -fYYYY/-sYYYY tag). An unscheduled assignment is due on `fallback` and has no
    handout; a scheduled one has a handout only when the plan pins (or the manual release
    button recorded) one."""
    found = schedule.entry_for_repo(sched, repo)
    entry = found[1] if found else None
    if entry is None:
        return fallback, None
    return entry.due_datetime, entry.handout_datetime


def _deploy_section(deploy: schedule.Deploy) -> str:
    """The section a deploy lands in - the top-level directory of its destination path,
    or the destination repo itself when the path is a bare session folder (a release into
    a repo that IS one section). The same `subpath or repo` shape discovery reports for
    an already-released folder, so both sides classify a row the same way."""
    dest = (deploy.cohort_dest_path or deploy.course_source_path).strip("/")
    head, sep, _ = dest.partition("/")
    return head if sep else deploy.cohort_dest_repo


def _session_dates(sched: schedule.Schedule) -> dict[tuple[str, str], datetime]:
    """Map a session row - (ordinal, 'lecture'|'lab') - to when that session HAPPENS: the
    entry's `event_datetime` from schedule.yml's `releases`, keyed by the ordinal and
    section of each deploy's destination folder (so the site can date a released row from
    the plan that released it). Keying on the row, not the week, is what lets Wednesday's
    lab carry its own time rather than inheriting Monday's lecture. Deploys may ship on
    their own `deploy_datetime` clocks; the site announces the class, not the copy.
    Earliest wins when several releases touch the same row."""
    out: dict[tuple[str, str], datetime] = {}
    for release in sched.releases:
        if release.when is None:
            continue  # event_datetime: tbc - undated, can't place a session
        for d in release.deploy:
            folder = (
                (d.cohort_dest_path or d.course_source_path)
                .rstrip("/")
                .rsplit("/", 1)[-1]
            )
            n = session_number(folder)
            if n is None:
                continue
            key = (str(n), _row_kind(_deploy_section(d)))
            if key not in out or release.when < out[key]:
                out[key] = release.when
    return out


def _pretty(label: str) -> str:
    """A schedule label as a display name, for an entry that declared no title."""
    return label.replace("-", " ").replace("_", " ").title()


def _special_event_entry(
    title: str,
    when: date | datetime,
    tbc: bool = False,
    dateless: bool = False,
) -> str:
    """A generic schedule row (the theme's schedule_row_special_event.html) for a
    display-only entry: a clinic, a guest lecture, a review session. Nothing is released;
    the site simply shows it.

    TBC: an undated entry (`event_datetime: tbc`) still needs a sortable `date:` for the
    theme, so the caller passes end-of-term as `when` plus `dateless=True` - the theme
    then prints "TBC" instead of the placeholder. A dated entry with `tbc=True` keeps its
    date and gains a "(TBC)" marker."""
    flags = ""
    if tbc or dateless:
        flags = "tbc: true\n" + ("dateless: true\n" if dateless else "")
    return (
        f"---\n"
        f"type: special_event\n"
        f'name: "{_q(title)}"\n'
        f"date: {_iso_when(when)}\n"
        f"{flags}"
        f'description: ""\n'
        f"---\n"
    )


def _event_entry(event: schedule.Event, fallback: date) -> str:
    """One `events:` row, rendered as the type it declared - an exam or a special event.
    An event with no title of its own falls back to its prettified label, and an undated
    one (`event_datetime: tbc`) sorts at `fallback` (end of term) as a dateless row."""
    render = _exam_entry if event.type == "exam" else _special_event_entry
    return render(
        event.title or _pretty(event.label),
        event.when if event.when is not None else fallback,
        event.tbc,
        event.when is None,
    )


def _term_date_entry(name: str, when: date) -> str:
    """A semester-boundary row (the theme's schedule_row_term_date.html). `name` fills the
    row's event column and is the only text it shows, so the description stays empty;
    `hide_time` suppresses the placeholder clock time - a term boundary is a whole day,
    not a 09:00 appointment."""
    return (
        f"---\n"
        f"type: term_date\n"
        f"date: {_iso_when(when)}\n"
        f"hide_time: true\n"
        f'name: "{_q(name)}"\n'
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

        # Course identity into _config.yml (course_name / _semester / _code /
        # _description, github_org) - only the keys the plan declares, nothing else.
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
    lecture and lab rows (linked into the private content repos), this year's assignments,
    and the display-only rows of the schedule (exams, special events, term dates)."""

    def build(_wd: Path) -> _SitePlan:
        content_repos = seed.discover_cohort_repos([cohort_org])
        release_sources = seed.discover_release_sources(cohort_org, content_repos)
        # One row per (ordinal, kind): a week's lecture materials and its lab are separate
        # rows on the schedule, so a lab released into `labs/` never folds into the
        # lecture's row (and never shows up twice, on the schedule and the labs page).
        sources_by_row: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
        for repo, subpath, folder, n in release_sources:
            key = (str(n), _row_kind(subpath or repo))
            sources_by_row.setdefault(key, []).append((repo, subpath, folder))
        rows = sorted(sources_by_row, key=lambda k: (int(k[0]), k[1]))
        assignments = seed.discover_assignments(course_org)
        # A persistent course org holds per-year templates (assignment-*-fYYYY); a cohort
        # site should list only its own year's, matched on the cohort's fYYYY/sYYYY tag.
        tag = _cohort_tag(cohort_org)
        if tag:
            assignments = [a for a in assignments if a.lower().endswith(tag)]
        log_step(
            f"Syncing {cohort_org}/{_site_repo(cohort_org)}: {len(rows)} released "
            f"session row(s), {len(assignments)} assignment(s)"
        )

        # Course identity comes from the course org metadata, semester from the cohort tag.
        meta = _yaml_file(course_org, ".github", "dsl-course.yml")
        # Schedule is cohort-specific (it varies by year), so it comes from the cohort's
        # own classroom-config/schedule.yml. So do this cohort's instructors/TAs - read
        # from its own classroom-config/people.yml below, NOT the course org (whose
        # dsl-course.yml carries only the multi-year instructor cards).
        sched = schedule.load(cohort_org)
        # Every datetime on `sched` is already the cohort's wall clock (the parser converts
        # a written offset into the cohort timezone), so the renderers below just print it.
        start = sched.semester_start or _semester_start(cohort_org)
        # Real per-row release datetimes from schedule.yml's releases; a row not in the
        # plan falls back to a synthesised weekly date below.
        session_when = _session_dates(sched)

        config = {}
        if meta.get("course_name"):
            config["course_name"] = str(meta["course_name"])
        if _semester_label(cohort_org):
            config["course_semester"] = _semester_label(cohort_org)
        if meta.get("course_code"):
            config["course_code"] = str(meta["course_code"])
        # The site's blurb. Declared once in the course org's dsl-course.yml and pushed to
        # every cohort site; left as the site repo has it when the course doesn't declare
        # one. Written as a single line whatever the source shape (see _q).
        if meta.get("course_description"):
            config["course_description"] = str(meta["course_description"])
        # The footer's GitHub link (the site's only click-back). This is the COHORT site,
        # so it links the cohort org - where this year's materials and the students' own
        # repos live - never the course org (faculty-side) or the template's default.
        config["github_org"] = cohort_org

        # The display-only half of the schedule. `events:` rows render as what they
        # declared (exam or special event); an undated (TBC) one sorts at end-of-term.
        end = sched.semester_end or start + timedelta(weeks=15)
        event_entries = {
            f"{i + 1:02d}-{_slug(e.label)}.md": _event_entry(e, end)
            for i, e in enumerate(sched.events)
        }
        # Every course has exams, so a schedule that names none still gets stub mid/end
        # dates of a ~15-week semester (bounded by semester_end when set) - a placeholder
        # faculty replace, rather than a schedule page with no exams on it at all.
        if not any(e.type == "exam" for e in sched.events):
            event_entries |= {
                "midterm.md": _exam_entry("MidTerm Exam", start + timedelta(weeks=8)),
                "final.md": _exam_entry("Final Exam", end),
            }
        # The term's own boundaries, when the schedule pins them.
        if sched.semester_start:
            event_entries["term-start.md"] = _term_date_entry(
                "Term starts", sched.semester_start
            )
        if sched.semester_end:
            event_entries["term-end.md"] = _term_date_entry(
                "Term ends", sched.semester_end
            )

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
            # Assignment handout/due dates come from schedule.yml when set (keyed on the
            # assignment slug), else a synthesised fortnightly cadence.
            collections={
                "_lectures": {
                    _row_file(s, kind): _lecture_entry(
                        cohort_org,
                        s,
                        session_when.get((s, kind), start + timedelta(days=int(s) * 7)),
                        sources_by_row[(s, kind)],
                        kind,
                    )
                    for s, kind in rows
                },
                "_assignments": {
                    f"{i + 1:02d}-{a}.md": _assignment_entry(
                        course_org,
                        a,
                        *_assignment_dates(
                            sched, a, start + timedelta(days=(i + 1) * 14)
                        ),
                        sched=sched,
                    )
                    for i, a in enumerate(assignments)
                },
                "_events": event_entries,
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
    kind: str = "lecture",
) -> str:
    """A public session entry: hosted links for every published section (whatever this
    repo's sections are - `lectures`, `faq`, ... - plus `readings` in actual-readings
    mode), plus the reading list as inline text when in reading-list mode. Public-facing
    body - no 'enrolled students only' gate. The week's `labs` section is a `lab` row of
    its own (`kind`), exactly as on the cohort site.

    `section_links` is `(section, [(name, url), ...])` in publication order; each link is
    named `<section-singular> - <file>`, as on the cohort site."""
    links_block = _links_block(section_links)
    title = f"{_ROW_NOUN[kind]} {session}"
    body = f"Materials for {title.lower()}."
    if reading_list_md:
        body += "\n\n### Reading list\n\n" + _liquid_raw(reading_list_md)
    return (
        f"---\n"
        f"type: {kind}\n"
        f"date: {_iso_when(when)}\n"
        f'title: "{title}"\n'
        f'tldr: "Materials for {title.lower()}."\n'
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
            log(
                f"  sections published as files: {', '.join(file_sections) or '(none)'}"
            )

            for s in sessions:
                if not s.isdigit():
                    continue
                site_session = served_root / f"session-{s}"
                url_base = f"/{PUBLIC_MATERIALS_DIR}/{source_repo}/session-{s}"
                # Links per row: the week's `labs` section becomes its own lab row,
                # everything else (lectures, faq, readings) the session row.
                section_links: list[tuple[str, list[tuple[str, str]]]] = []
                lab_links: list[tuple[str, list[tuple[str, str]]]] = []
                reading_list_md = ""

                for section in file_sections:
                    sec_src = find_session_dir(src / section, s)
                    if sec_src is None:
                        continue
                    dest = site_session / section
                    shutil.copytree(sec_src, dest, dirs_exist_ok=True)
                    links = _public_links(dest, f"{url_base}/{section}")
                    if links:
                        rows = (
                            lab_links if _row_kind(section) == "lab" else section_links
                        )
                        rows.append((section, links))

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

                # A row with nothing published gets no page at all, rather than an empty
                # one the public would click through to.
                if not section_links and not lab_links and not reading_list_md:
                    log(f"  (session {s}: nothing to publish - no page)")
                    continue
                when = start + timedelta(days=int(s) * 7)
                if section_links or reading_list_md:
                    lecture_entries[_row_file(s, "lecture")] = _public_lecture_entry(
                        s, when, section_links, reading_list_md
                    )
                if lab_links:
                    lecture_entries[_row_file(s, "lab")] = _public_lecture_entry(
                        s, when, lab_links, "", "lab"
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
    ps.add_argument(
        "--cohort-org", default=None, help="One cohort; omit with --all-cohorts"
    )
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
    if args.cmd != "public-sync" and not (args.all_cohorts or args.cohort_org):
        log_err("pass --cohort-org or --all-cohorts.")
        return 1
    # A read helper that couldn't reach the API raises RuntimeError; a config file with
    # one bad indent raises yaml.YAMLError out of load_yaml_config (people.yml is
    # web-editable, so faculty author that fault directly). In an Actions log a one-line
    # error beats a traceback either way, and the run still goes red.
    try:
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
                # One cohort's raised failure (an unreachable API, a people.yml that
                # doesn't parse) must not skip every LATER cohort's site on the 06:00
                # cron - log it, mark the batch failed, and carry on. The same per-cohort
                # isolation PR #151/#146 applied to the nightly refresh and the scheduler.
                try:
                    rc |= sync_site(args.course_org, cohort)
                except Exception as exc:
                    log_err(
                        f"site sync for {cohort} failed ({type(exc).__name__}): {exc}"
                    )
                    rc |= 1  # accumulate, don't clobber prior cohorts' status bits
            return rc
        # --cohort-org arrives on the automatic path straight from a repository_dispatch's
        # `client_payload.cohort_org`, written by whoever holds a cohort's DSL_BOT_TOKEN - a
        # lower trust tier than the course org. Naming SOMEONE ELSE'S cohort would rebuild
        # that cohort's site from this dispatch. The registry is the authority on which
        # cohorts this course org owns, so an unregistered name is refused. Checked here
        # rather than inside sync_site, because every internal caller (a release, the
        # scheduler, the --all-cohorts loop above) already passes a cohort it read FROM the
        # registry - only the CLI takes one from outside. Casefold: GitHub org names are
        # case-insensitive.
        registered = seed.discover_cohorts(args.course_org)
        if registered and args.cohort_org.casefold() not in {
            c.casefold() for c in registered
        }:
            log_err(
                f"{args.cohort_org} is not registered under {args.course_org} "
                f"({seed.COHORTS_PATH} lists {', '.join(sorted(registered))}) - refusing "
                f"to sync its site."
            )
            return 1
        return sync_site(args.course_org, args.cohort_org)
    except (RuntimeError, yaml.YAMLError) as exc:
        log_err(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
