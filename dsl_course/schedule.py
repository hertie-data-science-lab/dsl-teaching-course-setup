"""dsl-course schedule -- the per-cohort classroom-config/schedule.yml, this cohort's
single home for the timed release plan AND the dates other tools display/enforce:

Each block encodes a BEHAVIOUR: `releases` deploy materials, `assignments` have a
lifecycle, `events` are display-only calendar rows.

    timezone: Europe/Berlin          # optional (default Europe/Berlin) - how naive times
                                     # below are interpreted; GitHub cron itself is UTC
    releases:                        # the auto-release plan - label ->
      lecture_02:                    # {event_datetime + deploys}. Each deploy ships at its
        event_datetime: 2026-09-15T10:00   # deploy_datetime (default: the event itself).
        deploy:                            # Labels are free identifiers.
          - course_source_repo: course-materials-f2026   # course_source_repo + course_source_path
            course_source_path: lectures/02_intro        # are the only required keys;
            cohort_dest_repo: materials                  # cohort_dest_repo, cohort_dest_path
            cohort_dest_path: lectures/02_intro          # and deploy_datetime are optional.
            deploy_datetime: 2026-09-15T09:00
    assignments:                     # each assignment's whole lifecycle. The slug is a
      assignment-1:                  # label; course_source_repo names the COURSE-org repo
        course_source_repo: assignment-1-f2026   # it hands out from, and is REQUIRED.
        handout_datetime: 2026-09-22T09:00  # A bare due_datetime is END of day (23:59:59)
        due_datetime: 2026-10-13     # - "due on the 13th" closes at day's end.
        grading_datetime: 2026-10-15 # Snapshot freezes + autograder fires (default: due).
    events:                          # display-only rows - nothing deploys, the site just
      mid-term:                      # shows them. `type` is `exam` or `special_event`
        type: exam                   # (the default when omitted).
        title: MidTerm Exam          # `event_datetime` is a whole day, or a full datetime
        event_datetime: 2026-11-03   # when the start time is known.
      project-clinic:
        title: Project Clinic
        event_datetime: 2026-10-14T10:00
    semester_start: 2026-09-07
    semester_end: 2026-12-18

Every field is optional - a cohort with no schedule.yml (or a blank one) behaves exactly
as before everywhere that reads it (releases are skipped, dates synthesised).

Times are timezone-aware: a naive datetime/date is interpreted in `timezone`; an explicit
offset (e.g. `...T14:00+02:00`) is honoured as written.

Parsing is total but never silent: an entry that is valid YAML yet not a valid schedule
entry (a typo'd key, a missing date) is dropped so the rest of the term still parses, and
recorded in `Schedule.dropped` for `load` to log, `--validate` to fail on, and Check cohort setup
to count.

Usage:
    python3 -m dsl_course.schedule --cohort-org Deep-Learning-EXAMPLE-f2026
    python3 -m dsl_course.schedule --cohort-org Deep-Learning-EXAMPLE-f2026 --validate
    python3 -m dsl_course.schedule --file classroom-config/schedule.yml --validate
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .utils import coerce_date, get_file_content, log_err

CONFIG_REPO = "classroom-config"
SCHEDULE_PATH = "schedule.yml"
DEFAULT_TZ = "Europe/Berlin"


# --------------------------------------------------------------------------- pure core


def _tz(name: str | None) -> ZoneInfo:
    """Resolve a timezone name, falling back to the default if it's missing/unknown."""
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


# The date-level coercion (semester bounds, whole-day events) is the shared canonical one
# in utils - `active_today` uses the same, so the two can never drift. Aliased under the
# module's historical private name for its internal callers (and the tests that pin it).
_coerce_date = coerce_date


def _coerce_datetime(
    value: object, tz: ZoneInfo, *, end_of_day: bool = False
) -> datetime | None:
    """A YAML datetime/date or ISO string -> a timezone-aware datetime (None if
    unparseable). A bare date has no time, so it becomes start-of-day (00:00) or, when
    `end_of_day`, 23:59:59. A naive datetime is stamped with `tz`; one that already
    carries an offset keeps it."""

    def _from_date(d: date) -> datetime:
        return datetime.combine(d, time(23, 59, 59) if end_of_day else time(0, 0))

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):  # bare YAML date (no time component)
        dt = _from_date(value)
    elif isinstance(value, str):
        s = value.strip()
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            d = _coerce_date(s)
            if d is None:
                return None
            dt = _from_date(d)
        else:
            # A date-only string parses to 00:00 - honour end_of_day for it too.
            if end_of_day and "T" not in s and ":" not in s:
                dt = _from_date(dt.date())
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def _coerce_date_or_datetime(value: object, tz: ZoneInfo) -> date | datetime | None:
    """A whole-day value -> `date`; one that carries a time -> a tz-aware `datetime`
    (coerced exactly like a release `when`: naive is stamped with `tz`, an explicit offset
    is kept). Keeping the two distinct is what lets a reader tell "no time was given" from
    "midnight" - the website renders a placeholder time for the former."""
    if isinstance(value, datetime) or (
        isinstance(value, str) and ("T" in value or ":" in value)
    ):
        return _coerce_datetime(value, tz)
    return _coerce_date(value)


