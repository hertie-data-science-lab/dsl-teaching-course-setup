"""list-orgs -- discover DSL course and cohort orgs dynamically from GitHub.

Source of truth: every org's `.github` repo is tagged by `bootstrap_course.py` -
`dsl-course-hub` for a persistent COURSE org, `dsl-cohort` for a per-year COHORT
org. This tool searches for both topics across all repos the caller can see, reads
each org's `.github/dsl-course.yml`, and emits a JSON / Markdown / YAML inventory
of the two tiers separately.

Usage:
    python3 -m dsl_course.list_orgs                       # JSON to stdout
    python3 -m dsl_course.list_orgs --format markdown     # Markdown tables
    python3 -m dsl_course.list_orgs --format yaml         # YAML
    python3 -m dsl_course.list_orgs --update-file PATH    # in-place MD update
"""

from __future__ import annotations

import argparse
import json
import sys

from .utils import gh, gh_json, log_err

COURSE_HUB_TOPIC = "dsl-course-hub"
COHORT_TOPIC = "dsl-cohort"

AUTOGEN_START = "<!-- DSL-AUTOGEN-COURSE-ORGS-START -->"
AUTOGEN_END = "<!-- DSL-AUTOGEN-COURSE-ORGS-END -->"
COHORT_START = "<!-- DSL-AUTOGEN-COHORT-ORGS-START -->"
COHORT_END = "<!-- DSL-AUTOGEN-COHORT-ORGS-END -->"


def _tagged_orgs(topic: str) -> list[str]:
    """Owner logins of every `.github` repo carrying `topic`."""
    results = gh_json(
        "search",
        "repos",
        f"topic:{topic}",
        "--limit",
        "100",
        "--json",
        "name,owner",
    )

    owners = []
    for repo in results:
        if repo.get("name") != ".github":
            continue
        owner = (repo.get("owner") or {}).get("login", "")
        if owner:
            owners.append(owner)
    return owners


def discover_course_orgs() -> list[dict]:
    """Find every `.github` repo tagged `dsl-course-hub` and fetch its metadata.

    Returns a list of dicts with keys: org, org_name, course_name, course_code, url.
    Sorted by org name.
    """
    orgs = []
    for owner in _tagged_orgs(COURSE_HUB_TOPIC):
        meta = _fetch_metadata(owner)
        if meta.get("course"):
            # A cohort org's dsl-course.yml is a pointer back to its course org
            # (`course:`/`org:` keys only). Cohorts bootstrapped before the topic split
            # still carry dsl-course-hub on their .github, so filter them here too -
            # this inventory enumerates COURSE orgs, never their per-year cohorts.
            continue
        orgs.append(
            {
                "org": owner,
                "org_name": meta.get("org_name", owner),
                "course_name": meta.get("course_name", ""),
                "course_code": meta.get("course_code", ""),
                "url": f"https://github.com/{owner}",
            }
        )

    orgs.sort(key=lambda o: o["org"].lower())
    return orgs


def discover_cohort_orgs() -> list[dict]:
    """Find every `.github` repo tagged `dsl-cohort` and read its course pointer.

    Returns a list of dicts with keys: org, course, url - sorted by course org, then
    cohort, so the table groups each course's deliveries together.
    """
    cohorts = [
        {
            "org": owner,
            # `or ""` also covers a bare `course:` key parsed as YAML null.
            "course": _fetch_metadata(owner).get("course") or "",
            "url": f"https://github.com/{owner}",
        }
        for owner in _tagged_orgs(COHORT_TOPIC)
    ]
    cohorts.sort(key=lambda c: (c["course"].lower(), c["org"].lower()))
    return cohorts


def _fetch_metadata(org: str) -> dict:
    """Read and parse `.github/dsl-course.yml` for an org. Returns {} on any failure."""
    code, raw = gh(
        "api",
        f"repos/{org}/.github/contents/dsl-course.yml",
        "--jq",
        ".content | @base64d",
    )
    if code != 0 or not raw:
        return {}

    try:
        import yaml

        parsed = yaml.safe_load(raw) or {}
        return parsed if isinstance(parsed, dict) else {}
    except Exception as e:
        log_err(f"could not parse dsl-course.yml for {org}: {e}")
        return {}


