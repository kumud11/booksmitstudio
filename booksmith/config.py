"""Run configuration. Everything is overridable from the command line or env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

DEFAULT_OUT_DIR = "output"
DEFAULT_LOG_DIR = "output/trace"


@dataclass
class RunConfig:
    """Knobs the orchestrator reads. No magic numbers inside the agents."""

    out_dir: str = DEFAULT_OUT_DIR
    trace_dir: str = DEFAULT_LOG_DIR

    # The book being made. `None` means "use the bundled spec".
    spec: "object | None" = None

    # Called with every line of console output; the studio streams it to the page.
    log: Callable[[str], None] | None = None

    # Revision policy. Two review loops (editor, fact-checker) share one budget so
    # a pathological draft cannot loop forever.
    max_rounds: int = 3
    voice_pass_rounds: int = 1

    # Brief constraints, surfaced to the agents instead of hard-coded in prompts.
    chapters: int = 3
    min_words: int = 600
    max_words: int = 900
    target_words: int = 760

    # Network behaviour.
    request_timeout: int = 30
    fetch_workers: int = 8
    offline: bool = False           # skip all live fetching (air-gapped demos)
    verify_live: bool = True        # fact-checker re-fetches cited links

    # LLM backend: auto | offline | anthropic | openai | gemini
    backend: str = "auto"
    model: str | None = None

    llm_max_tokens: int = 4096
    llm_temperature: float = 0.3

    verbose: bool = True
    extras: dict = field(default_factory=dict)

    def env_flag(self, name: str) -> bool:
        return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}

    @property
    def do_fetch(self) -> bool:
        return not self.offline

    @property
    def do_verify_live(self) -> bool:
        return self.verify_live and not self.offline