def _instant(value: date | datetime, tz: ZoneInfo) -> datetime:
    """A sortable tz-aware instant for a value that may be whole-day or timed. Mixing the
    two in one list is otherwise unsortable (`date` and `datetime` don't compare, nor do
    naive and aware ones); a whole-day value sorts at the start of its day in `tz`."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=tz)
    return datetime.combine(value, time(0, 0), tzinfo=tz)


@dataclass
class Deploy:
    """One source->dest copy: a path in a COURSE-org source repo copied into a COHORT-org
    dest repo. `cohort_dest_path` defaults to `course_source_path` (mirror).

    `deploy_datetime` optionally overrides the copy's own ship time; unset, it ships at
    the parent entry's `event_datetime`. This is what disaggregates the class from its
    materials: the entry's `event_datetime` is the session the site announces, a deploy's
    `deploy_datetime` ships the files an hour (or a week) before or after it."""

    course_source_repo: str
    course_source_path: str
    cohort_dest_repo: str = "materials"
    cohort_dest_path: str | None = None
    deploy_datetime: datetime | None = None


@dataclass
class Release:
    """A labelled scheduled entry: when the thing HAPPENS (`event_datetime` in the YAML),
    plus, optionally, `deploy` actions (content copies) - or an `assignment` handout
    synthesised by the scheduler from `assignments.<slug>.handout_datetime`.

    `when` holds the entry's `event_datetime`: what the cohort site's schedule shows AND
    the default fire time for its deploys. An individual deploy may carry its own
    `deploy_datetime` to ship earlier or later than the session it belongs to. An entry
    with no actions at all is inert: it fires nothing and the site shows nothing - a row
    with nothing to release belongs in `events:`."""

    label: str
    # None = the event_datetime is literally `tbc`: the site shows a TBC row and nothing
    # can fire until faculty replace it with a real date.
    when: datetime | None
    deploy: list[Deploy] = field(default_factory=list)
    assignment: str | None = None
    title: str = ""  # display-only: overrides the prettified label on the site
    # `tbc: true` next to a REAL date = a provisional sketch: everything fires at that
    # date as normal, but the site marks it "(TBC)" to signal it may still move.
    tbc: bool = False

    @property
    def is_event_only(self) -> bool:
        """No actions - nothing to fire, and nothing for the site to show."""
        return not self.deploy and not self.assignment

    def due_deploys(self, now: datetime) -> list[Deploy]:
        """The deploys whose own ship time (`deploy_datetime`, else this entry's
        `event_datetime`) has arrived. An undated (TBC) entry's deploys can never be due -
        except one carrying its own explicit `deploy_datetime`."""
        return [
            d
            for d in self.deploy
            if (d.deploy_datetime or self.when) is not None
            and (d.deploy_datetime or self.when) <= now
        ]


@dataclass
class AssignmentEntry:
    """One assignment's whole lifecycle, in one place: `handout_datetime` (when
    student/team repos are provisioned), `due_datetime` (what students see),
    `grading_datetime` (when the snapshot freezes and the autograder fires), `type` and
    `max_team_size` (group assignments)."""

    due_datetime: datetime
    # The COURSE-org repo this assignment hands out from - the template one repo per
    # student (or per team) is generated from. Required and named outright: it used to be
    # derived as `<slug>-<cohort tag>`, which was right almost always and invisible in the
    # file that depended on it. Same meaning as a deploy's `course_source_repo`.
    course_source_repo: str
    # What the COHORT-side artefacts are called - the frozen cohort template repo, the
    # `<name>-<handle>` student repos, the teams.csv key, the snapshot and grades files.
    # None = the entry's slug, which is almost always right. Mirrors a deploy's
    # `cohort_dest_repo`: source names the course side, dest names the cohort side.
    cohort_dest_repo: str | None = None
    grading_datetime: datetime | None = None  # explicit pin; defaults to due_datetime
    # When to provision one repo per student (or per team - see `type`) from the
    # `<slug>-<tag>` template. The scheduler synthesises a release from this, so it fires
    # exactly like a `releases` entry. None = hand out manually (the button
    # then records the release moment here).
    handout_datetime: datetime | None = None
    # 'group' | 'individual' | None. The COHORT-level declaration of how this assignment
    # fans out; when set it wins over the template's own grading.yml `type:` (the
    # design-time fallback). None = defer to grading.yml (then individual).
    type: str | None = None
    # Group assignments: the team-size cap the welcome repo's "Join team" flow enforces
    # (templates/welcome/team-formation.yml reads it straight from schedule.yml; its
    # default when unset lives there). None = not set here.
    max_team_size: int | None = None


@dataclass
class Event:
    """A display-only calendar row: an exam, or any other session the cohort should see
    on the schedule but which releases nothing (a guest lecture, a project clinic).
    Nothing here ever fires - the site renders the row and that is all."""

    label: str
    title: str
    # A bare date = whole day; a datetime = real start time; None = `event_datetime: tbc`
    # (the site shows a TBC row). `tbc: true` next to a real date = provisional, "(TBC)".
    when: date | datetime | None
    # 'exam' | 'special_event'. Exams render as their own (red) row on the site.
    type: str = "special_event"
    tbc: bool = False


@dataclass
class Schedule:
    timezone: str = DEFAULT_TZ
    releases: list[Release] = field(default_factory=list)
    semester_start: date | None = None
    semester_end: date | None = None
    assignments: dict[str, AssignmentEntry] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    # Every entry this parse threw away, one human-readable line each, naming the YAML
    # path and what it costs the cohort. A malformed entry can't be rescued - it has no
    # date, or no source - but it must never vanish quietly: `load` logs each of these,
    # `--validate` exits non-zero on them, and Check cohort setup counts them. See `_drop`.
    dropped: list[str] = field(default_factory=list)


def _drop(drops: list[str], where: str, why: str, cost: str) -> None:
    """Record a thrown-away entry: where it is in the YAML, what is wrong, and what the
    cohort loses by it. The cost is the point - "entry dropped" alone tells faculty
    nothing about whether their term still runs."""
    drops.append(f"{where}: {why} - entry dropped, so {cost}")


def _require_mapping(
    raw: object, drops: list[str], block: str, noun: str, cost: str
) -> dict | None:
    """A top-level `releases:`/`assignments:`/`events:` block must be a `label -> entry`
    mapping. Returns it, or None when it is absent (nothing to parse) or authored as a
    list/scalar - the latter recorded as a drop rather than left to raise on `.items()`,
    which would break `load`'s never-raise contract (a list is the common mistake, since
    `deploy:` nested below IS a list)."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        _drop(
            drops,
            block,
            f"not a mapping (it must be {noun} -> entry, not a list or value)",
            cost,
        )
        return None
    return raw


