"""Writer agent.

The Writer is deliberately the most constrained agent in the team. It never sees
a search engine and it never invents a fact. It receives a *claim card pack*:
only the statements the Researcher verified, together with the exact figures
lifted from the pages, and it is required to express nothing else.

Two backends:

* `offline` (default when no API key is present) walks the planned movements in
  order and assembles them from the authored prose bank, binding every figure to
  a captured value. It depends entirely on the research having succeeded: a
  missing claim shortens the chapter, and the validators then fail it.
* `llm` asks the model to write the chapter from the same claim cards, with the
  same hard rules, then the identical validators run over the result.

Either way the Writer owns citation numbering. Symbolic `{{cite:alias}}` markers
become `[n]` in order of first appearance, and the reference list is generated
from the source that actually backs each one.
"""

from __future__ import annotations

import re

from ..knowledge.prose import ALIASES, MOVEMENTS, PROSE_BANKS, Fact
from ..llm import LLMError, resolve_backend
from ..models import ChapterPlan, Claim, Draft, Issue, Severity, citations_in, numeric_tokens
from ..validators import count_words, unexplained_numbers
from .base import Agent

CITE_RE = re.compile(r"\[\[cite:([A-Za-z0-9_.:-]+)\]\]")

SYSTEM = (
    "You are the Writer of a small book-production team. You write one chapter of a "
    "friendly, evidence-led guide. You are given a set of verified fact cards. Rules "
    "you must not break:\n"
    "1. Use ONLY facts present in the cards. Never add a figure, date, name or "
    "percentage that is not in a card.\n"
    "2. Copy numbers from the cards exactly as printed there, including Indian digit "
    "grouping if shown.\n"
    "3. Attach the citation marker [[cite:alias]] at the end of every sentence that "
    "states a fact or figure. Use the alias given in the card.\n"
    "4. Flowing prose only. No bullet points, no numbered lists, no headings, no "
    "tables, no bold text.\n"
    "5. Explain any technical term the first time it appears, in the same sentence or "
    "the next.\n"
    "6. Plain English, short sentences, warm and encouraging, like a patient mentor. No "
    "jargon, no press-release language, no hype.\n"
    "7. Do not write the 'Takeaway:' line or the reference list. Those are added "
    "afterwards.\n"
    "Return only the chapter prose."
)


