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
          - source_repo: course-materials-f2026   # source_repo + source_path are the
            source_path: lectures/02_intro        # only required keys; dest_repo,
            dest_repo: materials                  # dest_path and deploy_datetime are
            dest_path: lectures/02_intro          # optional.
            deploy_datetime: 2026-09-15T09:00
    assignments:                     # each assignment's whole lifecycle. A bare
      assignment-1:                  # due_datetime is END of day (23:59:59) - "due on the
        handout_datetime: 2026-09-22T09:00  # 13th" closes at day's end.
        due_datetime: 2026-10-13     # grading_datetime is the moment the snapshot
        grading_datetime: 2026-10-15 # freezes and the autograder fires (default: due).
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

Usage:
    python3 -m dsl_course.schedule --cohort-org Deep-Learning-EXAMPLE-f2026
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .utils import get_file_content

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


def _coerce_date(value: object) -> date | None:
    """A YAML date/datetime or an ISO `YYYY-MM-DD` string -> date (None if unparseable).
    Date-level (used for semester bounds and whole-day events)."""
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
    dest repo. `dest_path` defaults to `source_path` (mirror).

    `deploy_datetime` optionally overrides the copy's own ship time; unset, it ships at
    the parent entry's `event_datetime`. This is what disaggregates the class from its
    materials: the entry's `event_datetime` is the session the site announces, a deploy's
    `deploy_datetime` ships the files an hour (or a week) before or after it."""

    source_repo: str
    source_path: str
    dest_repo: str = "materials"
    dest_path: str | None = None
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


def _parse_deploy(raw: object, tz: ZoneInfo) -> list[Deploy]:
    """Parse a release's `deploy:` - a list (or a single mapping) of source->dest copies.
    Entries missing source_repo/source_path are skipped (nothing to copy). A malformed
    `deploy_datetime` parses to None (ship at the entry's event_datetime), in keeping
    with this parser's silent-drop style."""
    items = [raw] if isinstance(raw, dict) else (raw or [])
    out: list[Deploy] = []
    for d in items:
        if not isinstance(d, dict):
            continue
        src_repo, src_path = d.get("source_repo"), d.get("source_path")
        if not src_repo or not src_path:
            continue
        dest_path = d.get("dest_path")
        out.append(
            Deploy(
                source_repo=str(src_repo),
                source_path=str(src_path),
                dest_repo=str(d.get("dest_repo") or "materials"),
                dest_path=str(dest_path) if dest_path else None,
                deploy_datetime=_coerce_datetime(d.get("deploy_datetime"), tz),
            )
        )
    return out


def _is_tbc(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() == "tbc"


def _parse_releases(raw: object, tz: ZoneInfo) -> list[Release]:
    """Parse `releases:` (label -> {event_datetime + deploys}) into Releases sorted by
    their event_datetime.

    TBC: `event_datetime: tbc` keeps the entry as an UNDATED site row (when=None -
    nothing can fire); `tbc: true` next to a real date keeps everything firing but marks
    the site row "(TBC)". An entry with no date and no tbc can never fire or be shown,
    so it's dropped."""
    out: list[Release] = []
    for label, entry in (raw or {}).items():
        if not isinstance(entry, dict):
            continue
        raw_when = entry.get("event_datetime")
        when = _coerce_datetime(raw_when, tz)
        tbc = _is_tbc(raw_when) or entry.get("tbc") is True
        if when is None and not tbc:
            continue
        assignment = entry.get("assignment")
        out.append(
            Release(
                label=str(label),
                when=when,
                deploy=_parse_deploy(entry.get("deploy"), tz),
                assignment=str(assignment) if assignment else None,
                title=str(entry.get("title") or ""),
                tbc=tbc,
            )
        )
    # Undated (TBC) entries sort to the end of the plan.
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    out.sort(key=lambda r: (r.when is None, r.when or epoch))
    return out


def _parse_assignments(raw: object, tz: ZoneInfo) -> dict[str, AssignmentEntry]:
    # Only the nested {due_datetime, ...} form is accepted - matching the one schema
    # documented everywhere - rather than also silently accepting a bare due-date scalar.
    # A malformed `grading_datetime` parses to None and grading falls back to
    # due_datetime, in keeping with this parser's silent-drop style.
    out: dict[str, AssignmentEntry] = {}
    for slug, entry in (raw or {}).items():
        if not isinstance(entry, dict):
            continue
        due = _coerce_datetime(entry.get("due_datetime"), tz, end_of_day=True)
        if due is None:
            continue
        try:
            cap = int(entry["max_team_size"])
        except (KeyError, TypeError, ValueError):
            cap = None
        kind = str(entry.get("type") or "").strip().lower()
        out[str(slug)] = AssignmentEntry(
            due_datetime=due,
            grading_datetime=_coerce_datetime(
                entry.get("grading_datetime"), tz, end_of_day=True
            ),
            handout_datetime=_coerce_datetime(entry.get("handout_datetime"), tz),
            # anything other than the two known values -> None (silent-drop style)
            type=kind if kind in ("group", "individual") else None,
            max_team_size=cap,
        )
    return out


def _parse_events(raw: object, tz: ZoneInfo) -> list[Event]:
    """Parse `events:` (label -> {type, title, event_datetime}) into display-only rows,
    in calendar order.

    `event_datetime` is a whole-day date, or a full datetime when the start time is known
    (the website then shows that time instead of its placeholder). `event_datetime: tbc`
    keeps the event as an undated TBC row; `tbc: true` next to a real date marks it
    provisional ("(TBC)"). An entry with no date and no tbc can never be shown, so it's
    dropped."""
    out: list[Event] = []
    for label, entry in (raw or {}).items():
        if not isinstance(entry, dict):
            continue
        raw_when = entry.get("event_datetime")
        when = _coerce_date_or_datetime(raw_when, tz)
        tbc = _is_tbc(raw_when) or entry.get("tbc") is True
        if when is None and not tbc:
            continue
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
        key=lambda e: (e.when is None, epoch if e.when is None else _instant(e.when, tz))
    )
    return out


def parse(meta: dict) -> Schedule:
    """Parse a loaded schedule.yml dict into a Schedule. Pure; tolerant of missing/blank
    fields (a cohort with no schedule.yml behaves exactly as before)."""
    meta = meta if isinstance(meta, dict) else {}
    tz = _tz(meta.get("timezone"))
    return Schedule(
        timezone=str(meta.get("timezone") or DEFAULT_TZ),
        releases=_parse_releases(meta.get("releases"), tz),
        semester_start=_coerce_date(meta.get("semester_start")),
        semester_end=_coerce_date(meta.get("semester_end")),
        assignments=_parse_assignments(meta.get("assignments"), tz),
        events=_parse_events(meta.get("events"), tz),
    )


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
    optional everywhere it's read)."""
    content = get_file_content(cohort_org, CONFIG_REPO, SCHEDULE_PATH)
    meta = yaml.safe_load(content) if content else {}
    return parse(meta if isinstance(meta, dict) else {})


def _insert_handout(text: str, slug: str, stamp: str) -> str | None:
    """Pure text surgery for `record_handout` - schedule.yml is USER-owned and
    comment-rich, so we insert lines rather than re-serialising (which would destroy
    every comment). Returns the new text, or None when nothing should change (the
    entry already has a handout - write-once, a scheduled value is never touched)."""
    lines = text.splitlines(keepends=True)
    # locate the top-level assignments: block and, inside it, the slug's sub-block
    a_start = next(
        (i for i, ln in enumerate(lines) if ln.split("#")[0].rstrip() == "assignments:"),
        None,
    )
    entry_line = (
        f"    handout_datetime: {stamp}   # set automatically by the Release assignment button\n"
    )
    if a_start is None:
        # no assignments block at all: append one, flagging the due date still to add
        return (
            (text if text.endswith("\n") or not text else text + "\n")
            + f"\nassignments:\n  {slug}:\n{entry_line}"
            + "    # TODO: add `due_datetime:` - the date students see (required)\n"
        )
    # walk the block: find `  <slug>:`; block ends at the next non-comment col-0 line
    s_start = None
    for i in range(a_start + 1, len(lines)):
        stripped = lines[i].split("#")[0].rstrip()
        if stripped and not lines[i].startswith(" "):
            break  # left the assignments block
        if stripped == f"  {slug}:":
            s_start = i
            break
    if s_start is None:
        insert = (
            f"  {slug}:\n{entry_line}"
            "    # TODO: add `due_datetime:` - the date students see (required)\n"
        )
        lines.insert(a_start + 1, insert)
        return "".join(lines)
    # slug found: scan its sub-block (deeper-indented lines) for an existing handout
    for i in range(s_start + 1, len(lines)):
        stripped = lines[i].split("#")[0].rstrip()
        if stripped and (len(lines[i]) - len(lines[i].lstrip())) <= 2:
            break  # next slug or out of the block
        if stripped.strip().startswith("handout_datetime:"):
            return None  # write-once - never move a scheduled or recorded handout
    lines.insert(s_start + 1, entry_line)
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
        stamp = datetime.now(_tz(tz_name if isinstance(tz_name, str) else None)).strftime(
            "%Y-%m-%dT%H:%M"
        )
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
    parser.add_argument("--cohort-org", required=True)
    args = parser.parse_args()
    print(json.dumps(asdict(load(args.cohort_org)), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