# The keys each schema level understands. Anything else - a typo (`grading_dateime:`), a
# legacy name (`dest_repo:`), or a whole plan under an unknown top-level key
# (`materials_releases:`) - is silently ignored by the parser and so means something other
# than what faculty wrote; `_flag_unknown_keys` surfaces it so `--validate` catches it.
KNOWN_TOP_LEVEL = frozenset(
    {"timezone", "releases", "semester_start", "semester_end", "assignments", "events"}
)
KNOWN_RELEASE = frozenset({"event_datetime", "deploy", "assignment", "title", "tbc"})
KNOWN_DEPLOY = frozenset(
    {
        "course_source_repo",
        "course_source_path",
        "cohort_dest_repo",
        "cohort_dest_path",
        "deploy_datetime",
    }
)
KNOWN_ASSIGNMENT = frozenset(
    {
        "due_datetime",
        "course_source_repo",
        "cohort_dest_repo",
        "grading_datetime",
        "handout_datetime",
        "type",
        "max_team_size",
    }
)
KNOWN_EVENT = frozenset({"type", "title", "event_datetime", "tbc"})


def _flag_unknown_keys(
    drops: list[str], entry: dict, known: frozenset[str], where: str, cost: str
) -> None:
    """Record every key of `entry` not in `known`. Unlike `_drop`, the entry itself is
    KEPT (only the stray key is ignored) - a typo'd or legacy key otherwise passes
    validation while silently changing what the file means. Only called for entries that
    parse; a dropped entry already gets its own line."""
    for key in entry:
        if str(key) not in known:
            loc = f"{where}.{key}" if where else str(key)
            drops.append(f"{loc}: unrecognised key - ignored, so {cost}")