class WriterAgent(Agent):
    role = "writer"
    name = "Writer"

    def run(self, chapter: ChapterPlan, revision_notes: list[Issue] | None = None,
            revision: int = 0) -> Draft:
        facts, notes = self._build_cards(chapter)
        if revision:
            self.say(
                f"revision {revision}: {len(notes)} instruction(s) to apply "
                f"({', '.join(sorted({n.code for n in notes})) or 'none'})"
            )

        if self.has_llm():
            try:
                body = self._llm_draft(chapter, facts, notes)
                backend = "llm"
                self.say(f"drafted {count_words(body)} words via {self.llm_name}")
            except LLMError as exc:
                body = self._offline_draft(chapter, facts)
                backend = "offline(fallback)"
                self.say(f"LLM draft failed ({exc}); used offline composer")
        else:
            body = self._offline_draft(chapter, facts)
            backend = "offline"
            self.say(f"drafted {count_words(body)} words via offline composer")

        if not body.strip():
            notes.append(Issue(
                Severity.BLOCKING, "no-prose-path",
                "this book has no authored prose bank and no language model is "
                "configured, so the chapter cannot be written",
                f"ch{chapter.index}", "note_only",
                "Set a model API key, or ask the Architect for a book whose outline "
                "can be written by a model.",
            ))

        body, references = self._resolve_citations(body, facts, chapter)

        # The length limit is a hard rule of the brief, so it is enforced on every
        # round rather than only on the round the Editor complained about it.
        body = self._trim_to_brief(body, chapter)

        if revision_notes:
            body = self._apply_mechanical_fixes(body, revision_notes, chapter)

        body, references = self._prune_unused(body, references)
        body = self._drop_unsupported_paragraphs(body, references, chapter)
        body, references = self._prune_unused(body, references)

        takeaway = self._takeaway(chapter, facts)
        draft = Draft(
            chapter_index=chapter.index,
            title=chapter.title,
            body=body.strip(),
            takeaway=takeaway,
            references=references,
            reference_map={int(r["n"]): r for r in references},
            claim_ids_used=sorted({
                claim_id
                for ref in references
                for claim_id in (ref.get("claim_ids") or [ref.get("claim_id", "")])
                if claim_id
            }),
            backend=backend,
            revision=revision,
        )
        self.ledger.put_draft(draft)
        self.announce("draft", chapter=chapter.index, words=count_words(body),
                      backend=backend, revision=revision,
                      citations=len(references))
        return draft

    def _prune_unused(self, body: str, references: list[dict]) -> tuple[str, list[dict]]:
        """Renumber so the reference list matches the markers that survived.

        Mechanical fixes can drop the last sentence of a paragraph, which can take a
        citation with it. Rather than leave a dangling entry, renumber from what is
        actually in the text.
        """
        order: list[int] = []
        for match in re.finditer(r"\[(\d{1,3})\]", body):
            n = int(match.group(1))
            if n in order:
                continue
            order.append(n)
        if order == sorted(order) and len(order) == len(references):
            return body, references

        remap = {old: new for new, old in enumerate(order, start=1)}
        by_n = {int(r["n"]): r for r in references}
        kept = []
        for old in order:
            ref = dict(by_n.get(old, {}))
            ref.pop("n", None)
            ref["n"] = remap[old]
            kept.append(ref)

        def shift(match: re.Match) -> str:
            old = int(match.group(1))
            return f"[{remap[old]}]" if old in remap else ""

        return re.sub(r"\[(\d{1,3})\]", shift, body), kept

    # ------------------------------------------------------------ claim cards
    def movements(self) -> dict:
        """The authored prose for the book being made, if it has any.

        A spec names its bank. With no spec at all - someone running the agents by
        hand - the bundled book is assumed, which is what every caller did before
        books could be planned.
        """
        spec = self.ledger.spec
        name = spec.prose_bank if spec is not None else "upi"
        return PROSE_BANKS.get(name, {})

    def _build_cards(self, chapter: ChapterPlan) -> tuple[dict, list[Issue]]:
        """Resolve this chapter's usable facts to named cards.

        Two routes, in order of preference:

        * An authored prose bank for this book, where each movement names the
          aliases it wants. That is the bundled book, and it needs no model.
        * Otherwise the verified claims for the chapter's evidence slots, keyed by
          claim id. This is the route a book created from the studio uses, and it
          requires a language model to turn cards into prose.
        """
        movements = self.movements()
        prose_movements = [m for m in chapter.movements if m.key in movements]
        if prose_movements:
            return self._cards_from_prose(chapter, prose_movements)
        return self._cards_from_slots(chapter, [])

    def _cards_from_prose(self, chapter: ChapterPlan, movements) -> tuple[dict, list[Issue]]:
        bank = self.movements()
        aliases: set[str] = set()
        for movement in movements:
            aliases |= _aliases_in(bank[movement.key])

        facts: dict[str, Fact] = {}
        notes: list[Issue] = []
        for alias in sorted(aliases):
            claim = None
            for candidate in ALIASES.get(alias, ()):
                claim = self.ledger.claims.get(candidate)
                if claim is not None and claim.verified:
                    break
                claim = None
            if claim is None:
                notes.append(Issue(
                    Severity.BLOCKING, "evidence-missing",
                    f"no verified source for '{alias}', so this fact was left out",
                    f"ch{chapter.index}", "note_only",
                    "Researcher must verify a source for this slot.",
                ))
                continue
            source = self.ledger.source(claim.source_keys[0]) if claim.source_keys else None
            facts[alias] = Fact(claim, source)

        self.say(
            f"ch{chapter.index}: {len(facts)}/{len(aliases)} claim cards available "
            f"from {len({f.key for f in facts.values()})} source(s)"
        )
        return facts, notes

    def _cards_from_slots(self, chapter: ChapterPlan, notes: list[Issue]) -> tuple[dict, list[Issue]]:
        """Cards from the chapter's evidence slots, keyed by claim id."""
        wanted = sorted({s for m in chapter.movements for s in m.slots})
        facts: dict[str, Fact] = {}
        for claim in self.ledger.claims_for_chapter(chapter.index):
            source = self.ledger.source(claim.source_keys[0]) if claim.source_keys else None
            facts[claim.id] = Fact(claim, source)
        if wanted and not facts:
            notes.append(Issue(
                Severity.BLOCKING, "evidence-missing",
                f"none of the {len(wanted)} evidence slot(s) this chapter needs "
                f"({', '.join(wanted[:5])}) could be verified from a live source",
                f"ch{chapter.index}", "note_only",
                "The Architect must propose sources whose pages really carry these "
                "figures.",
            ))
        self.say(
            f"ch{chapter.index}: {len(facts)}/{len(wanted)} slot(s) filled "
            f"from {len({f.key for f in facts.values()})} source(s)"
        )
        return facts, notes

    # ---------------------------------------------------------------- offline
    def _has_prose_bank(self, chapter: ChapterPlan) -> bool:
        return any(m.key in self.movements() for m in chapter.movements)

    def _offline_draft(self, chapter: ChapterPlan, facts: dict) -> str:
        if not self._has_prose_bank(chapter):
            return self._compose_from_cards(chapter, facts)
        bank = self.movements()
        paragraphs: list[str] = []
        for movement in chapter.movements:
            fn = bank.get(movement.key)
            if fn is None:
                continue
            produced = fn(facts)
            for para in produced:
                if para.strip():
                    paragraphs.append(" ".join(para.split()))
        return "\n\n".join(paragraphs)

    def _compose_from_cards(self, chapter: ChapterPlan, facts: dict) -> str:
        """Assemble a chapter from verified claim cards, with no model.

        This is not writing. Every sentence is either a connective that says only
        what the cards say, or the card's own sentence from the source, so a
        chapter built this way can be checked line by line: the numbers are the
        publisher's, the links are live, and no judgement has been smuggled in.
        It is what keeps the studio usable on a machine with no model at all.
        """
        if not facts:
            self.ledger.decide(
                self.name, "no-cards",
                f"ch{chapter.index}: no verified claim cards, so no chapter could be "
                "composed offline",
            )
            return ""

        self.ledger.decide(
            self.name, "offline-compose",
            f"ch{chapter.index}: composed {len(facts)} verified claim(s) into prose "
            "with no language model, so the text asserts nothing the sources do not",
        )
        paragraphs: list[str] = []

        for movement in chapter.movements:
            for card in self._cards_for_movement(movement, facts):
                paragraphs.append(
                    _cited(_after_attribution(card.sentence()), card.id)
                )

        if not paragraphs:
            return ""

        opening = self._opening(chapter, facts)
        if opening:
            paragraphs.insert(0, opening)
        paragraphs.append(self._closing(chapter, facts))
        return "\n\n".join(p for p in paragraphs if p.strip())

    def _cards_for_movement(self, movement, facts: dict) -> list[Fact]:
        """The cards this movement asked for, by slot name or by claim id."""
        if not movement.slots:
            return []
        # The spec maps "source:probe" to a slot; the cards are keyed by claim id,
        # so the lookup has to run the other way.
        by_slot = {
            slot: claim_id
            for claim_id, slot in (self.ledger.spec.probe_slots or {}).items()
        } if self.ledger.spec else {}
        chosen: list[Fact] = []
        seen: set[str] = set()
        for slot in movement.slots:
            fact = facts.get(slot) or facts.get(by_slot.get(slot, slot))
            if fact is None or fact.claim.id in seen:
                continue
            seen.add(fact.claim.id)
            chosen.append(fact)
        return chosen

    OPENERS = (
        "Before you take anything in {title} on trust, here is what {org} "
        "actually publishes about {topic}. Every figure below carries the reference "
        "it was read from, and every reference is a page you can open and check "
        "yourself.",
        "This chapter is built entirely from figures that {org} publishes about "
        "{topic}. Each one is quoted with its source attached, so you can read the "
        "original wording rather than take this book's word for it.",
        "Nothing in this chapter is asserted without a source. What follows is what "
        "{org} publishes about {topic}, figure by figure, with the page each figure "
        "was read from named beside it.",
    )

    def _opening(self, chapter: ChapterPlan, facts: dict) -> str:
        title = self.ledger.spec.title if self.ledger.spec else chapter.title
        lead = facts[next(iter(facts))]
        org = lead.org or "the cited sources"
        template = self.OPENERS[(chapter.index - 1) % len(self.OPENERS)]
        return template.format(
            title=title, org=org, topic=_soft_lower(chapter.title),
        )

    def _closing(self, chapter: ChapterPlan, facts: dict) -> str:
        return (
            f"Read those figures together and you have the measured part of "
            f"{_soft_lower(chapter.title)}: what has been counted, by whom, and how much. "
            f"Where you plan to rely on one of these numbers, open its reference and "
            f"read it there - that is where a stale figure will show itself, and "
            f"where you can put it right if it is wrong."
        )

    # -------------------------------------------------------------------- llm
    def _llm_draft(self, chapter: ChapterPlan, facts: dict, notes: list[Issue]) -> str:
        backend = resolve_backend(self.config.backend, self.config.model)
        cards = "\n".join(f"- {alias}: {fact.render()}" for alias, fact in sorted(facts.items()))
        movements = "\n".join(
            f"  - {m.key.split('.')[-1]}: {m.intent}" for m in chapter.movements
        )
        terms = sorted({t for m in chapter.movements for t in m.terms})
        brief = self.ledger.brief
        instruction = ""
        if notes:
            instruction = "\n\nEDITS REQUIRED FROM REVIEW:\n" + "\n".join(
                f"  - [{n.code}] {n.message}" for n in notes if n.severity in
                (Severity.BLOCKING, Severity.MAJOR)
            )
        prompt = (
            f"BOOK: {self.ledger.plan.title if self.ledger.plan else brief.get('title', '')}\n"
            f"CHAPTER {chapter.index} of {brief.get('chapters', 3)}\n"
            f"Working title: {chapter.title}\n"
            f"Purpose: {chapter.purpose}\n"
            f"Length: {self.config.target_words} words "
            f"(hard limit {self.config.min_words}-{self.config.max_words}). "
            f"Write at least {len(chapter.movements)} short paragraphs so the length "
            "comes from breadth, not padding.\n"
            f"Voice: {self.ledger.plan.voice if self.ledger.plan else ''}\n"
            f"Reader: {brief.get('audience', '')}\n\n"
            f"MOVEMENTS TO COVER, IN THIS ORDER:\n{movements}\n\n"
            + (f"TERMS TO EXPLAIN ON FIRST USE: {', '.join(terms)}\n\n" if terms else "")
            + f"VERIFIED FACT CARDS (the only facts you may use):\n{cards}\n"
            f"{instruction}\n"
            "Write the chapter prose now. Mark every factual sentence with the "
            "[[cite:alias]] token for the card it came from, using the alias exactly "
            "as printed on the card."
        )
        text = backend.complete(
            SYSTEM, prompt, max_tokens=self.config.llm_max_tokens,
            temperature=self.config.llm_temperature,
        )
        return _clean_llm_prose(text)

    # ------------------------------------------------------------- citations
    def _resolve_citations(self, body: str, facts: dict, chapter: ChapterPlan) -> str:
        """Turn [[cite:alias]] into [n] in order of first appearance.

        Numbering is per *source page*, not per claim: a page that carries three
        figures gets one reference number, not three identical-looking entries.
        Every claim behind that number is kept in `claim_ids` so the FactChecker
        still re-reads the page once per figure.
        """
        numbering: dict[str, int] = {}
        references: list[dict] = []
        missing: list[str] = []
        where = f"ch{chapter.index}"

        def substitute(match: re.Match) -> str:
            alias = match.group(1)
            fact = facts.get(alias)
            if fact is None:
                missing.append(alias)
                return ""
            claim = self.ledger.claims.get(fact.id)
            source = self.ledger.source(fact.key)
            if claim is None or source is None:
                missing.append(alias)
                return ""
            page_key = _page_key(source)
            if page_key not in numbering:
                numbering[page_key] = len(numbering) + 1
                references.append({
                    "n": numbering[page_key],
                    "alias": alias,
                    "claim_id": fact.id,
                    "claim_ids": [fact.id],
                    "source_key": fact.key,
                    "org": source.org,
                    "title": source.title,
                    "url": source.url,
                    "published": source.published,
                    "tier": source.tier,
                    "link_status": source.status,
                })
            elif fact.id not in references[numbering[page_key] - 1]["claim_ids"]:
                references[numbering[page_key] - 1]["claim_ids"].append(fact.id)
            return f"[{numbering[page_key]}]"

        resolved = CITE_RE.sub(substitute, body)
        resolved = re.sub(r"\s+([.,;:])", r"\1", resolved)
        resolved = re.sub(r" {2,}", " ", resolved)
        resolved = re.sub(r"\[\s*\]", "", resolved)
        resolved = re.sub(r" +\n", "\n", resolved)

        if missing:
            self.ledger.decide(
                self.name, "citation-dropped",
                f"{where}: dropped marker(s) for {sorted(set(missing))} because no "
                "verified source backs them",
            )
        self.say(
            f"{where}: {len(references)} source page(s) cited from "
            f"{len({c for r in references for c in r.get('claim_ids', [r['claim_id']])})} "
            "claim(s)"
        )
        return resolved, references

    def references_for(self, draft: Draft) -> list[dict]:
        """Rebuild the reference list from the draft's resolved citation map."""
        out = []
        for n, ref in sorted(draft.reference_map.items()):
            if ref.get("url"):
                out.append(dict(ref))
        return out

    # ------------------------------------------------------------- takeaway
    CURATED_CLOSERS = {
        1: "Takeaway: UPI is now ordinary, worldwide in scale and free for you to "
           "accept, so put your QR code where customers can reach it, keep it clean "
           "and say the amount aloud as you take each payment.",
        2: "Takeaway: Accepting UPI costs you nothing, the money lands straight away "
           "and small merchants keep zero charges, so the real cost of not joining "
           "is the customers you cannot take money from.",
        3: "Takeaway: Failed payments have deadlines, complaints have a free route "
           "and fraud is concentrated in large payments, so keep your records, "
           "answer quickly and treat every UPI payment as carefully as cash.",
    }

    def _takeaway(self, chapter: ChapterPlan, facts: dict) -> str:
        if self._has_prose_bank(chapter):
            return self.CURATED_CLOSERS.get(
                chapter.index,
                "Takeaway: review this chapter's figures before acting on them.",
            )
        if not self.has_llm():
            return self._composed_takeaway(chapter, facts)
        return self._llm_takeaway(chapter, facts)

    def _composed_takeaway(self, chapter: ChapterPlan, facts: dict) -> str:
        """The takeaway a reader can act on when nobody wrote one.

        With no model there is no way to be clever here, so it says the true thing
        about the chapter: what it rests on, and what to do with it.
        """
        if not facts:
            return ""
        orgs = sorted({fact.org for fact in facts.values() if fact.org})
        count = len({fact.claim.id for fact in facts.values()})
        who = orgs[0] if len(orgs) == 1 else " and ".join(orgs[:2]) if orgs else "the sources"
        return (
            f"Takeaway: {count} figure{'' if count == 1 else 's'} here come from "
            f"{who}, and each one can be checked at its own link; treat them as the "
            "measured part of the story, not the whole of it."
        )

    def _llm_takeaway(self, chapter: ChapterPlan, facts: dict) -> str:
        """One line the reader could act on today, in the book's own voice.

        Deterministic when a prose bank exists so every chapter of the bundled book
        matches; model-written for a book authored from the studio.
        """
        if not self.has_llm():
            return ""
        from ..llm import resolve_backend

        backend = resolve_backend(self.config.backend, self.config.model)
        cards = "\n".join(
            f"- {fact.render()}" for _, fact in sorted(facts.items())[:12]
        )
        prompt = (
            f"BOOK: {self.ledger.plan.title if self.ledger.plan else ''}\n"
            f"Chapter {chapter.index}: {chapter.title}\n"
            f"Purpose: {chapter.purpose}\n"
            f"Voice: {self.ledger.plan.voice if self.ledger.plan else ''}\n\n"
            f"FACTS THE CHAPTER STANDS ON:\n{cards}\n\n"
            "Write ONE sentence, at most 35 words, that tells the reader the single "
            "most useful thing to do after reading this chapter. Begin it with "
            "'Takeaway: '. No numbers that are not in the facts above. Return only "
            "that sentence."
        )
        try:
            raw = backend.complete(
                SYSTEM, prompt, max_tokens=300, temperature=0.4
            )
        except LLMError as exc:
            self.say(f"takeaway not written: {exc}")
            return ""
        cleaned = _clean_llm_prose(raw).strip()
        line = cleaned.splitlines()[0] if cleaned else ""
        line = line.strip().strip('"').strip()
        if not line:
            return ""
        if not line.lower().startswith("takeaway:"):
            line = "Takeaway: " + line[0].lower() + line[1:]
        return line

    # --------------------------------------------------------- revision fixes
    def _trim_to_brief(self, body: str, chapter: ChapterPlan) -> str:
        """Cut to the brief's ceiling before anyone reviews it.

        Waiting for the Editor to complain wastes a whole round, and by then the
        Writer has already spent a model call producing prose it must throw away.
        """
        over_by = count_words(body) - self.config.max_words
        if over_by <= 0:
            return body
        self.ledger.decide(
            self.name, "trim-for-length",
            f"ch{chapter.index}: {over_by} word(s) over the brief's "
            f"{self.config.max_words}-word limit; cutting the paragraphs that carry "
            "the least",
        )
        paragraphs = [p for p in body.split("\n\n") if p.strip()]
        return "\n\n".join(self._trim_to(paragraphs, self.config.max_words - 20))

    def _apply_mechanical_fixes(self, body: str, notes: list[Issue],
                                chapter: ChapterPlan) -> str:
        """Apply the fixes the Writer can make without a language model.

        Citation repair, length trimming and list flattening are mechanical. Style
        opinions are not, so they are handed back to the Editor as advisory rather
        than silently ignored.
        """
        kinds = {n.fix_kind for n in notes if n.fix_kind}
        paragraphs = [p for p in body.split("\n\n") if p.strip()]

        if "flatten_prose" in kinds:
            flattened = []
            for para in paragraphs:
                flat = re.sub(r"^\s*(?:[-*+•]|\d+[.)])\s+", "", para)
                flat = flat.replace("**", "")
                flat = re.sub(r"^#{1,6}\s+", "", flat)
                flattened.append(flat)
            paragraphs = flattened

        if "fix_typo" in kinds:
            paragraphs = [re.sub(r"\s{2,}", " ", p) for p in paragraphs]
            paragraphs = [re.sub(r"\s+([.,;:!?])", r"\1", p) for p in paragraphs]

        # The length limit is a hard rule of the brief, so it is enforced every
        # round rather than only on the round the Editor complained about it.
        over_by = count_words("\n\n".join(paragraphs)) - self.config.max_words
        if over_by > 0:
            self.ledger.decide(
                self.name, "trim-for-length",
                f"ch{chapter.index}: {over_by} word(s) over the brief's "
                f"{self.config.max_words}-word limit",
            )
            paragraphs = self._trim_to(paragraphs, self.config.max_words - 20)

        body = "\n\n".join(paragraphs)

        if "pad_to_length" in kinds and count_words(body) < self.config.min_words + 40:
            self.ledger.decide(
                self.name, "cannot-pad",
                f"ch{chapter.index}: no verified evidence left to expand the chapter "
                "without risking an unsourced claim",
            )
        return body

    def _trim_to(self, paragraphs: list[str], target: int) -> list[str]:
        """Shorten a chapter by dropping whole paragraphs, never sentences.

        The opening and the closing paragraph always stay: they carry the voice
        and the mentor framing the brief asks for. From the middle, the least
        load-bearing go first - a paragraph carrying no citation of its own is the
        one whose loss costs the reader least, and among equals the longest is
        the most compressible.
        """
        if len(paragraphs) <= 2:
            return paragraphs
        first, last = paragraphs[0], paragraphs[-1]
        middle = paragraphs[1:-1]
        budget = target - count_words(first) - count_words(last)
        if budget <= 0:
            return [first, last]

        keep = list(middle)
        over = count_words("\n\n".join([first] + keep + [last])) - target
        while over > 0 and keep:
            thinnest = min(
                range(len(keep)),
                key=lambda i: (len(set(CITE_RE.findall(keep[i]))), -count_words(keep[i])),
            )
            over -= count_words(keep.pop(thinnest))
        return [first] + keep + [last]

    def _drop_unsupported_paragraphs(self, body: str, references: list[dict],
                                      chapter: ChapterPlan) -> str:
        """Cut any paragraph holding a figure the chapter's citations cannot cover.

        Trimming removes paragraphs, and a removed paragraph takes its citation
        with it. A neighbour that leaned on that citation for a date is then left
        holding an unsourced number, which the FactChecker will reject. Rather
        than ship a fragment, the Writer drops it and records why.

        The allowed set is the chapter's, exactly as the FactChecker builds it, so
        this pass can never cut a paragraph the gate would have accepted.
        """
        allowed: dict[str, str] = {}
        for ref in references:
            for claim in _claims_of(ref, self.ledger):
                allowed[claim.id] = claim.text
                for name, value in claim.values.items():
                    allowed[f"{claim.id}:{name}"] = value
                source = self.ledger.source(ref.get("source_key", ""))
                for probe_key, record in (source.evidence if source else {}).items():
                    for token in numeric_tokens(record.get("match", "")):
                        allowed[f"{claim.id}:{probe_key}:evidence"] = token
            for token in numeric_tokens(str(ref.get("published", ""))):
                allowed[f"{ref.get('n')}:published"] = token

        bad = set(unexplained_numbers(body, allowed))
        if not bad:
            return body

        kept: list[str] = []
        dropped: list[str] = []
        for para in body.split("\n\n"):
            if not para.strip():
                continue
            unsupported = sorted(set(unexplained_numbers(para, allowed)) & bad)
            if unsupported:
                dropped.append(f"{unsupported[:3]} in {para.strip()[:60]!r}")
                continue
            kept.append(para)

        if dropped:
            self.ledger.decide(
                self.name, "unsupported-numbers-cut",
                f"ch{chapter.index}: dropped {len(dropped)} paragraph(s) whose "
                f"figures no citation in the chapter covers ({', '.join(sorted(bad)[:5])}): "
                + "; ".join(dropped[:2]),
            )
        return "\n\n".join(kept)


