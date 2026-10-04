#!/usr/bin/env python3
"""Which model did `auto` pick, and will it answer in JSON?

    python tools/probe_model.py

The first thing to run when a book will not plan itself: it prints the backend
it resolved, the model id and the base URL, then asks that backend for a JSON
object. If this prints a timeout or an error, the problem is the model, not the
pipeline.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from booksmith import llm

backend = llm.resolve_backend("auto")
print("backend:", backend.name, backend.model, backend.base_url, flush=True)
t = time.time()
out = backend.complete(
    "You reply with JSON only.",
    'Reply with JSON only: {"ok": true, "note": "one sentence"}',
    max_tokens=120, json_mode=True,
)
print("reply:", out[:300])
print("parsed:", llm.try_json(out))
print("elapsed: %.1fs" % (time.time() - t))