def _parse_deploy(
    raw: object, tz: ZoneInfo, drops: list[str], label: str
) -> list[Deploy]:
    """Parse a release's `deploy:` - a list (or a single mapping) of source->dest copies.
    Entries missing course_source_repo/course_source_path are skipped (nothing to copy).
    A malformed `deploy_datetime` parses to None (ship at the entry's event_datetime)."""
    items = [raw] if isinstance(raw, dict) else (raw or [])
    out: list[Deploy] = []
    for i, d in enumerate(items):
        where = f"releases.{label}.deploy[{i}]"
        if not isinstance(d, dict):
            _drop(drops, where, "not a mapping", "this copy never ships")
            continue
        src_repo, src_path = d.get("course_source_repo"), d.get("course_source_path")
        if not src_repo or not src_path:
            _drop(
                drops,
                where,
                "missing `course_source_repo` and/or `course_source_path`",
                "this copy never ships",
            )
            continue
        dest_path = d.get("cohort_dest_path")
        _flag_unknown_keys(
            drops, d, KNOWN_DEPLOY, where, "that setting is ignored for this copy"
        )
        out.append(
            Deploy(
                course_source_repo=str(src_repo),
                course_source_path=str(src_path),
                cohort_dest_repo=str(d.get("cohort_dest_repo") or "materials"),
                cohort_dest_path=str(dest_path) if dest_path else None,
                deploy_datetime=_coerce_datetime(d.get("deploy_datetime"), tz),
            )
        )
    return out


