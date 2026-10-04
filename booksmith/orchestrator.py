"""The orchestrator: every collaboration rule in the system lives here.

Agents never call each other. They read and write the shared ledger and return a
decision, and this file decides what happens next. Keeping the policy in one
readable place is what makes the design explainable in a walkthrough.

The shape of a run:

    Planner
        |
    Researcher  (one live pass over every candidate source)
        |
    for each chapter:                      <- two independent review loops
        |                                  share one bounded round budget
        +-- Writer
        +-- Editor  ---------> REVISE ----+
        +-- FactChecker ----> REJECT ----+   (the gate: it can stop a chapter)
        |
        +-- repeat while issues remain and rounds remain
        |
    Voicekeeper  (cross-chapter consistency; one more editorial pass if needed)
        |
    Assembler  (refuses to publish a chapter that never passed the gate)
"""

from __future__ import annotations

import sys
from pathlib import Path

from .config import RunConfig
from .ledger import Ledger
from .agents.editor import EditorAgent
from .agents.fact_checker import FactCheckerAgent
from .agents.planner import PlannerAgent
from .agents.researcher import ResearcherAgent
from .agents.voicekeeper import VoicekeeperAgent
from .agents.writer import WriterAgent
from .models import Draft, Issue, Severity, Verdict
from .render import render_book, render_html, render_preview, render_review, write_book
from .spec import BookSpec
from .visuals import write_assets


