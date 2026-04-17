"""bootstrap-org (deprecated) — use bootstrap_course instead.

Kept for backward compatibility. All functionality moved to bootstrap_course.
"""

from .bootstrap_course import main

if __name__ == "__main__":
    import sys

    sys.exit(main())
