"""dsl-course schedule -- the per-cohort classroom-config/schedule.yml, this cohort's
single home for every date faculty declare: the release calendar (sessions/labs), the
semester window, assignment due dates + grading grace-days, and exam dates.

Replaces the old split between the cohort's `.github/dsl-course.yml` `schedule:` block
(due dates/exams/grace-days) and `classroom-config/schedule.csv` (session -> release
date) - both were 100% faculty-typed with no bot writer and no PII, so there was no
reason for them to live in different repos of the same cohort org.

classroom-config/schedule.yml:
    semester_start: 2026-09-07
    semester_end: 2026-12-18
    sessions:                    # release calendar - session ordinal -> date; drives
      "1": 2026-09-07            # the Scheduled release cron (scheduler.py)
      "3": 2026-09-21
    labs:                        # a second, parallel release calendar for cohorts with
      "1": 2026-09-09            # a labs/<NN>_.../ section on its own cadence
      "3": 2026-09-23
    assignments:                 # due dates (slug -> {due, grace_days}) - the SSOT for
      assignment-1:               # both website display (site.py) and the grading
        due: 2026-10-13           # deadline pin (collect.py); grace_days extends the
        grace_days: 2             # grading pin only, never shown to students
    exams:
      - name: MidTerm Exam
        date: 2026-11-03

Every field is optional - a cohort with no schedule.yml (or a blank one) behaves
exactly as before everywhere that reads it (dates are synthesised/skipped, never
blocked).

Usage:
    python3 -m dsl_course.schedule --cohort-org Deep-Learning-EXAMPLE-f2026
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

import yaml

from .utils import get_file_content

CONFIG_REPO = "classroom-config"
SCHEDULE_PATH = "schedule.yml"


# --------------------------------------------------------------------------- pure core


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


@dataclass
class AssignmentEntry:
    due: date
    grace_days: int = 0  # grading-only pin extension, never shown to students


@dataclass
class Exam:
    name: str
    date: date


@dataclass
class Schedule:
    semester_start: date | None = None
    semester_end: date | None = None
    sessions: dict[str, date] = field(default_factory=dict)
    labs: dict[str, date] = field(default_factory=dict)
    assignments: dict[str, AssignmentEntry] = field(default_factory=dict)
    exams: list[Exam] = field(default_factory=list)


def _parse_calendar(raw: dict) -> dict[str, date]:
    return {str(k): d for k, v in (raw or {}).items() if (d := _coerce_date(v))}


def _parse_assignments(raw: dict) -> dict[str, AssignmentEntry]:
    # Only the nested {due, grace_days} form is accepted - matching the one schema
    # documented everywhere (this module's docstring, the seeded schedule.yml sample,
    # required-input-schema.md), rather than also silently accepting a bare due-date
    # scalar nobody is told to write.
    out: dict[str, AssignmentEntry] = {}
    for slug, entry in (raw or {}).items():
        if not isinstance(entry, dict):
            continue
        due = _coerce_date(entry.get("due"))
        if due is None:
            continue
        try:
            grace = int(entry.get("grace_days", 0))
        except (TypeError, ValueError):
            grace = 0
        out[str(slug)] = AssignmentEntry(due=due, grace_days=grace)
    return out


def parse(meta: dict) -> Schedule:
    """Parse a loaded schedule.yml dict into a Schedule. Pure; tolerant of missing/blank
    fields (a cohort with no schedule.yml behaves exactly as before)."""
    meta = meta if isinstance(meta, dict) else {}
    exams = [
        Exam(name=str(e.get("name", "Exam")), date=d)
        for e in (meta.get("exams") or [])
        if isinstance(e, dict) and (d := _coerce_date(e.get("date")))
    ]
    return Schedule(
        semester_start=_coerce_date(meta.get("semester_start")),
        semester_end=_coerce_date(meta.get("semester_end")),
        sessions=_parse_calendar(meta.get("sessions") or {}),
        labs=_parse_calendar(meta.get("labs") or {}),
        assignments=_parse_assignments(meta.get("assignments") or {}),
        exams=exams,
    )


def grading_deadline(sched: Schedule, slug: str) -> str | None:
    """The grading pin for `slug`: due date + optional grace_days. None if unscheduled."""
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
