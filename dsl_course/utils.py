"""Shared utilities for dsl_course tools."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from typing import Any


RATE_LIMIT_MARKERS = (
    "secondary rate limit",
    "api rate limit exceeded",
    "abuse detection",
)


def gh(*args: str, stdin: str | None = None, retries: int = 3) -> tuple[int, str]:
    """Run a gh CLI command. Returns (returncode, stdout+stderr).

    Retries on GitHub secondary rate limits with exponential backoff.
    """
    import time

    delay = 30
    for attempt in range(retries + 1):
        result = subprocess.run(
            ["gh"] + list(args),
            capture_output=True,
            text=True,
            input=stdin,
        )
        out = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return result.returncode, out
        lower = out.lower()
        is_rate_limited = any(m in lower for m in RATE_LIMIT_MARKERS)
        if not is_rate_limited or attempt == retries:
            return result.returncode, out
        print(
            f"  [wait] rate-limited, retry {attempt + 1}/{retries} in {delay}s",
            flush=True,
        )
        time.sleep(delay)
        delay *= 2
    return result.returncode, out


def gh_json(*args: str) -> Any:
    """Run a gh CLI command and parse JSON stdout. Raises on failure."""
    result = subprocess.run(
        ["gh"] + list(args),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh command failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def git(*args: str, cwd: str | None = None) -> tuple[int, str]:
    """Run a git command."""
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def log(msg: str) -> None:
    print(msg, flush=True)


def log_step(msg: str) -> None:
    print(f"\n-> {msg}", flush=True)


def log_ok(msg: str) -> None:
    print(f"  [ok] {msg}", flush=True)


def log_skip(msg: str) -> None:
    print(f"  [skip] {msg} (already exists)", flush=True)


def log_err(msg: str) -> None:
    print(f"  [err] {msg}", file=sys.stderr, flush=True)


def repo_exists(org: str, name: str) -> bool:
    code, _ = gh("api", f"repos/{org}/{name}")
    return code == 0


def get_default_branch(org: str, name: str) -> str:
    """Return the default branch of a repo. Falls back to 'main'."""
    code, out = gh("api", f"repos/{org}/{name}", "--jq", ".default_branch")
    if code == 0 and out:
        return out
    return "main"


def extract_logins(entries: list | None) -> list[str]:
    """Normalise a list of roster entries (dict or str) to GitHub logins."""
    if not entries:
        return []
    out = []
    for e in entries:
        if isinstance(e, str):
            if e:
                out.append(e)
        elif isinstance(e, dict):
            login = e.get("github", "").strip()
            if login:
                out.append(login)
    return out


def create_team(
    org: str, name: str, description: str = "", privacy: str = "closed"
) -> bool:
    """Create a team. Idempotent — treats 422 'already exists' as success.
    Returns True if a team with this name now exists.
    """
    code, out = gh(
        "api",
        "--method",
        "POST",
        f"orgs/{org}/teams",
        "--field",
        f"name={name}",
        "--field",
        f"description={description}",
        "--field",
        f"privacy={privacy}",
    )
    if code == 0:
        log_ok(f"team created: {name}")
        return True
    if "already exists" in out.lower() or "422" in out:
        log_skip(f"team {name}")
        return True
    log_err(f"failed to create team {name}: {out[:200]}")
    return False


def add_team_member(org: str, team_slug: str, login: str, role: str = "member") -> bool:
    code, out = gh(
        "api",
        "--method",
        "PUT",
        f"orgs/{org}/teams/{team_slug}/memberships/{login}",
        "--field",
        f"role={role}",
    )
    if code == 0:
        return True
    log_err(f"failed to add {login} to {team_slug}: {out[:100]}")
    return False


def create_repo(
    org: str,
    name: str,
    private: bool = True,
    description: str = "",
    is_template: bool = False,
) -> bool:
    """Create a repo. Idempotent — treats existing repo as success."""
    args = [
        "api",
        "--method",
        "POST",
        f"orgs/{org}/repos",
        "--field",
        f"name={name}",
        "--field",
        f"private={str(private).lower()}",
        "--field",
        f"is_template={str(is_template).lower()}",
    ]
    if description:
        args += ["--field", f"description={description}"]
    code, out = gh(*args)
    if code == 0:
        log_ok(f"repo created: {org}/{name}")
        return True
    if "name already exists" in out.lower() or "422" in out:
        log_skip(f"repo {org}/{name}")
        return True
    log_err(f"failed to create repo {org}/{name}: {out[:200]}")
    return False


def put_file(org: str, repo: str, path: str, content: bytes, message: str) -> bool:
    """Create or update a file via the Contents API.

    Updates require the existing file's SHA; we fetch it first if present.
    """
    b64 = base64.b64encode(content).decode()
    args = [
        "api",
        "--method",
        "PUT",
        f"repos/{org}/{repo}/contents/{path}",
        "--field",
        f"message={message}",
        "--field",
        f"content={b64}",
    ]
    # If the file already exists, fetch its SHA (required for update)
    code, sha = gh(
        "api",
        f"repos/{org}/{repo}/contents/{path}",
        "--jq",
        ".sha",
    )
    if code == 0 and sha:
        args += ["--field", f"sha={sha}"]
    code, out = gh(*args)
    if code == 0:
        return True
    log_err(f"failed to put {path}: {out[:200]}")
    return False


def get_file_content(org: str, repo: str, path: str) -> str | None:
    """Fetch a file's decoded text content. Returns None if not found."""
    code, out = gh(
        "api",
        f"repos/{org}/{repo}/contents/{path}",
        "--jq",
        ".content | @base64d",
    )
    if code != 0:
        return None
    return out


