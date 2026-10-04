"""Shared agent scaffolding: identity, logging, and the access agents get.

Every agent is a plain object with a `run` method. It gets the shared `Ledger`
and a `RunConfig` and nothing else — no agent holds a reference to another
agent. That is deliberate: the collaboration rules live in the orchestrator,
where they can be read in one sitting.
"""

from __future__ import annotations

import sys

from ..config import RunConfig
from ..ledger import Ledger


class Agent:
    role = "agent"
    name = "Agent"

    def __init__(self, config: RunConfig, ledger: Ledger):
        self.config = config
        self.ledger = ledger

    # ---------------------------------------------------------------- output
    def say(self, message: str) -> None:
        self._emit(f"  [{self.name}] {message}")

    def banner(self) -> None:
        self._emit(f"\n{self.name}")

    def _emit(self, text: str) -> None:
        if self.config.log is not None:
            self.config.log(text)
        if self.config.verbose:
            print(text, file=sys.stdout, flush=True)

    def announce(self, event: str, **detail) -> None:
        self.ledger.note(self.name, event, **detail)

    # ------------------------------------------------------------------ llm
    @property
    def llm_name(self) -> str:
        from ..llm import resolve_backend

        return resolve_backend(self.config.backend, self.config.model).name

    def has_llm(self) -> bool:
        return self.llm_name != "offline"