"""Editor agent.

Runs the deterministic brief-compliance validators first, because those are
objective and cheap, then optionally asks a language model for a stylistic pass.
Anything the model returns is re-validated: an Editor cannot mark its own edits as
clean, because every edit goes back through the same checks.
"""

from __future__ import annotations

import re

from ..llm import LLMError, resolve_backend
from ..models import Draft, Issue, Report, Severity, Verdict
from ..validators import check_draft, count_words
from .base import Agent

SYSTEM = (
    "You are the Editor of a small book-production team. You edit one chapter of a "
    "friendly, evidence-led guide. You check grammar, spelling, punctuation, tone "
    "and readability. You are encouraging but exacting: plain English, short "
    "sentences, no jargon, no hype, no lists inside the prose. You never change a "
    "number and never add a fact. Reply with JSON only."
)

PASSABLE = {Severity.MINOR}


class EditorAgent(Agent):
    role = "editor"
    name = "Editor"

    def run(self, draft: Draft, round_no: int = 1) -> Report:
        report = Report(agent=self.name)

        issues = check_draft(draft, self.ledger.brief, self._glossary())
        report.issues.extend(issues)
        report.metrics["words"] = str(count_words(draft.body))
        report.metrics["citations"] = str(len(draft.references))
        report.metrics["paragraphs"] = str(
            len([p for p in draft.body.split("\n\n") if p.strip()])
        )
        report.metrics["round"] = str(round_no)
        report.metrics["backend"] = draft.backend

        if self.has_llm() and not any(
            i.severity is Severity.BLOCKING for i in issues
        ):
            self._llm_style_pass(draft, report)

        report.verdict = self._verdict(report)
        self._say(draft, report)
        self.ledger.record_report(report, draft.chapter_index)
        return report

    # ----------------------------------------------------------------- checks
    def _glossary(self) -> dict:
        if self.ledger.plan and self.ledger.plan.glossary:
            return self.ledger.plan.glossary
        from ..knowledge.brief import GLOSSARY

        return GLOSSARY

    def _verdict(self, report: Report) -> Verdict:
        if any(i.severity is Severity.BLOCKING for i in report.issues):
            return Verdict.REJECT
        if any(i.severity is Severity.MAJOR for i in report.issues):
            return Verdict.REVISE
        return Verdict.PASS

    # --------------------------------------------------------------- llm pass
    def _llm_style_pass(self, draft: Draft, report: Report) -> None:
        backend = resolve_backend(self.config.backend, self.config.model)
        prompt = (
            f"Chapter {draft.chapter_index}. Voice: "
            f"{self.ledger.plan.voice if self.ledger.plan else ''}\n"
            f"Reader: {self.ledger.brief.get('audience', '')}\n\n"
            f"{draft.body}\n\n"
            "Return JSON: {\"edits\":[{\"quote\":\"exact words to change\","
            "\"replacement\":\"better wording\","
            "\"reason\":\"why\",\"severity\":\"major|minor\"}],"
            "\"notes\":\"one-sentence assessment\"}\n"
            "Only propose changes to wording, rhythm or clarity. Never introduce or "
            "alter a number, a citation marker or a factual statement. If the prose is "
            "already good, return an empty edits list."
        )
        try:
            raw = backend.complete(
                SYSTEM, prompt, max_tokens=self.config.llm_max_tokens,
                temperature=0.2, json_mode=True,
            )
        except LLMError as exc:
            report.metrics["style_pass"] = f"unavailable: {exc}"
            return

        from ..llm import try_json

        data = try_json(raw) or {}
        edits = data.get("edits") or []
        applied, rejected = 0, 0
        body = draft.body
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            quote = str(edit.get("quote", "")).strip()
            replacement = str(edit.get("replacement", "")).strip()
            if not quote or not replacement or quote not in body:
                rejected += 1
                continue
            if CITATION_RE.search(quote) and quote.replace(replacement, "") != quote:
                rejected += 1
                continue
            if NUMBER_RE.search(quote) != NUMBER_RE.search(replacement):
                rejected += 1
                continue
            body = body.replace(quote, replacement, 1)
            applied += 1

        report.metrics["style_edits_applied"] = str(applied)
        report.metrics["style_edits_rejected"] = str(rejected)
        report.metrics["style_notes"] = str(data.get("notes", ""))[:160]
        if body != draft.body:
            # The Editor never edits in place. It hands a corrected draft back and
            # the orchestrator decides, so the revision is auditable.
            self.ledger.decide(
                self.name, "style-edits",
                f"ch{draft.chapter_index}: {applied} wording change(s) proposed",
            )
            self._proposed_bodies = getattr(self, "_proposed_bodies", {})
            self._proposed_bodies[draft.chapter_index] = body

    def proposed_body(self, chapter_index: int, fallback: str) -> str:
        return getattr(self, "_proposed_bodies", {}).get(chapter_index, fallback)

    # ---------------------------------------------------------------- logging
    def _say(self, draft: Draft, report: Report) -> None:
        counts = (
            f"{len(report.blocking())} blocking, "
            f"{len(report.major())} major, {len(report.minor())} minor"
        )
        self.say(
            f"ch{draft.chapter_index}: {count_words(draft.body)} words, "
            f"{len(draft.references)} refs -> {report.verdict.value.upper()} ({counts})"
        )
        for issue in report.blocking() + report.major():
            hint = f" | {issue.hint}" if issue.hint else ""
            self.say(f"    [{issue.severity.value}] {issue.code}: {issue.message}{hint}")


CITATION_RE = re.compile(r"\[\d+\]")
NUMBER_RE = re.compile(r"\d")


def _num(text: str) -> set:
    return {m.group(0) for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", text or "")}


_ = (Issue, PASSABLE)