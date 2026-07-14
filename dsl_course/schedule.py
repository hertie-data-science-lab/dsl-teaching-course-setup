"""dsl-course schedule -- the per-cohort classroom-config/schedule.yml, this cohort's
single home for the timed release plan AND the dates other tools display/enforce:

    timezone: Europe/Berlin          # optional (default Europe/Berlin) - how naive times
                                     # below are interpreted; GitHub cron itself is UTC
    materials_releases:              # the auto-release plan - label -> {when + actions}.
      session_2:                     # `when` is a full datetime (bare date -> 00:00);
        when: 2026-09-15T14:00       # dsl_course.scheduler fires each release when its
        deploy:                      # `when` has arrived. Labels are free identifiers.
          - {source_repo: course-materials-f2026, source_path: lectures/02_intro,
             dest_repo: materials, dest_path: lectures/02_intro}   # dest_path optional
      a2-grade:
        when: 2026-10-15T00:00
        grade: {template: assignment-2-f2026, deadline: 2026-10-13T23:59, group: false}
    assignments:                     # due dates (website countdown + grading pin). A bare
      assignment-1:                  # due date is END of day (23:59:59) - "due on the
        due: 2026-10-13              # 13th" closes at day's end (a release date opens at
        grace_days: 2               # its start). grace_days extends the grading pin only.
    exams:
      - {name: MidTerm Exam, date: 2026-11-03}
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
from datetime import date, datetime, time, timedelta
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
    Date-level (used for semester bounds + exams, which are whole-day)."""
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


@dataclass
class Deploy:
    """One source->dest copy: a path in a COURSE-org source repo copied into a COHORT-org
    dest repo. `dest_path` defaults to `source_path` (mirror)."""

    source_repo: str
    source_path: str
    dest_repo: str = "materials"
    dest_path: str | None = None


@dataclass
class Grade:
    template: str
    deadline: datetime | None = None  # commit cutoff; None -> resolved from assignments
    group: bool = False


@dataclass
class Release:
    """A labelled scheduled release: fire its actions once `when` has arrived. A release
    may carry any mix of `deploy` (content copies), `assignment` (provision student repos
    from a template), and `grade` (run the autograder)."""

    label: str
    when: datetime
    deploy: list[Deploy] = field(default_factory=list)
    assignment: str | None = None
    grade: Grade | None = None


@dataclass
class AssignmentEntry:
    due: datetime
    grace_days: int = 0  # grading-only pin extension, never shown to students


@dataclass
class Exam:
    name: str
    date: date


@dataclass
class Schedule:
    timezone: str = DEFAULT_TZ
    releases: list[Release] = field(default_factory=list)
    semester_start: date | None = None
    semester_end: date | None = None
    assignments: dict[str, AssignmentEntry] = field(default_factory=dict)
    exams: list[Exam] = field(default_factory=list)


def _parse_deploy(raw: object) -> list[Deploy]:
    """Parse a release's `deploy:` - a list (or a single mapping) of source->dest copies.
    Entries missing source_repo/source_path are skipped (nothing to copy)."""
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
            )
        )
    return out


def _parse_grade(raw: object, tz: ZoneInfo) -> Grade | None:
    """Parse a release's `grade:` - either `grade: <template>` or a
    `{template, deadline, group}` mapping."""
    if isinstance(raw, str) and raw.strip():
        return Grade(template=raw.strip())
    if isinstance(raw, dict) and raw.get("template"):
        return Grade(
            template=str(raw["template"]),
            deadline=_coerce_datetime(raw.get("deadline"), tz, end_of_day=True),
            group=bool(raw.get("group", False)),
        )
    return None


def _parse_releases(raw: object, tz: ZoneInfo) -> list[Release]:
    """Parse `materials_releases:` (label -> {when + actions}) into Releases sorted by
    `when`. A release with no valid `when` can never fire, so it's dropped."""
    out: list[Release] = []
    for label, entry in (raw or {}).items():
        if not isinstance(entry, dict):
            continue
        when = _coerce_datetime(entry.get("when"), tz)
        if when is None:
            continue
        assignment = entry.get("assignment")
        out.append(
            Release(
                label=str(label),
                when=when,
                deploy=_parse_deploy(entry.get("deploy")),
                assignment=str(assignment) if assignment else None,
                grade=_parse_grade(entry.get("grade"), tz),
            )
        )
    out.sort(key=lambda r: r.when)
    return out


def _parse_assignments(raw: object, tz: ZoneInfo) -> dict[str, AssignmentEntry]:
    # Only the nested {due, grace_days} form is accepted - matching the one schema
    # documented everywhere - rather than also silently accepting a bare due-date scalar.
    out: dict[str, AssignmentEntry] = {}
    for slug, entry in (raw or {}).items():
        if not isinstance(entry, dict):
            continue
        due = _coerce_datetime(entry.get("due"), tz, end_of_day=True)
        if due is None:
            continue
        try:
            grace = int(entry.get("grace_days", 0))
        except (TypeError, ValueError):
            grace = 0
        out[str(slug)] = AssignmentEntry(due=due, grace_days=grace)
    return out


def _parse_exams(raw: object) -> list[Exam]:
    return [
        Exam(name=str(e.get("name", "Exam")), date=d)
        for e in (raw or [])
        if isinstance(e, dict) and (d := _coerce_date(e.get("date")))
    ]


def parse(meta: dict) -> Schedule:
    """Parse a loaded schedule.yml dict into a Schedule. Pure; tolerant of missing/blank
    fields (a cohort with no schedule.yml behaves exactly as before)."""
    meta = meta if isinstance(meta, dict) else {}
    tz = _tz(meta.get("timezone"))
    return Schedule(
        timezone=str(meta.get("timezone") or DEFAULT_TZ),
        releases=_parse_releases(meta.get("materials_releases"), tz),
        semester_start=_coerce_date(meta.get("semester_start")),
        semester_end=_coerce_date(meta.get("semester_end")),
        assignments=_parse_assignments(meta.get("assignments"), tz),
        exams=_parse_exams(meta.get("exams")),
    )


def grading_deadline(sched: Schedule, slug: str) -> str | None:
    """The grading pin for `slug`: due datetime + optional grace_days. ISO string, or
    None if unscheduled."""
    entry = sched.assignments.get(slug)
    if entry is None:
        return None
    return (entry.due + timedelta(days=entry.grace_days)).isoformat()


# ---------------------------------------------------------------------- gh/git wiring


def load(cohort_org: str) -> Schedule:
    """Fetch + parse schedule.yml from the cohort's PRIVATE classroom-config repo. A
    pure loader: a missing file returns an empty Schedule silently (every field
    optional everywhere it's read)."""
    content = get_file_content(cohort_org, CONFIG_REPO, SCHEDULE_PATH)
    meta = yaml.safe_load(content) if content else {}
    return parse(meta if isinstance(meta, dict) else {})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-org", required=True)
    args = parser.parse_args()
    print(json.dumps(asdict(load(args.cohort_org)), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