def render_markdown_table(orgs: list[dict]) -> str:
    """Render the autogen section: header + table, bracketed by marker comments."""
    lines = [
        AUTOGEN_START,
        "",
        f"_Auto-generated from GitHub. Discovered via topic `{COURSE_HUB_TOPIC}` on each org's `.github` repo._",
        "",
        "| Org | Course | Code |",
        "| --- | --- | --- |",
    ]
    for o in orgs:
        link = f"[{o['org']}]({o['url']})"
        lines.append(
            f"| {link} | {o['course_name'] or '-'} | {o['course_code'] or '-'} |"
        )
    lines.append("")
    lines.append(AUTOGEN_END)
    return "\n".join(lines)


def render_cohort_table(cohorts: list[dict]) -> str:
    """Render the cohort autogen section, bracketed by its own marker comments."""
    lines = [
        COHORT_START,
        "",
        f"_Auto-generated from GitHub. Discovered via topic `{COHORT_TOPIC}` on each org's `.github` repo; the course org is that org's `dsl-course.yml` `course:` pointer._",
        "",
        "| Cohort org | Course org |",
        "| --- | --- |",
    ]
    for c in cohorts:
        link = f"[{c['org']}]({c['url']})"
        course = (
            f"[{c['course']}](https://github.com/{c['course']})"
            if c["course"]
            else "_(orphaned)_"
        )
        lines.append(f"| {link} | {course} |")
    lines.append("")
    lines.append(COHORT_END)
    return "\n".join(lines)


def _replace_block(text: str, start: str, end: str, section: str, path: str) -> str:
    """Swap the `start`..`end` block in `text` for `section`. Unchanged if no markers."""
    start_idx = text.find(start)
    end_idx = text.find(end)

    if start_idx == -1 or end_idx == -1:
        log_err(
            f"markers not found in {path}. "
            f"Add `{start}` and `{end}` around the section "
            "you want auto-regenerated."
        )
        return text

    return text[:start_idx] + section + text[end_idx + len(end) :]


def update_file(path: str, blocks: list[tuple[str, str, str]]) -> bool:
    """Replace each `(start, end, section)` autogen block inside `path`.

    Returns True if the file changed. All blocks are applied against one read/write, so
    a missing marker for one block never discards the others.
    """
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        log_err(f"file not found: {path}")
        return False

    current = p.read_text()
    updated = current
    for start, end, section in blocks:
        updated = _replace_block(updated, start, end, section, path)

    if updated == current:
        return False

    p.write_text(updated)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "yaml"],
        default="json",
        help="Output format when writing to stdout. Default: json.",
    )
    parser.add_argument(
        "--update-file",
        default=None,
        help="Path to a Markdown file. Replaces the course block "
        f"({AUTOGEN_START}..{AUTOGEN_END}) and the cohort block "
        f"({COHORT_START}..{COHORT_END}).",
    )
    args = parser.parse_args()

    orgs = discover_course_orgs()
    cohorts = discover_cohort_orgs()

    if args.update_file:
        changed = update_file(
            args.update_file,
            [
                (AUTOGEN_START, AUTOGEN_END, render_markdown_table(orgs)),
                (COHORT_START, COHORT_END, render_cohort_table(cohorts)),
            ],
        )
        print(
            f"{'updated' if changed else 'no change'}: {args.update_file} "
            f"({len(orgs)} course orgs, {len(cohorts)} cohort orgs)"
        )
        return 0

    combined = {"course_orgs": orgs, "cohort_orgs": cohorts}
    if args.format == "json":
        print(json.dumps(combined, indent=2))
    elif args.format == "yaml":
        import yaml

        print(yaml.safe_dump(combined, sort_keys=False))
    else:
        print(render_markdown_table(orgs))
        print()
        print(render_cohort_table(cohorts))

    return 0


if __name__ == "__main__":
    sys.exit(main())
