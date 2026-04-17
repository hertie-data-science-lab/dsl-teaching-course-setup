"""dsl-course post-migrate -- retrospective cleanup of course orgs.

Implements Option H (ADR 0009): course org keeps materials; per-cohort
satellite orgs hold student submission repos.

Three phases:
    classify       -- inspect repos, write a migration manifest. No writes.
    tag-in-place   -- apply cohort/course/content-type topics to all repos,
                      privatise past-cohort public repos, optionally archive.
                      Destructive but reversible.
    migrate        -- transfer submission repos out of the course org into
                      their cohort satellite org. Destructive, partly reversible
                      (transfer can be reversed; the URL redirect is not).

Usage:
    # Phase 1 -- read-only, produces manifest
    python3 -m dsl_course.post_migrate \\
        --org Hertie-School-Deep-Learning-E1394 \\
        --phase classify

    # Phase 2 -- apply topics + privatise past cohorts
    python3 -m dsl_course.post_migrate \\
        --org Hertie-School-Deep-Learning-E1394 \\
        --phase tag-in-place \\
        --privatise-past-cohorts \\
        --execute

    # Phase 3 -- transfer submission repos to cohort satellite orgs
    #   Requires satellite orgs (hertie-dl-f2022 etc.) to exist already.
    python3 -m dsl_course.post_migrate \\
        --org Hertie-School-Deep-Learning-E1394 \\
        --phase migrate \\
        --satellite-prefix hertie-dl \\
        --execute
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from .utils import (
    archive_repo,
    current_mds_year,
    gh,
    gh_json,
    log,
    log_err,
    log_ok,
    log_step,
    set_repo_topics,
)

COHORT_PREFIX_RE = re.compile(r"^(?P<cohort>[fs]\d{4})[-_](?P<rest>.+)$")
COHORT_SUFFIX_RE = re.compile(r"^(?P<rest>.+)[-_](?P<cohort>[fs]\d{4})$")

SOLUTION_MARKERS = ("solution", "solutions")
SUBMISSION_MARKERS = (
    "problem-set",
    "problem_set",
    "ps-",
    "ps_",
    "assignment-",
    "group",
    "group-",
    "group_",
    "team",
    "team-",
    "team_",
    "ps1",
    "ps2",
    "ps3",
    "ps4",
)
LAB_MARKERS = (
    "tutorial",
    "lab",
    "workshop",
    "git-and-github",
    "object-oriented",
    "algorithm-analysis",
    "recursion",
    "demonstration",
)
TEMPLATE_MARKERS = ("template",)


def list_repos(org: str) -> list[dict[str, Any]]:
    """List all repos in an org. Paginates manually -- gh --paginate concatenates
    JSON arrays which json.loads rejects."""
    log_step(f"Listing repos in {org}")
    all_repos: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = gh_json(
            "api",
            f"orgs/{org}/repos?per_page=100&page={page}",
            "--jq",
            "[.[] | {name, private, archived, default_branch, description, "
            "topics, created_at, pushed_at, size, is_template}]",
        )
        if not batch:
            break
        all_repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    log_ok(f"found {len(all_repos)} repos")
    return all_repos


def parse_cohort(name: str) -> tuple[str | None, str]:
    """Split 'f2022-foo-bar' or 'content-f2025' -> (cohort, rest).
    Returns (None, name) if no match."""
    m = COHORT_PREFIX_RE.match(name)
    if m:
        return m.group("cohort"), m.group("rest")
    m = COHORT_SUFFIX_RE.match(name)
    if m:
        return m.group("cohort"), m.group("rest")
    return None, name


STOPWORDS = {
    "submission",
    "tutorial",
    "tutorials",
    "assignment",
    "assignments",
    "problem",
    "set",
    "sets",
    "lab",
    "labs",
    "workshop",
    "workshops",
    "group",
    "team",
    "groups",
    "teams",
    "content",
    "course",
    "solutions",
    "solution",
    "new",
    "old",
    "fall",
    "spring",
    "summer",
    "winter",
    "deep",
    "learning",
    "machine",
    "hertie",
    "school",
    "data",
    "science",
    "session",
    "last",
    "final",
    "midterm",
}


def _looks_like_person_or_group_token(tok: str) -> bool:
    """Heuristic: is this trailing token a student/group identifier?

    Examples that should return True:
      'group-a', 'groupc', 'ps1', 'ps-1-a', 'grp4', 'ps3_group_e',
      'lonny-aditi-franco-dom' (multi-name group), 'nadine-dominik-week6-demo',
      student usernames like 'psharratt', 'elkaele'.
    Examples that should return False:
      '1', '2', 'solutions', 'tutorial', 'assignment', 'problem-set-2'.
    """
    low = tok.lower().replace("_", "-")
    if not low:
        return False
    if low.isdigit():
        return False
    # Strip numeric-only suffixes like "-1", "-2"
    parts = [p for p in low.split("-") if p]
    if not parts:
        return False
    # Contains group/team/ps markers + something after
    if any(
        p
        in (
            "group",
            "team",
            "grp",
            "groupa",
            "groupb",
            "ps",
            "ps1",
            "ps2",
            "ps3",
            "ps4",
        )
        for p in parts
    ):
        return True
    if any(re.match(r"^(group|team|grp|ps)[a-z0-9]", p) for p in parts):
        return True
    if any(re.match(r"^ps[-_]?\d", p) for p in parts):
        return True
    # If every segment is a stopword, NOT a person/group
    if all(p in STOPWORDS for p in parts):
        return False
    # Looks like a username: has a non-stopword alpha segment
    non_stopword = [p for p in parts if p not in STOPWORDS and not p.isdigit()]
    return bool(non_stopword)


def classify_content_type(rest: str, is_template: bool = False) -> str:
    """Assign ONE content-type tag by priority order.

    rest: the repo name with cohort prefix stripped.
    Returns one of: solutions, template, submission, lab, course-content, other.
    """
    lower = rest.lower()

    # Priority 1: solutions
    if any(m in lower for m in SOLUTION_MARKERS):
        return "solutions"

    # Priority 2: GitHub-flagged templates are explicit
    if is_template:
        return "template"

    # Priority 3: does name contain a group/team/ps marker AND a known
    # assignment/tutorial/lab type? That's a submission.
    # Normalise underscores to dashes for part-splitting.
    normalised = rest.replace("_", "-").lower()
    parts = [p for p in normalised.split("-") if p]
    has_assignment_type = any(
        m in normalised
        for m in (
            *SUBMISSION_MARKERS,
            "tutorial",
            "lab",
            "workshop",
            "demonstration",
            "demo",
        )
    )
    has_group_token = any(
        re.match(r"^(group|team|grp|ps)[a-z0-9]*$", p) for p in parts
    ) or any(re.match(r"^ps\d+$", p) for p in parts)
    if has_assignment_type and has_group_token:
        return "submission"

    # Priority 3b: does the trailing 1-2 tokens look like a student/group
    # identifier on top of an assignment/tutorial stem?
    if len(parts) >= 3:
        last_two = "-".join(parts[-2:])
        last_one = parts[-1]
        if _looks_like_person_or_group_token(
            last_one
        ) or _looks_like_person_or_group_token(last_two):
            stem = "-".join(parts[:-1])
            if any(
                m in stem
                for m in (
                    *SUBMISSION_MARKERS,
                    "tutorial",
                    "lab",
                    "workshop",
                    "demonstration",
                    "demo",
                )
            ):
                return "submission"

    # Priority 4: generic submission-marker presence with no clear suffix ->
    # instructor-master course content
    submission_marker_present = any(m in lower for m in SUBMISSION_MARKERS)
    if submission_marker_present:
        return "course-content"

    # Priority 5: labs / tutorials / workshops
    if any(m in lower for m in LAB_MARKERS):
        return "lab"

    # Priority 6: catch-all course material
    return "course-content"


def content_type_disposition(ctype: str) -> str:
    """Under Option H: is this repo a 'material' (stays) or 'submission' (moves)?"""
    if ctype in ("submission",):
        return "move-to-cohort-org"
    if ctype in ("solutions", "template", "lab", "course-content", "other"):
        return "keep-in-course-org"
    return "keep-in-course-org"


def build_manifest(
    org: str,
    course_code: str,
    satellite_prefix: str | None,
) -> dict[str, Any]:
    """Classify every repo in an org and build a manifest."""
    repos = list_repos(org)
    current = f"f{current_mds_year()}"

    classified: list[dict[str, Any]] = []
    summary: dict[str, int] = {}
    cohort_counts: dict[str, int] = {}

    for r in repos:
        name = r["name"]
        cohort, rest = parse_cohort(name)
        is_template = bool(r.get("is_template")) or "template" in name.lower()
        ctype = classify_content_type(rest, is_template=is_template)
        disposition = content_type_disposition(ctype)

        is_past_cohort = cohort is not None and cohort < current

        # Where to move it, if applicable
        dest_org = None
        if disposition == "move-to-cohort-org" and cohort is not None:
            if satellite_prefix:
                dest_org = f"{satellite_prefix}-{cohort}"
            else:
                dest_org = f"TBD-{cohort}"

        proposed_topics = sorted(
            {
                f"cohort-{cohort}" if cohort else "cohort-unknown",
                f"course-{course_code.lower().replace('grad-', '').replace('_', '-')}",
                ctype,
            }
        )

        entry = {
            "name": name,
            "cohort": cohort,
            "content_type": ctype,
            "disposition": disposition,
            "destination_org": dest_org,
            "current_private": r["private"],
            "current_archived": r["archived"],
            "is_past_cohort": is_past_cohort,
            "proposed_topics": proposed_topics,
            "proposed_private": (
                True if (is_past_cohort and not r["private"]) else r["private"]
            ),
            "proposed_archived": r["archived"],  # never auto-archive in classify
            "existing_topics": r.get("topics") or [],
            "description": r.get("description") or "",
            "default_branch": r.get("default_branch") or "main",
            "pushed_at": r.get("pushed_at", "")[:10],
        }

        classified.append(entry)
        summary[ctype] = summary.get(ctype, 0) + 1
        if cohort:
            cohort_counts[cohort] = cohort_counts.get(cohort, 0) + 1

    manifest = {
        "org": org,
        "course_code": course_code,
        "satellite_prefix": satellite_prefix,
        "current_cohort": current,
        "summary_by_content_type": summary,
        "summary_by_cohort": dict(sorted(cohort_counts.items())),
        "repos": classified,
    }
    return manifest


def manifest_path(org: str) -> Path:
    slug = org.lower().replace("_", "-")
    return Path(__file__).parent.parent / "inventory" / f"{slug}-migration-manifest.yml"


def write_manifest(manifest: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False, allow_unicode=True)
    log_ok(f"manifest written: {path}")


def phase_classify(
    org: str,
    course_code: str,
    satellite_prefix: str | None,
) -> int:
    manifest = build_manifest(org, course_code, satellite_prefix)
    path = manifest_path(org)
    write_manifest(manifest, path)

    log("")
    log(f"=== Classification summary for {org} ===")
    log(f"Current cohort (auto): {manifest['current_cohort']}")
    log("")
    log("By content type:")
    for ctype, count in sorted(
        manifest["summary_by_content_type"].items(), key=lambda kv: -kv[1]
    ):
        log(f"  {count:>4}  {ctype}")
    log("")
    log("By cohort:")
    for cohort, count in manifest["summary_by_cohort"].items():
        log(f"  {count:>4}  {cohort}")
    log("")
    disposition_counts: dict[str, int] = {}
    for r in manifest["repos"]:
        disposition_counts[r["disposition"]] = (
            disposition_counts.get(r["disposition"], 0) + 1
        )
    log("Proposed disposition (Option H):")
    for d, n in sorted(disposition_counts.items(), key=lambda kv: -kv[1]):
        log(f"  {n:>4}  {d}")
    log("")
    public_past = sum(
        1 for r in manifest["repos"] if r["is_past_cohort"] and not r["current_private"]
    )
    log(f"Public repos in past cohorts (would be privatised): {public_past}")
    log("")
    log(f"Next step: review {path}, then run --phase tag-in-place.")
    return 0


def load_manifest(org: str) -> dict[str, Any]:
    path = manifest_path(org)
    if not path.exists():
        log_err(f"Manifest not found: {path}. Run --phase classify first.")
        sys.exit(1)
    with path.open() as f:
        return yaml.safe_load(f)


def set_private(org: str, repo: str) -> bool:
    code, out = gh(
        "api",
        "--method",
        "PATCH",
        f"repos/{org}/{repo}",
        "--field",
        "private=true",
    )
    if code == 0:
        return True
    log_err(f"failed to privatise {org}/{repo}: {out[:200]}")
    return False


def phase_tag_in_place(
    org: str,
    privatise_past_cohorts: bool,
    archive_past_cohorts: bool,
    execute: bool,
) -> int:
    manifest = load_manifest(org)
    repos = manifest["repos"]

    log_step(
        f"tag-in-place on {org} "
        f"({'EXECUTE' if execute else 'DRY-RUN'}; "
        f"privatise={privatise_past_cohorts}; archive={archive_past_cohorts})"
    )

    tagged = 0
    privatised = 0
    archived = 0

    for r in repos:
        name = r["name"]
        proposed_topics = r["proposed_topics"]
        existing = set(r["existing_topics"])
        will_tag = set(proposed_topics) != existing

        will_privatise = (
            privatise_past_cohorts and r["is_past_cohort"] and not r["current_private"]
        )
        will_archive = (
            archive_past_cohorts and r["is_past_cohort"] and not r["current_archived"]
        )

        if not (will_tag or will_privatise or will_archive):
            continue

        actions = []
        if will_tag:
            actions.append(f"topics={proposed_topics}")
        if will_privatise:
            actions.append("privatise")
        if will_archive:
            actions.append("archive")

        prefix = "EXECUTE" if execute else "DRY-RUN"
        log(f"  [{prefix}] {name}: {', '.join(actions)}")

        if not execute:
            continue

        if will_tag:
            if set_repo_topics(org, name, proposed_topics):
                tagged += 1
        if will_privatise:
            if set_private(org, name):
                privatised += 1
        if will_archive:
            if archive_repo(org, name):
                archived += 1

    log("")
    if execute:
        log_ok(
            f"tag-in-place done: {tagged} tagged, "
            f"{privatised} privatised, {archived} archived"
        )
    else:
        log("dry-run only -- rerun with --execute to apply.")
    return 0


def transfer_repo(org: str, repo: str, new_owner: str) -> bool:
    code, out = gh(
        "api",
        "--method",
        "POST",
        f"repos/{org}/{repo}/transfer",
        "--field",
        f"new_owner={new_owner}",
    )
    if code == 0:
        return True
    log_err(f"failed to transfer {org}/{repo} -> {new_owner}: {out[:200]}")
    return False


def org_exists(org: str) -> bool:
    code, _ = gh("api", f"orgs/{org}")
    return code == 0


def phase_migrate(org: str, execute: bool) -> int:
    manifest = load_manifest(org)
    to_move = [r for r in manifest["repos"] if r["disposition"] == "move-to-cohort-org"]

    log_step(
        f"migrate on {org} ({'EXECUTE' if execute else 'DRY-RUN'}); "
        f"{len(to_move)} repos to move"
    )

    # Summarise
    by_dest: dict[str, int] = {}
    for r in to_move:
        by_dest[r["destination_org"]] = by_dest.get(r["destination_org"], 0) + 1
    for d, n in sorted(by_dest.items()):
        log(f"  {n:>4}  ->  {d}")

    # Validate destination orgs exist
    dest_orgs = sorted({r["destination_org"] for r in to_move if r["destination_org"]})
    missing = [d for d in dest_orgs if not org_exists(d)]
    if missing:
        log("")
        log_err(
            f"Destination orgs do not exist: {missing}. "
            f"Create them (or have an org Owner create them) before running migrate."
        )
        if not execute:
            log("dry-run: showing plan only; create the missing orgs before --execute.")
        return 1 if execute else 0

    if not execute:
        log("")
        log("dry-run only -- rerun with --execute to apply.")
        return 0

    moved = 0
    failed = 0
    for r in to_move:
        name = r["name"]
        dest = r["destination_org"]
        if transfer_repo(org, name, dest):
            log_ok(f"  transferred {name} -> {dest}")
            moved += 1
        else:
            failed += 1

    log("")
    log_ok(f"migrate done: {moved} transferred, {failed} failed")
    return 0 if failed == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True, help="Course org name")
    parser.add_argument(
        "--phase",
        required=True,
        choices=["classify", "tag-in-place", "migrate"],
    )
    parser.add_argument(
        "--course-code",
        default="",
        help="e.g. GRAD-E1394 (used for course-* topic; inferred from org if omitted)",
    )
    parser.add_argument(
        "--satellite-prefix",
        default=None,
        help="Prefix for cohort satellite orgs e.g. 'hertie-dl' "
        "-> hertie-dl-f2022, hertie-dl-f2023, ...",
    )
    parser.add_argument(
        "--privatise-past-cohorts",
        action="store_true",
        help="(tag-in-place) flip public past-cohort repos to private",
    )
    parser.add_argument(
        "--archive-past-cohorts",
        action="store_true",
        help="(tag-in-place) archive any past-cohort repo",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="(tag-in-place, migrate) apply changes; default is dry-run",
    )
    args = parser.parse_args()

    # Infer course code from org name if not given
    course_code = args.course_code
    if not course_code:
        m = re.search(r"([CE]\d+)$", args.org)
        if m:
            course_code = f"GRAD-{m.group(1)}"
        else:
            course_code = "GRAD-UNKNOWN"

    if args.phase == "classify":
        return phase_classify(args.org, course_code, args.satellite_prefix)
    if args.phase == "tag-in-place":
        return phase_tag_in_place(
            args.org,
            args.privatise_past_cohorts,
            args.archive_past_cohorts,
            args.execute,
        )
    if args.phase == "migrate":
        return phase_migrate(args.org, args.execute)
    return 1


if __name__ == "__main__":
    sys.exit(main())