# ------------------------------------------------------------------- helpers

_ATTRIBUTION_RE = re.compile(
    r"^(?P<lead>[A-Z][\w&.\- ]{1,40}? (?:reports?|says?|states?|notes?|records?|"
    r"published|write|writes|found|show|shows) that )(?P<rest>.+)$"
)
_PLAIN_OPENER_RE = re.compile(r"^[A-Z][a-z]")


def _soft_lower(text: str) -> str:
    """Lowercase a phrase for use mid-sentence, leaving names alone.

    "P2M transactions" and "UPI volumes" keep their capitals; "Monthly volumes"
    becomes "monthly volumes".
    """
    words = str(text or "").split(" ", 1)
    if words and _PLAIN_OPENER_RE.match(words[0]):
        words[0] = words[0][0].lower() + words[0][1:]
    return " ".join(words)


def _after_attribution(sentence: str) -> str:
    """Lower the case where a source's own sentence is quoted into ours.

    "PIB reports that Monthly volumes..." reads as a title, not a sentence. Only
    the first letter changes; every word and figure is left exactly as published.
    """
    match = _ATTRIBUTION_RE.match(sentence or "")
    if not match:
        return sentence
    rest = match.group("rest")
    first = rest.split(" ", 1)[0]
    # Only a plain sentence opener loses its capital: "P2M", "UPI" and "FY26"
    # are names, not starts of sentences. `istitle()` is no help - it calls "P2M"
    # title case - so the test is an upper case letter followed by a lower one.
    # An adverb in front of a comma ("Further, as of...") keeps it too, because
    # it is not the start of the sentence, only of the clause.
    if not rest or "," in first or not _PLAIN_OPENER_RE.match(first):
        return sentence
    return match.group("lead") + rest[0].lower() + rest[1:]