class Orchestrator:
    def __init__(self, config: RunConfig | None = None, spec: BookSpec | None = None):
        self.config = config or RunConfig()
        self.spec = spec or self.config.spec or BookSpec.from_dict(
            {"title": "Untitled", "introduction": "No book was specified."}
        )
        self.config.spec = self.spec
        self.ledger = Ledger()
        self.ledger.spec = self.spec
        self.ledger.brief = self.spec.to_brief()
        self.planner = PlannerAgent(self.config, self.ledger)
        self.researcher = ResearcherAgent(self.config, self.ledger)
        self.writer = WriterAgent(self.config, self.ledger)
        self.editor = EditorAgent(self.config, self.ledger)
        self.fact_checker = FactCheckerAgent(self.config, self.ledger)
        self.voicekeeper = VoicekeeperAgent(self.config, self.ledger)
        self.published: list[Draft] = []
        self.rejected: dict[int, list[Issue]] = {}
        self.figures: list[dict] = []

    # ------------------------------------------------------------------- run
    def run(self) -> int:
        self._heading(f"BookSmith: {self.spec.title}")
        self.ledger.decide(
            "Orchestrator", "run-start",
            f"{self.config.chapters} chapters, {self.config.max_rounds} review "
            f"rounds each, {self.config.min_words}-{self.config.max_words} words",
        )

        plan = self.planner.run()
        self.researcher.run()

        for chapter in plan.chapters:
            draft = self._run_chapter(chapter)
            if draft is not None:
                self.published.append(draft)

        self._voice_pass()

        return self._finish()

    # -------------------------------------------------------------- per chapter
    def _run_chapter(self, chapter) -> Draft | None:
        self._heading(f"Chapter {chapter.index}: {chapter.title}")
        notes: list[Issue] = []
        previous_body = ""

        for round_no in range(1, self.config.max_rounds + 1):
            self.say(f"round {round_no} of {self.config.max_rounds}")
            draft = self.writer.run(chapter, revision_notes=notes, revision=round_no - 1)
            draft.references = self.writer.references_for(draft)

            editor_report = self.editor.run(draft, round_no)
            fact_report = self.fact_checker.run(draft)

            notes = editor_report.blocking() + editor_report.major() \
                + fact_report.blocking()

            clean = (
                editor_report.verdict is Verdict.PASS
                and fact_report.verdict is Verdict.PASS
            )
            if clean:
                self.ledger.decide(
                    "Orchestrator", "chapter-converged",
                    f"ch{chapter.index} passed both reviews in round {round_no}",
                )
                self.say(f"converged after {round_no} round(s)")
                return draft

            body = self.editor.proposed_body(chapter.index, draft.body)
            if body != draft.body:
                draft.body = body.strip()

            if round_no == self.config.max_rounds:
                break

            # Two identical drafts in a row mean the remaining advice is not
            # something the Writer can act on - it needs a model to rewrite with.
            # Asking again would only spend the time to arrive at the same page.
            if body == previous_body and not any(
                i.severity is Severity.BLOCKING for i in notes
            ):
                self.ledger.decide(
                    "Orchestrator", "revision-no-progress",
                    f"ch{chapter.index}: round {round_no} produced the same prose as "
                    f"round {round_no - 1} while carrying only advisory issue(s) "
                    f"({', '.join(sorted({i.code for i in notes})[:4])}); stopping "
                    "rather than re-drafting the same text",
                )
                self.say(
                    "no progress is possible without a model; keeping this draft"
                )
                break
            previous_body = body
            self.say(
                f"returning to Writer with {len(notes)} instruction(s): "
                + ", ".join(sorted({n.code for n in notes})[:6])
            )

        blocking = [i for i in notes if i.severity is Severity.BLOCKING]
        if not blocking:
            # The gate is a blocking issue, not a clean sweep. Style advice that
            # nobody could act on without a model is recorded, not used to throw
            # away a chapter whose every number is sourced and verified.
            majors = [i for i in notes if i.severity is Severity.MAJOR]
            self.ledger.decide(
                "Orchestrator",
                "chapter-converged-with-notes" if majors else "chapter-converged",
                f"ch{chapter.index} had no blocking issue after "
                f"{self.config.max_rounds} rounds and was published"
                + (f", carrying {len(majors)} advisory issue(s): "
                   + ", ".join(sorted({i.code for i in majors})[:6]) if majors else ""),
            )
            self.say(
                f"published after {self.config.max_rounds} round(s) with no blocking "
                f"issue" + (f"; {len(majors)} advisory issue(s) noted" if majors else "")
            )
            return draft

        self.rejected[chapter.index] = notes
        self.ledger.decide(
            "Orchestrator", "chapter-withheld",
            f"ch{chapter.index} still had {len(blocking)} blocking issue(s) after "
            f"{self.config.max_rounds} rounds: "
            + ", ".join(sorted({i.code for i in blocking})[:6]),
        )
        self.say(
            f"WITHHELD: {len(blocking)} unresolved blocking issue(s) after "
            f"{self.config.max_rounds} rounds"
        )
        return None

    # ------------------------------------------------------------------ voices
    def _voice_pass(self) -> None:
        if len(self.published) < 2:
            return
        self._heading("Cross-chapter voice check")
        report = self.voicekeeper.run(self.published)
        if report.verdict is not Verdict.REVISE:
            self.ledger.decide(
                "Orchestrator", "voice-consistent",
                "all chapters share one register; no editorial pass needed",
            )
            return

        affected = sorted({
            issue.location
            for issue in report.major()
            if issue.location.startswith("ch")
        })
        if not affected:
            self.ledger.decide(
                "Orchestrator", "voice-advice-only",
                "voice differences were minor; recorded rather than rewritten",
            )
            return

        for location in affected:
            index = int(location[2:])
            chapter = next(
                (c for c in self.ledger.plan.chapters if c.index == index), None
            )
            if chapter is None:
                continue
            for round_no in range(1, self.config.voice_pass_rounds + 1):
                self.say(f"ch{index} voice pass {round_no}")
                draft = self.writer.run(
                    chapter,
                    revision_notes=report.major() + report.minor(),
                    revision=100 + round_no,
                )
                draft.references = self.writer.references_for(draft)
                draft.body = self.editor.proposed_body(index, draft.body)
                self.editor.run(draft, round_no)
                self.fact_checker.run(draft)
                self.ledger.drafts[index] = draft
            self.published = [
                self.ledger.drafts[d.chapter_index] for d in self.published
            ]

    # ----------------------------------------------------------------- output
    def _finish(self) -> int:
        out_dir = Path(self.config.out_dir)
        exit_code = 0

        if not self.published:
            self._heading("Result")
            self.say("no chapter passed the review gate; nothing was published")
            exit_code = 1
        else:
            self.figures = write_assets(out_dir, self.spec, self.ledger.claims)
            if self.figures:
                self.say(f"drew {len(self.figures)} figure(s) into {out_dir / 'assets'}")
            book = render_book(self.ledger, self.figures)
            path = write_book(out_dir / "book.md", book)
            page = write_book(out_dir / "book.html", render_html(self.ledger, self.figures))
            preview = write_book(
                out_dir / "preview.html", render_preview(self.ledger, self.figures)
            )
            self._heading("Result")
            self.say(f"wrote {path} ({len(self.published)} chapter(s))")
            self.say(f"wrote {page}")
            self.say(f"wrote {preview} (the book and its evidence in one file)")

        review = render_review(self.ledger)
        write_book(out_dir / "review.md", review)
        self.ledger.dump(out_dir / "ledger.json")

        stats = self.ledger.stats()
        self.say(
            f"sources verified {stats['sources_verified']}/{stats['sources_considered']}, "
            f"claims verified {stats['claims_verified']}/{stats['claims_total']}, "
            f"reviews {stats['reviews']}"
        )
        if self.rejected:
            self.say(
                f"withheld chapter(s): {sorted(self.rejected)} "
                f"({sum(len(v) for v in self.rejected.values())} unresolved issue(s))"
            )
            exit_code = 2 if not self.published else 1

        self.say(f"trace: {out_dir / 'ledger.json'}")
        self.say(f"review: {out_dir / 'review.md'}")
        return exit_code

    # ----------------------------------------------------------------- output
    def _heading(self, text: str) -> None:
        self._emit(f"\n{'=' * 72}\n{text}\n{'=' * 72}")

    def say(self, text: str) -> None:
        if self.config.verbose:
            self._emit(f"  {text}")

    def _emit(self, text: str) -> None:
        if self.config.log is not None:
            self.config.log(text)
        if self.config.verbose:
            print(text, file=sys.stdout, flush=True)