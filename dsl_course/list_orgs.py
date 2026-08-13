"""list-orgs -- discover DSL course orgs dynamically from GitHub.

Source of truth: every course org's `.github` repo is tagged with the
topic `dsl-course-hub` (set by `bootstrap_course.py`). This tool searches
for that topic across all repos the caller can see, reads each org's
`.github/dsl-course.yml`, and emits a JSON / Markdown / YAML inventory.

Usage:
    python3 -m dsl_course.list_orgs                       # JSON to stdout
    python3 -m dsl_course.list_orgs --format markdown     # Markdown table
    python3 -m dsl_course.list_orgs --format yaml         # YAML
    python3 -m dsl_course.list_orgs --update-file PATH    # in-place MD update
"""

from __future__ import annotations

import argparse
import json
import sys

from .utils import gh, gh_json, log_err

COURSE_HUB_TOPIC = "dsl-course-hub"

AUTOGEN_START = "<!-- DSL-AUTOGEN-COURSE-ORGS-START -->"
AUTOGEN_END = "<!-- DSL-AUTOGEN-COURSE-ORGS-END -->"


def discover_course_orgs() -> list[dict]:
    """Find every `.github` repo tagged `dsl-course-hub` and fetch its metadata.

    Returns a list of dicts with keys: org, org_name, course_name, course_code, url.
    Sorted by org name.
    """
    results = gh_json(
        "search",
        "repos",
        f"topic:{COURSE_HUB_TOPIC}",
        "--limit",
        "100",
        "--json",
        "name,owner,url",
    )

    orgs = []
    for repo in results:
        if repo.get("name") != ".github":
            continue
        owner = (repo.get("owner") or {}).get("login", "")
        if not owner:
            continue

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


def update_file(path: str, new_section: str) -> bool:
    """Replace the autogen block inside `path`. Returns True if the file changed."""
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        log_err(f"file not found: {path}")
        return False

    current = p.read_text()
    start_idx = current.find(AUTOGEN_START)
    end_idx = current.find(AUTOGEN_END)

    if start_idx == -1 or end_idx == -1:
        log_err(
            f"markers not found in {path}. "
            f"Add `{AUTOGEN_START}` and `{AUTOGEN_END}` around the section "
            "you want auto-regenerated."
        )
        return False

    before = current[:start_idx]
    after = current[end_idx + len(AUTOGEN_END) :]
    updated = before + new_section + after

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
        help="Path to a Markdown file. Replaces content between "
        f"{AUTOGEN_START} and {AUTOGEN_END}.",
    )
    args = parser.parse_args()

    orgs = discover_course_orgs()

    if args.update_file:
        section = render_markdown_table(orgs)
        changed = update_file(args.update_file, section)
        print(
            f"{'updated' if changed else 'no change'}: {args.update_file} "
            f"({len(orgs)} course orgs)"
        )
        return 0

    if args.format == "json":
        print(json.dumps(orgs, indent=2))
    elif args.format == "yaml":
        import yaml

        print(yaml.safe_dump(orgs, sort_keys=False))
    else:
        print(render_markdown_table(orgs))

    return 0


if __name__ == "__main__":
    sys.exit(main())
