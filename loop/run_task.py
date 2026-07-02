# ABOUTME: CLI entrypoint for preparing and verifying agent-docs loop runs.
# ABOUTME: Delegates implementation details to loop.runner for testability.

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loop.runner import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
