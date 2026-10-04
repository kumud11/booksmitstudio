"""Planner agent.

Turns the brief into a spine: three chapters, each with a purpose, an ordered
list of movements, and the *claim slots* it needs evidence for. Those slots are
the contract between the Planner and the Researcher - the Planner never names a
source, it only names the questions it wants answered.

In LLM mode the model drafts the outline, which is then validated against a hard
schema and merged over a curated skeleton. The skeleton is not a fallback for a
lazy model; it is the floor the model has to clear.
"""

from __future__ import annotations

from ..knowledge.brief import BRIEF, GLOSSARY
from ..knowledge.outline import SKELETON
from ..llm import LLMError, try_json
from ..models import BookPlan, ChapterPlan, Movement
from .base import Agent


class PlannerAgent(Agent):
    role = "planner"
    name = "Planner"

    SYSTEM = (
        "You are the Planner of a small book-production team. You turn a publishing "
        "brief into a chapter-by-chapter outline for a friendly, evidence-led guide. "
        "You never invent sources and you never write the prose. Reply with JSON only."
    )

    def run(self, brief: dict | None = None) -> BookPlan:
        self.banner()
        if brief is not None:
            self.ledger.brief = brief
        if not self.ledger.brief:
            # Only fall back to the bundled brief when nobody has set one.
            self.ledger.brief = BRIEF
        b = self.ledger.brief

        plan = self._from_spine(b)
        self.say(f"outline: {len(plan.chapters)} chapters, "
                 f"{sum(len(c.movements) for c in plan.chapters)} movements")

        if self.has_llm():
            try:
                enriched = self._with_llm(plan, b)
                plan = enriched
                self.say("model refined chapter titles, purposes and openers")
            except LLMError as exc:
                self.say(f"LLM unavailable ({exc}); keeping the book's own outline")

        self._validate(plan, b)
        self.ledger.plan = plan
        self.ledger.decide(
            self.name,
            "outline-approved",
            f"{len(plan.chapters)} chapters, "
            f"{len({s for c in plan.chapters for m in c.movements for s in m.slots})} "
            "evidence slots requested",
        )
        self.announce("plan_ready", chapters=len(plan.chapters))
        for chapter in plan.chapters:
            self.say(f"ch{chapter.index}: {chapter.title} "
                     f"({len(chapter.movements)} movements)")
        return plan

    # ------------------------------------------------------------------ build
    def _spine(self) -> list[dict]:
        """The book's own outline, or the bundled one if there is no spec yet."""
        if self.ledger.spec is not None and self.ledger.spec.chapter_specs():
            return self.ledger.spec.chapter_specs()
        return [
            {
                "title": chapter["title"],
                "purpose": chapter["purpose"],
                "movements": [
                    {
                        "key": step[0],
                        "intent": step[1],
                        "slots": list(step[2]) if len(step) > 2 else [],
                        "terms": list(step[3]) if len(step) > 3 else [],
                    }
                    for step in chapter["movements"]
                ],
            }
            for chapter in SKELETON
        ]

    def _from_spine(self, brief: dict) -> BookPlan:
        target = int((brief["min_words"] + brief["max_words"]) / 2)
        target = max(brief["min_words"] + 60, min(brief["max_words"] - 60, target))
        chapters = []
        for i, spec in enumerate(self._spine(), start=1):
            movements = [
                Movement(
                    key=f"ch{i}.{step['key']}",
                    intent=step["intent"],
                    slots=tuple(step["slots"]),
                    terms=tuple(step["terms"]),
                )
                for step in spec["movements"]
            ]
            chapters.append(
                ChapterPlan(
                    index=i,
                    title=spec["title"],
                    purpose=spec["purpose"],
                    movements=movements,
                    target_words=target,
                    must_cover=[m.intent for m in movements],
                )
            )
        return BookPlan(
            title=brief["title"],
            audience=brief["audience"],
            voice=brief["voice"],
            chapters=chapters,
            glossary=dict(GLOSSARY),
            notes="Structure is fixed; only titles, purposes and openers may vary.",
        )

    def _with_llm(self, plan: BookPlan, brief: dict) -> BookPlan:
        from ..llm import resolve_backend

        backend = resolve_backend(self.config.backend, self.config.model)
        skeleton_dump = [
            {
                "chapter": c.index,
                "current_title": c.title,
                "purpose": c.purpose,
                "movements": [{"key": m.key, "intent": m.intent} for m in c.movements],
            }
            for c in plan.chapters
        ]
        prompt = (
            f"BRIEF\n{brief['title']}\nAudience: {brief['audience']}\n"
            f"Chapters: exactly {brief['chapters']}. Each {brief['min_words']}-"
            f"{brief['max_words']} words. Voice: {brief['voice']}\n\n"
            f"EXISTING OUTLINE\n{skeleton_dump}\n\n"
            "Rewrite the titles, purposes and the 'open' and 'close' movement intents. "
            "Keep the movement keys and their order exactly as they are, keep the same "
            "number of movements, and keep every fact slot untouched. Make the titles "
            f"concrete and appetising for {brief['audience'].lower()}.\n"
            'Reply as JSON: {"chapters":[{"index":1,"title":"...","purpose":"...",'
            '"open":"...","close":"..."}]}'
        )
        raw = backend.complete(
            self.SYSTEM, prompt, max_tokens=2000, temperature=self.config.llm_temperature,
            json_mode=True,
        )
        data = try_json(raw)
        if not isinstance(data, dict) or "chapters" not in data:
            raise LLMError("planner reply was not usable JSON")

        by_index = {}
        for entry in data["chapters"]:
            try:
                by_index[int(entry["index"])] = entry
            except (KeyError, TypeError, ValueError):
                continue

        for chapter in plan.chapters:
            entry = by_index.get(chapter.index)
            if not entry:
                continue
            title = str(entry.get("title", "")).strip()
            purpose = str(entry.get("purpose", "")).strip()
            if title:
                chapter.title = title
            if purpose:
                chapter.purpose = purpose
            for movement in chapter.movements:
                tail = movement.key.split(".")[-1]
                replacement = str(entry.get(tail, "")).strip()
                if replacement:
                    movement.intent = replacement
        return plan

    # ----------------------------------------------------------------- checks
    def _validate(self, plan: BookPlan, brief: dict) -> None:
        problems = []
        if len(plan.chapters) != brief["chapters"]:
            problems.append(f"expected {brief['chapters']} chapters, got {len(plan.chapters)}")
        for chapter in plan.chapters:
            if not chapter.movements:
                problems.append(f"chapter {chapter.index} has no movements")
            if not (brief["min_words"] <= chapter.target_words <= brief["max_words"]):
                problems.append(
                    f"chapter {chapter.index} target {chapter.target_words} outside "
                    f"{brief['min_words']}-{brief['max_words']}"
                )
            for movement in chapter.movements:
                if len(movement.intent) < 20:
                    problems.append(f"movement {movement.key} has a vague intent")
            slots = {s for m in chapter.movements for s in m.slots}
            if len(slots) < 3:
                problems.append(
                    f"chapter {chapter.index} asks for {len(slots)} evidence slot(s); "
                    "it cannot be evidenced"
                )
        slots = {
            s
            for c in plan.chapters
            for m in c.movements
            for s in m.slots
        }
        if len(slots) < 8:
            problems.append(f"only {len(slots)} evidence slots requested; outline is thin")
        if problems:
            raise ValueError("planner produced an invalid outline: " + "; ".join(problems))