"""Shared test helpers.

The package imports cleanly without network (the gh/git calls only fire when a function
runs), so tests import dsl_course modules directly and exercise the PURE logic: the
workflow renderers (their output must be GitHub-parseable YAML) and the content
transforms in site/release. The thin gh/git orchestration is deliberately NOT mocked -
that only asserts we wrote the call we wrote; its real failure modes need a live org.
"""

from __future__ import annotations

import yaml


def workflow_inputs(rendered: str) -> dict:
    """Parse a rendered workflow and return its `workflow_dispatch.inputs`.

    PyYAML follows YAML 1.1, where the bare key `on:` parses to boolean True, so the
    top-level trigger key is `True`, not the string "on" (GitHub's own parser is fine
    with `on:`). Accept either so the test asserts real structure, not the quirk."""
    doc = yaml.safe_load(rendered)
    trigger = doc.get("on", doc.get(True))
    return trigger["workflow_dispatch"].get("inputs") or {}


def workflow_jobs(rendered: str) -> dict:
    return yaml.safe_load(rendered)["jobs"]