def semester_label(semester: str) -> str:
    """'f2025' -> 'Fall 2025', 's2026' -> 'Spring 2026'."""
    code = semester[0].lower()
    year = semester[1:]
    season = {"f": "Fall", "s": "Spring"}.get(code, code.upper())
    return f"{season} {year}"


def current_mds_year() -> int:
    """Current MDS cohort year. Hertie academic year starts 1 August."""
    from datetime import date

    today = date.today()
    if today.month >= 8:
        return today.year
    return today.year - 1


def set_repo_topics(org: str, repo: str, topics: list[str]) -> bool:
    """Replace the full topic list on a repo (GitHub limit: 20 topics, lowercase kebab)."""
    normalised = sorted({t.lower().replace("_", "-") for t in topics if t})
    args = [
        "api",
        "--method",
        "PUT",
        f"repos/{org}/{repo}/topics",
        "-H",
        "Accept: application/vnd.github+json",
    ]
    for t in normalised:
        args += ["--field", f"names[]={t}"]
    code, out = gh(*args)
    if code == 0:
        return True
    log_err(f"failed to set topics on {org}/{repo}: {out[:200]}")
    return False


def add_collaborator(org: str, repo: str, login: str, permission: str = "push") -> bool:
    """Add a collaborator to a repo. permission: pull | triage | push | maintain | admin."""
    code, out = gh(
        "api",
        "--method",
        "PUT",
        f"repos/{org}/{repo}/collaborators/{login}",
        "--field",
        f"permission={permission}",
    )
    if code == 0:
        return True
    log_err(f"failed to add {login} to {org}/{repo}: {out[:200]}")
    return False


def archive_repo(org: str, repo: str) -> bool:
    code, out = gh(
        "api",
        "--method",
        "PATCH",
        f"repos/{org}/{repo}",
        "--field",
        "archived=true",
    )
    if code == 0:
        return True
    log_err(f"failed to archive {org}/{repo}: {out[:200]}")
    return False


def generate_from_template(
    template_org: str,
    template_name: str,
    owner: str,
    name: str,
    private: bool = True,
    description: str = "",
) -> bool:
    """Create a repo from a template. Idempotent."""
    code, out = gh(
        "api",
        "--method",
        "POST",
        f"repos/{template_org}/{template_name}/generate",
        "-H",
        "Accept: application/vnd.github+json",
        "--field",
        f"owner={owner}",
        "--field",
        f"name={name}",
        "--field",
        f"private={str(private).lower()}",
        "--field",
        f"description={description}",
    )
    if code == 0:
        return True
    if "name already exists" in out.lower():
        log_skip(f"repo {owner}/{name}")
        return True
    log_err(f"failed to generate {owner}/{name} from template: {out[:200]}")
    return False
