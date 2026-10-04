#!/usr/bin/env python3
"""Start the Booksmith Studio index page.

    python studio.py

Opens http://127.0.0.1:8765/ where you type a book's title and introduction. The
Architect plans the rest, the team writes it, and the files land in
`books/<slug>/output/`.

    python studio.py --port 9000 --backend anthropic --no-browser
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from booksmith.studio.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())