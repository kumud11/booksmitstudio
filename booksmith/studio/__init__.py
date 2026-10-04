"""Booksmith Studio: the index page where a book is requested.

`python studio.py` serves a single page on localhost. You type a title and an
introduction; the Architect writes the rest of the plan with a language model and
the team runs the same pipeline the bundled book uses. Everything is written to
`books/<slug>/`, so every book stays on disk with its own spec, log and output.
"""

from __future__ import annotations

from .app import Studio, main, serve

__all__ = ["Studio", "main", "serve"]