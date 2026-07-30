"""Where the central toolkit lives.

Every seeded workflow checks this repo out and runs its engine code from it (see
workflows_render), and the generated READMEs link back to it (see profile_readme) - so
both sides must name the same repo/ref. One definition, imported by both.
"""

from __future__ import annotations

CENTRAL = "hertie-data-science-lab/dsl-teaching-course-setup"
# Seeded workflows run the engine code from this ref of the central repo.
CENTRAL_REF = "main"