def _cited(sentence: str, alias: str) -> str:
    """A sentence with its citation token attached where the prose bank puts it."""
    text = " ".join(str(sentence or "").split())
    if not text:
        return ""
    text = text.rstrip(".。").rstrip("…").rstrip(".")
    pieces = _split_long(text)
    return " ".join(p if p.endswith((".", "!", "?")) else p + "." for p in pieces) \
        + f" [[cite:{alias}]]."


# Where a long sentence may be cut without changing what it says.
_CUT_POINTS = (", and ", ", but ", ", while ", ", with ", ", as ", "; ", ", which ")


def _split_long(text: str, limit: int = 46) -> list[str]:
    """Break an over-long sentence at its own conjunctions.

    Sources write 60-word sentences; the book's own voice does not. Cutting at a
    comma keeps every word and every figure, so nothing is added and nothing is
    lost - the citation still covers the whole paragraph afterwards.
    """
    text = text.strip()
    if count_words(text) <= limit:
        return [text]

    best: tuple[float, str, int] | None = None
    for cut in _CUT_POINTS:
        at = text.rfind(cut)
        if at > 0:
            head = text[:at]
            balance = abs(count_words(head) - count_words(text) / 2)
            if best is None or balance < best[0]:
                best = (balance, cut, at)
    if best is None:
        # Nothing in the sentence offers a conjunction, so fall back to a plain
        # comma - but only where both halves stand on their own, so the cut never
        # leaves a fragment such as "UPI." behind.
        for at in range(len(text) - 1, 0, -1):
            if text[at:at + 2] != ", ":
                continue
            head, tail = text[:at], text[at + 2:]
            if count_words(head) < 14 or count_words(tail) < 14:
                continue
            if re.search(r"[A-Za-z]\.$", head) or re.search(r"\b[A-Z]\.$", head):
                continue
            return _split_long(head, limit) + _split_long(tail, limit)
        return [text]

    _, cut, at = best
    head = text[:at].rstrip(" ,;")
    tail = text[at + len(cut):].lstrip()
    if not head or not tail:
        return [text]

    parts: list[str] = []
    for piece in (head, tail):
        parts.extend(_split_long(piece, limit))
    if not _same_words(parts, text, consumed=[cut]):
        return [text]
    return parts


