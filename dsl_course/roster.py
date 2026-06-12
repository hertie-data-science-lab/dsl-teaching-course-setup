"""dsl-course roster -- read the per-cohort students.csv.

The single durable roster artifact is a PRIVATE per-cohort `students.csv`, kept in
the cohort org's `classroom-config` repo. Columns:

    student_id,hertie_email,name,github_handle,github_id,section

It is simultaneously the manual roster we maintain now, and the exact shape a future
Moodle adapter will emit. `github_handle` / `github_id` are blank until the student
onboards (the `welcome` Join issue fills them); a row with a blank handle is
enrolled-but-not-yet-onboarded and is skipped by provisioning.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from .utils import get_file_content, log_err

CONFIG_REPO = "classroom-config"
ROSTER_PATH = "students.csv"
FIELDS = ("student_id", "hertie_email", "name", "github_handle", "github_id", "section")


@dataclass
class Student:
    student_id: str
    hertie_email: str
    name: str
    github_handle: str
    github_id: str
    section: str

    @property
    def onboarded(self) -> bool:
        return bool(self.github_handle.strip())


def parse(text: str) -> list[Student]:
    """Parse students.csv text into Student rows."""
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        rows.append(Student(**{f: (row.get(f) or "").strip() for f in FIELDS}))
    return rows


def load(cohort_org: str) -> list[Student]:
    """Fetch + parse students.csv from the cohort's PRIVATE classroom-config repo."""
    content = get_file_content(cohort_org, CONFIG_REPO, ROSTER_PATH)
    if content is None:
        log_err(
            f"Could not find {ROSTER_PATH} in {cohort_org}/{CONFIG_REPO} - "
            f"bootstrap the cohort first (bootstrap_course --cohort)."
        )
        return []
    return parse(content)


def load_path(path: str) -> list[Student]:
    """Parse a local students.csv (for running outside Actions)."""
    with open(path, encoding="utf-8") as fh:
        return parse(fh.read())