def _is_tbc(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() == "tbc"


def _parse_releases(raw: object, tz: ZoneInfo, drops: list[str]) -> list[Release]:
    """Parse `releases:` (label -> {event_datetime + deploys}) into Releases sorted by
    their event_datetime.

    TBC: `event_datetime: tbc` keeps the entry as an UNDATED site row (when=None -
    nothing can fire); `tbc: true` next to a real date keeps everything firing but marks
    the site row "(TBC)". An entry with no date and no tbc can never fire or be shown,
    so it's dropped."""
    out: list[Release] = []
    mapping = _require_mapping(
        raw, drops, "releases", "label", "the whole release plan is ignored"
    )
    if mapping is None:
        return out
    for label, entry in mapping.items():
        where = f"releases.{label}"
        if not isinstance(entry, dict):
            _drop(
                drops, where, "not a mapping", "nothing deploys and no site row appears"
            )
            continue
        raw_when = entry.get("event_datetime")
        when = _coerce_datetime(raw_when, tz)
        tbc = _is_tbc(raw_when) or entry.get("tbc") is True
        if when is None and not tbc:
            _drop(
                drops,
                where,
                "no valid `event_datetime` (use `tbc` if the date is not settled)",
                "nothing deploys and no site row appears",
            )
            continue
        _flag_unknown_keys(
            drops, entry, KNOWN_RELEASE, where, "that setting is ignored"
        )
        assignment = entry.get("assignment")
        out.append(
            Release(
                label=str(label),
                when=when,
                deploy=_parse_deploy(entry.get("deploy"), tz, drops, str(label)),
                assignment=str(assignment) if assignment else None,
                title=str(entry.get("title") or ""),
                tbc=tbc,
            )
        )
    # Undated (TBC) entries sort to the end of the plan.
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    out.sort(key=lambda r: (r.when is None, r.when or epoch))
    return out


def _parse_assignments(
    raw: object, tz: ZoneInfo, drops: list[str]
) -> dict[str, AssignmentEntry]:
    # Only the nested {due_datetime, ...} form is accepted - matching the one schema
    # documented everywhere - rather than also silently accepting a bare due-date scalar.
    # A malformed `grading_datetime` parses to None and grading falls back to due_datetime.
    out: dict[str, AssignmentEntry] = {}
    cost = "no deadline for students, no submission snapshot and no autograding"
    mapping = _require_mapping(
        raw,
        drops,
        "assignments",
        "slug",
        "no assignment has a deadline, snapshot or autograding",
    )
    if mapping is None:
        return out
    for slug, entry in mapping.items():
        where = f"assignments.{slug}"
        if not isinstance(entry, dict):
            _drop(
                drops, where, "not a mapping (it needs a nested `due_datetime:`)", cost
            )
            continue
        due = _coerce_datetime(entry.get("due_datetime"), tz, end_of_day=True)
        if due is None:
            _drop(drops, where, "no valid `due_datetime`", cost)
            continue
        source_repo = str(entry.get("course_source_repo") or "").strip()
        if not source_repo:
            _drop(drops, where, "no `course_source_repo`", cost)
            continue
        _flag_unknown_keys(
            drops, entry, KNOWN_ASSIGNMENT, where, "that setting is ignored"
        )
        try:
            cap = int(entry["max_team_size"])
        except (KeyError, TypeError, ValueError):
            cap = None
        kind = str(entry.get("type") or "").strip().lower()
        if kind and kind not in ("group", "individual"):
            # A typo'd `type` (e.g. `gruop`) silently falls back to individual, so a group
            # assignment would be provisioned one-repo-per-student. Keep the fallback but
            # surface it, since the functional consequence is otherwise invisible.
            drops.append(
                f"{where}.type: unrecognised value {kind!r} (expected 'group' or "
                f"'individual') - treated as individual, one repo per student"
            )
        dest = str(entry.get("cohort_dest_repo") or "").strip()
        out[str(slug)] = AssignmentEntry(
            due_datetime=due,
            course_source_repo=source_repo,
            cohort_dest_repo=dest or None,
            grading_datetime=_coerce_datetime(
                entry.get("grading_datetime"), tz, end_of_day=True
            ),
            handout_datetime=_coerce_datetime(entry.get("handout_datetime"), tz),
            # anything other than the two known values -> None (silent-drop style)
            type=kind if kind in ("group", "individual") else None,
            max_team_size=cap,
        )
    return out


def _parse_events(raw: object, tz: ZoneInfo, drops: list[str]) -> list[Event]:
    """Parse `events:` (label -> {type, title, event_datetime}) into display-only rows,
    in calendar order.

    `event_datetime` is a whole-day date, or a full datetime when the start time is known
    (the website then shows that time instead of its placeholder). `event_datetime: tbc`
    keeps the event as an undated TBC row; `tbc: true` next to a real date marks it
    provisional ("(TBC)"). An entry with no date and no tbc can never be shown, so it's
    dropped."""
    out: list[Event] = []
    mapping = _require_mapping(
        raw, drops, "events", "label", "no calendar rows appear on the site"
    )
    if mapping is None:
        return out
    for label, entry in mapping.items():
        where = f"events.{label}"
        if not isinstance(entry, dict):
            _drop(drops, where, "not a mapping", "the row never appears on the site")
            continue
        raw_when = entry.get("event_datetime")
        when = _coerce_date_or_datetime(raw_when, tz)
        tbc = _is_tbc(raw_when) or entry.get("tbc") is True
        if when is None and not tbc:
            _drop(
                drops,
                where,
                "no valid `event_datetime` (use `tbc` if the date is not settled)",
                "the row never appears on the site",
            )
            continue
        _flag_unknown_keys(drops, entry, KNOWN_EVENT, where, "that setting is ignored")
        kind = str(entry.get("type") or "").strip().lower()
        out.append(
            Event(
                label=str(label),
                title=str(entry.get("title") or ""),
                when=when,
                # anything other than the two known values -> the display-only default
                # (silent-drop style): a typo'd `type` still shows the row
                type="exam" if kind == "exam" else "special_event",
                tbc=tbc,
            )
        )
    # Undated (TBC) events sort to the end of the term, as they do in the release plan.
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    out.sort(
        key=lambda e: (
            e.when is None,
            epoch if e.when is None else _instant(e.when, tz),
        )
    )
    return out


def parse(meta: dict) -> Schedule:
    """Parse a loaded schedule.yml dict into a Schedule. Pure; tolerant of missing/blank
    fields (a cohort with no schedule.yml behaves exactly as before). Anything it has to
    throw away is recorded in `Schedule.dropped` rather than vanishing - parsing stays
    total, but never silent."""
    meta = meta if isinstance(meta, dict) else {}
    drops: list[str] = []
    # A whole plan under an unknown top-level key (`materials_releases:` instead of
    # `releases:`) otherwise validates as "OK: nothing dropped" with zero releases - the
    # worst kind of silent failure, since the file looks full. Flag it here.
    _flag_unknown_keys(
        drops, meta, KNOWN_TOP_LEVEL, "", "nothing it contains is scheduled or shown"
    )
    tz_name = meta.get("timezone")
    tz = _tz(tz_name)
    if tz_name and str(tz_name).strip() != str(tz):
        drops.append(
            f"timezone: `{tz_name}` is not a known zone - falling back to {DEFAULT_TZ}, "
            f"so every naive time below is read in {DEFAULT_TZ}"
        )
    return Schedule(
        timezone=str(tz_name or DEFAULT_TZ),
        releases=_parse_releases(meta.get("releases"), tz, drops),
        semester_start=_coerce_date(meta.get("semester_start")),
        semester_end=_coerce_date(meta.get("semester_end")),
        assignments=_parse_assignments(meta.get("assignments"), tz, drops),
        events=_parse_events(meta.get("events"), tz, drops),
        dropped=drops,
    )


def cohort_name(slug: str, entry: AssignmentEntry) -> str:
    """The ONE cohort-side name for an assignment: `cohort_dest_repo`, else its slug.
    Every cohort-side artefact keys on it - generated repos, teams.csv, snapshots,
    autograde markers, grades - and the scheduler's fire-once check must agree with what
    collect writes, so both resolve it here rather than each deriving its own."""
    return entry.cohort_dest_repo or slug


def entry_for_repo(sched: Schedule, repo: str) -> tuple[str, AssignmentEntry] | None:
    """(slug, entry) for the assignment that hands out from `repo`, or None.

    Callers that start from a REPO name - the autograder, the website - must find its
    schedule entry by matching `course_source_repo`, never by deriving a slug from the
    repo name. The slug is now a free label, so `wk3-regression-f2026` may legitimately be
    keyed `regression`; deriving would silently miss it, and the symptoms are quiet ones
    (no due date on the site, a group assignment provisioned per student)."""
    for slug, entry in sched.assignments.items():
        if entry.course_source_repo == repo:
            return slug, entry
    return None


def grading_datetime_at(sched: Schedule, slug: str) -> datetime | None:
    """The grading pin for `slug` as a tz-aware datetime - the ONE instant at which the
    submission snapshot freezes and the autograder fires, so both always agree.

    An explicit `grading_datetime` wins; else `due_datetime`. None if unscheduled."""
    entry = sched.assignments.get(slug)
    if entry is None:
        return None
    if entry.grading_datetime is not None:
        return entry.grading_datetime
    return entry.due_datetime


def grading_datetime_iso(sched: Schedule, slug: str) -> str | None:
    """`grading_datetime_at` as an ISO string, or None if unscheduled."""
    at = grading_datetime_at(sched, slug)
    return at.isoformat() if at is not None else None


# ---------------------------------------------------------------------- gh/git wiring


def load(cohort_org: str) -> Schedule:
    """Fetch + parse schedule.yml from the cohort's PRIVATE classroom-config repo. A
    pure loader: a missing file returns an empty Schedule silently (every field
    optional everywhere it's read).

    A file that does not PARSE (faculty-editable YAML - an unclosed brace, a bad indent)
    is treated exactly as an absent one: the error is logged loudly, with the parser's own
    line/column, and an empty Schedule is returned. It must never raise: `load` sits under
    the hourly scheduler AND the site sync, and one cohort's typo froze both."""
    content = get_file_content(cohort_org, CONFIG_REPO, SCHEDULE_PATH)
    try:
        meta = yaml.safe_load(content) if content else {}
    except yaml.YAMLError as exc:
        log_err(
            f"{cohort_org}/{CONFIG_REPO}/{SCHEDULE_PATH} is NOT valid YAML - the whole "
            f"schedule is ignored:"
        )
        # the parser's own message: it carries the line/column and the offending snippet
        log_err(str(exc))
        log_err(
            f"fix {CONFIG_REPO}/{SCHEDULE_PATH} on main in {cohort_org} - until then "
            f"NOTHING is scheduled for this cohort (no releases, no handouts, no deadline "
            f"snapshots, no autograding) and the site builds without schedule data."
        )
        meta = {}
    sched = parse(meta if isinstance(meta, dict) else {})
    if sched.dropped:
        # Loud, because this is the failure faculty cannot see: the file is valid YAML and
        # the run goes green, but an entry they wrote is not in the plan. Every caller
        # comes through here - the hourly scheduler, the site sync, Check cohort setup - so
        # saying it once here says it everywhere.
        log_err(
            f"{cohort_org}/{CONFIG_REPO}/{SCHEDULE_PATH}: {len(sched.dropped)} entry/ies "
            f"DROPPED - they parse as YAML but not as schedule entries:"
        )
        for line in sched.dropped:
            log_err(f"  {line}")
        log_err(f"fix them on main in {cohort_org}; everything else is unaffected.")
    return sched


def load_file(path: str) -> tuple[Schedule | None, str | None]:
    """Parse a schedule.yml from DISK: returns (schedule, None), or (None, error) when the
    file is missing or is not valid YAML.

    The opposite stance to `load`, deliberately. `load` treats an unparseable cohort file
    as an absent one, because it sits under the hourly cron and one typo must not be able
    to freeze a cohort. Here the caller is a validator whose whole job is to fail, so a
    broken file is an error and not an empty schedule."""
    p = Path(path)
    try:
        text = p.read_text()
    except OSError as exc:
        return None, f"cannot read {path}: {exc}"
    try:
        meta = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        # the parser's own message carries the line/column and the offending snippet
        return None, f"{path} is not valid YAML:\n{exc}"
    if not isinstance(meta, dict):
        return None, f"{path} is valid YAML but not a mapping - it needs top-level keys"
    return parse(meta), None


def _validate_report(sched: Schedule, source: str) -> str:
    """What the parser UNDERSTOOD, followed by anything it threw away.

    Reporting the totals matters as much as reporting the drops: a well-formed entry with
    the wrong date is invisible to validation, but "4 assignments" when you wrote five is
    not. This is what a reader sees in a run summary, so it stays plain text."""
    lines = [
        f"Parsed {source}",
        f"  term {sched.semester_start} -> {sched.semester_end}  ({sched.timezone})",
        (
            f"  {len(sched.releases)} release(s), "
            f"{sum(len(r.deploy) for r in sched.releases)} deploy(s) | "
            f"{len(sched.assignments)} assignment(s) | {len(sched.events)} event(s)"
        ),
    ]
    if sched.dropped:
        lines.append("")
        lines.append(f"  {len(sched.dropped)} ENTRY/IES DROPPED:")
        lines.extend(f"    - {d}" for d in sched.dropped)
    return "\n".join(lines)


_HANDOUT_COMMENT = "   # set automatically by the Release assignment button"
_DUE_TODO = "# TODO: add `due_datetime:` - the date students see (required)"


def _insert_handout(text: str, slug: str, stamp: str) -> str | None:
    """Pure text surgery for `record_handout` - schedule.yml is USER-owned and
    comment-rich, so we insert lines rather than re-serialising (which would destroy
    every comment).

    Returns the new text, or None when nothing should - or safely can - change: the
    entry already carries a handout (write-once, a scheduled value is never touched), or
    the `assignments:` block is shaped in a way this line surgery can't recognise (a flow
    mapping). In the latter case we leave the file untouched rather than fabricate a
    duplicate entry - the old code assumed exactly two-space indentation, missed a
    deeper-nested entry, and injected a fake `  {slug}:` that swallowed the real one,
    dropping its `due_datetime` for good."""
    lines = text.splitlines(keepends=True)

    def indent_of(ln: str) -> int:
        return len(ln) - len(ln.lstrip())

    # locate the top-level `assignments:` mapping key (a bare block header at column 0)
    a_start = next(
        (
            i
            for i, ln in enumerate(lines)
            if ln.split("#")[0].rstrip() == "assignments:"
        ),
        None,
    )
    if a_start is None:
        # A flow-style `assignments: {...}` (or any other col-0 line beginning
        # `assignments:` that isn't a plain block header) can't take a line insertion -
        # leave it untouched rather than append a second, duplicate key.
        if any(re.match(r"^assignments:\s*\S", ln.split("#")[0]) for ln in lines):
            return None
        # no assignments block at all: append one (the documented 2-space shape),
        # flagging the due date still to add.
        return (
            (text if text.endswith("\n") or not text else text + "\n")
            + f"\nassignments:\n  {slug}:\n"
            + f"    handout_datetime: {stamp}{_HANDOUT_COMMENT}\n"
            + f"    {_DUE_TODO}\n"
        )

    # The block body runs until the next non-comment column-0 line.
    block_end = len(lines)
    for i in range(a_start + 1, len(lines)):
        stripped = lines[i].split("#")[0].rstrip()
        if stripped and not lines[i].startswith((" ", "\t")):
            block_end = i
            break

    # The slug key at WHATEVER indent it sits at - matching only exactly two spaces was
    # the bug. A positive indent inside the block is required (a col-0 match would be a
    # sibling top-level key, not an assignment).
    slug_re = re.compile(rf"^(\s+){re.escape(slug)}:\s*(#.*)?$")
    for i in range(a_start + 1, block_end):
        m = slug_re.match(lines[i])
        if not m:
            continue
        slug_indent = len(m.group(1))
        # Scan the slug's sub-block (lines indented deeper than the slug) for an existing
        # handout, learning the child indent from its first field.
        child_indent = slug_indent + 2
        seen_child = False
        for j in range(i + 1, block_end):
            stripped = lines[j].split("#")[0].rstrip()
            if not stripped:
                continue
            if indent_of(lines[j]) <= slug_indent:
                break  # next sibling slug, or out of the block
            if not seen_child:
                child_indent, seen_child = indent_of(lines[j]), True
            if stripped.lstrip().startswith("handout_datetime:"):
                return None  # write-once - never move a scheduled or recorded handout
        lines.insert(
            i + 1, f"{' ' * child_indent}handout_datetime: {stamp}{_HANDOUT_COMMENT}\n"
        )
        return "".join(lines)

    # Slug genuinely absent: fabricate a new entry, matched to the block's OWN entry
    # indent (learned from an existing sibling) so we never inject a 2-space entry into a
    # 4-space block. An empty block has no sibling to learn from - use the documented
    # 2-space shape.
    entry_indent = 2
    for i in range(a_start + 1, block_end):
        if lines[i].split("#")[0].rstrip():
            entry_indent = indent_of(lines[i])
            break
    pad, child = " " * entry_indent, " " * (entry_indent + 2)
    lines.insert(
        a_start + 1,
        f"{pad}{slug}:\n"
        f"{child}handout_datetime: {stamp}{_HANDOUT_COMMENT}\n"
        f"{child}{_DUE_TODO}\n",
    )
    return "".join(lines)


def record_handout(cohort_org: str, slug: str, stamp: str | None = None) -> None:
    """Record a manual handout back into schedule.yml (`assignments.<slug>.handout_datetime`),
    so the schedule stays the one record of when every assignment went out - whether
    the cron released it or a person clicked the button. Write-once: an existing
    handout_datetime (scheduled, or recorded by an earlier click) is never modified. Best
    effort - a failure here must never fail the release itself."""
    from .utils import log, put_file

    text = get_file_content(cohort_org, CONFIG_REPO, SCHEDULE_PATH) or ""
    if stamp is None:
        # the release moment, in the cohort's own timezone (naive, like every other
        # schedule datetime - the parser reads it back in that same zone)
        try:
            tz_name = (yaml.safe_load(text) or {}).get("timezone")
        except yaml.YAMLError:
            tz_name = None
        stamp = datetime.now(
            _tz(tz_name if isinstance(tz_name, str) else None)
        ).strftime("%Y-%m-%dT%H:%M")
    new = _insert_handout(text, slug, stamp)
    if new is None:
        return
    if put_file(
        cohort_org,
        CONFIG_REPO,
        SCHEDULE_PATH,
        new.encode(),
        f"schedule: record {slug} handout ({stamp})",
    ):
        log(f"  recorded handout in {CONFIG_REPO}/{SCHEDULE_PATH}: {slug} @ {stamp}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--cohort-org", help="fetch schedule.yml from a cohort org")
    source.add_argument(
        "--file", help="validate a schedule.yml on disk (no GitHub access)"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="exit non-zero if the file is unparseable or any entry was dropped, "
        "instead of dumping the schedule",
    )
    args = parser.parse_args()

    if args.file:
        sched, error = load_file(args.file)
        if error is not None:
            # Unlike a cohort fetch, a broken FILE is a hard failure - see load_file.
            log_err(error)
            print(f"INVALID: {args.file} could not be parsed")
            return 1
        source_name = args.file
    else:
        # A cohort fetch reads schedule.yml over the API: absent is an empty Schedule,
        # but an unreadable one raises - report it as a line, not a traceback.
        try:
            sched = load(args.cohort_org)
        except RuntimeError as exc:
            log_err(str(exc))
            return 1
        source_name = f"{args.cohort_org}/{SCHEDULE_PATH}"

    if not args.validate:
        print(json.dumps(asdict(sched), indent=2, default=str))
        return 0
    # Report what was UNDERSTOOD as well as what was dropped: validation cannot catch a
    # well-formed entry with the wrong date, but a count that is one short is visible.
    print(_validate_report(sched, source_name))
    if sched.dropped:
        print(f"\nINVALID: {len(sched.dropped)} entry/ies dropped")
        return 1
    print("\nOK: nothing dropped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