def _same_words(parts: list[str], text: str, consumed: list[str]) -> bool:
    """True when splitting only moved punctuation: no word added, none lost."""
    words = lambda s: sorted(re.findall(r"[^\W_]+", s, re.UNICODE))
    eaten = [w for cut in consumed for w in re.findall(r"[^\W_]+", cut, re.UNICODE)]
    return sorted(words(" ".join(parts)) + eaten) == words(text)


def _aliases_in(fn) -> set[str]:
    """Aliases referenced by a prose function's source, including inside strings."""
    import inspect

    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return set()
    aliases = set(re.findall(r'\bc\.get\("([a-z0-9_]+)"\)', src))
    aliases |= set(re.findall(r"\[\[cite:([a-z0-9_]+)\]\]", src))
    aliases |= set(re.findall(r"\[\[cite:([a-z0-9_]+)", src))
    return aliases


def _citation_order(body: str) -> list[int]:
    seen: list[int] = []
    for match in re.finditer(r"\[(\d{1,3})\]", body):
        n = int(match.group(1))
        if n not in seen:
            seen.append(n)
    return sorted(seen)


def _page_key(source) -> str:
    """What makes two references the same page: the link, else the title."""
    url = str(getattr(source, "url", "") or "").strip()
    if url:
        return url.lower().rstrip("/")
    return f"{getattr(source, 'org', '')}|{getattr(source, 'title', '')}".lower()


def _claims_of(ref: dict, ledger) -> list[Claim]:
    """Every claim a reference number stands for - usually one, sometimes several.

    One page can carry three figures, and the reference list prints that page
    once. The number therefore has to keep all three claims reachable.
    """
    ids = list(ref.get("claim_ids") or [])
    if not ids and ref.get("claim_id"):
        ids = [ref["claim_id"]]
    claims = []
    for claim_id in ids:
        claim = ledger.claims.get(claim_id)
        if claim is not None and claim not in claims:
            claims.append(claim)
    return claims


def _clean_llm_prose(text: str) -> str:
    """Strip the scaffolding a chat model adds around the prose."""
    text = (text or "").strip()
    text = re.sub(r"^```(?:\w+)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text.strip())
    text = re.sub(r"^(?:here(?:'s| is)|chapter \d+[:\s]*)", "", text, flags=re.I).strip()
    text = re.sub(r"^\*\*[^*]+\*\*\s*$", "", text, flags=re.M).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


_ = (Claim, Draft)