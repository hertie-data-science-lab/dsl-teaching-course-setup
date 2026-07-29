"""The Release materials button's input budget - one place for the arithmetic.

GitHub's `workflow_dispatch` accepts at most 10 inputs. The Release materials buttons
spend that budget on a fixed set of inputs plus two per discovered section (a
`release_<section>` checkbox and a `<section>_path` field - see
workflows_render._section_release_inputs), so how many sections can get checkboxes is a
DERIVED number, not an independent choice: MAX_RELEASE_SECTIONS falls out of the fixed
input count.

Keeping it derived here (rather than as a hand-maintained 3) means adding a fixed input
cannot silently eat a section slot: FIXED_RELEASE_INPUTS is asserted against the inputs
the central button actually renders (tests/test_renderers.py), so the arithmetic fails
loudly instead of drifting past 10.
"""

from __future__ import annotations

from .utils import log_err

# GitHub's hard cap on workflow_dispatch inputs.
GITHUB_MAX_DISPATCH_INPUTS = 10

# The inputs every Release materials button spends before any section gets a checkbox.
# `source_repo` only exists on the CENTRAL button (the run-from-repo one IS its source),
# so budgeting for it sizes both buttons off the tighter of the two.
FIXED_RELEASE_INPUTS = ("source_repo", "cohort_org", "sessions", "include_root_files")

# Each section costs a release_<section> checkbox + a <section>_path field.
INPUTS_PER_SECTION = 2


def section_slots(fixed_inputs: int = len(FIXED_RELEASE_INPUTS)) -> int:
    """How many sections can still get checkboxes, given `fixed_inputs` fixed ones."""
    return (GITHUB_MAX_DISPATCH_INPUTS - fixed_inputs) // INPUTS_PER_SECTION


MAX_RELEASE_SECTIONS = section_slots()


def cap_sections(sections: list[str], context: str) -> list[str]:
    """Sections beyond MAX_RELEASE_SECTIONS get no checkbox at all - GitHub's
    workflow_dispatch caps at 10 total inputs. Never silent: logs exactly what got
    dropped, so faculty & instructors know to release those directly
    (python3 -m dsl_course.release --destinations ...) instead of via the button."""
    sections = sorted(sections)
    if len(sections) <= MAX_RELEASE_SECTIONS:
        return sections
    dropped = sections[MAX_RELEASE_SECTIONS:]
    log_err(
        f"{context}: {len(sections)} sections found, only rendering checkboxes for "
        f"the first {MAX_RELEASE_SECTIONS} ({', '.join(sections[:MAX_RELEASE_SECTIONS])}) "
        f"- release {', '.join(dropped)} directly via "
        "`python3 -m dsl_course.release --destinations ...`."
    )
    return sections[:MAX_RELEASE_SECTIONS]
