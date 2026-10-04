"""Architect agent.

This is the agent the studio index page talks to. It is given a title and an
introduction - nothing else - and it writes the whole `BookSpec`: the outline, the
evidence slots each movement needs, the candidate sources with regex probes that
can lift their figures, the glossary the Editor will police, and the figures worth
drawing.

Two things make that safe to let a model do:

1. Nothing here is trusted. Every URL is checked for a real scheme, every probe is
   compiled, every slot has to line up with a probe that exists, and the finished
   spec goes through `BookSpec.problems()` before a single page is fetched. A spec
   that fails is refused, not repaired into fiction.
2. The model proposes; the Researcher disposes. A source only becomes a claim
   after its probe has matched that page live, so a hallucinated URL produces an
   empty chapter rather than a fabricated fact.

Without a language model the Architect cannot invent sources, but it can still plan: if
the publisher supplies source links, it fetches them and builds the outline out of the
figures it finds there. With neither a model nor links there is nothing to plan from,
and it says so rather than guessing.
"""

from __future__ import annotations

import hashlib
import re

from ..llm import LLMError, resolve_backend, try_json
from ..spec import BookSpec, slugify
from .base import Agent

SYSTEM = (
    "You are the Architect of a book-production team. You are given a book's title "
    "and its introduction, and you write the production plan for it. You reply with "
    "JSON only.\n\n"
    "You never write the prose. You plan where the evidence will come from."
)

PLAN_HINT = r"""\
Produce a JSON object with exactly these keys:

{
  "title": "kept as given",
  "audience": "who exactly reads this, in one line",
  "voice": "one paragraph describing tone, sentence length and register",
  "chapters": <integer, the number of chapters>,
  "min_words": <integer>, "max_words": <integer>,
  "jargon": ["term", "..."],
  "glossary": {"TERM": "plain-English gloss of the term, one clause"},
  "slot_titles": {"slot_name": "the question this slot answers, in reader language"},
  "outline": [
    {
      "title": "chapter title, appetising and concrete",
      "purpose": "what this chapter must achieve for the reader",
      "movements": [
        {"key": "open", "intent": "what this movement does, one sentence",
         "slots": ["slot_name"], "terms": ["term to gloss here"]}
      ]
    }
  ],
  "sources": [
    {
      "key": "short_snake_case_id",
      "org": "the publishing organisation",
      "title": "the page's own title",
      "url": "https://... the exact page, not a site root",
      "published": "YYYY-MM-DD or YYYY",
      "tier": "official | regulator | reputable_press | other",
      "slots": ["slot_name"],
      "probes": [
        {"key": "short_snake_case_id",
         "claim": "the fact this page supports, stated in plain English",
         "pattern": "a Python regex that matches that fact on the page"}
      ]
    }
  ],
  "probe_slots": {"source_key:probe_key": "slot_name"},
  "corroboration": {"source_key": ["other_source_key"]},
  "figures": [
    {"key": "ch1_thing", "chapter": 1, "kind": "bar|line|donut|stat",
     "title": "chart title", "caption": "one line under the chart",
     "items": [{"claim": "source_key:probe_key", "value": "named_capture_group",
                "label": "axis label"}]}
  ]
}

Rules that are not negotiable:

- Chapter count, length and voice come from the request. Use the requested length.
- Every chapter starts with a movement keyed "open" and ends with one keyed
  "close". Every other movement key is a short snake_case name. 5 to 9 movements
  per chapter.
- A movement's "slots" name the evidence it needs. Every slot must appear in
  "slot_titles" and must be answered by at least one probe in "probe_slots".
  Use 8 to 16 slots across the whole book and reuse slots where it helps.
- "jargon" lists only the terms the reader will meet and might not know. Every
  jargon term needs a glossary entry.
- Sources must be real pages that exist today and carry the exact figures you
  probe for. Prefer official and regulator pages over press. Never invent a URL,
  an organisation or a statistic.
- Each probe pattern is a Python regular expression matched case-insensitively
  against the page's visible text. Use \\s+ between words that a page may break
  across lines, escape the characters that mean something in regex, and pull every
  figure you want to quote into a named group:
  (?P<volume>[\d,]+\.?\d*) crore transactions
  Quote the wording you expect to find, not a paraphrase of it.
- probe_slots maps "source_key:probe_key" to the slot that probe answers.
- corroboration lists, for any source that refuses automated clients, the source
  keys that carry the same fact so the citation can still be used.
- figures plot only claim ids you created, and "value" must be a named group that
  probe really captures. Prefer 2 to 6 items per figure. Choose "bar" for
  comparisons, "line" for a series over time, "donut" for shares of a whole and
  "stat" for a headline number with its unit.
"""


class ArchitectAgent(Agent):
    role = "architect"
    name = "Architect"

    def run(self, request: BookSpec, repair: bool = True) -> BookSpec:
        """Turn a requested book into a spec a run can actually execute."""
        self.banner()
        if not self.has_llm():
            return self.derive(request)

        backend = resolve_backend(self.config.backend, self.config.model)
        spec = request
        for attempt in range(1, 3):
            prompt = self._prompt(request, spec, attempt)
            try:
                raw = backend.complete(
                    SYSTEM, prompt, max_tokens=8000, temperature=0.4, json_mode=True,
                )
            except LLMError as exc:
                # A model that cannot answer in time is still a model that is there.
                # Rather than lose the run, fall back to the links if the publisher
                # supplied any; only refuse outright when there is nothing else.
                self.say(f"model call failed: {exc}")
                self.ledger.decide(
                    self.name, "model-failed",
                    f"planning by model failed ({exc}); "
                    + ("falling back to the supplied links"
                       if self._links(request) else "no links to fall back on"),
                )
                if self._links(request):
                    return self.derive(request)
                raise
            data = try_json(raw)
            if not isinstance(data, dict):
                self.say("model reply was not usable JSON; asking again")
                continue

            try:
                spec = self._merge(request, data)
            except (TypeError, ValueError, AttributeError) as exc:
                # A plan shaped wrong is a wrong answer, not a failed run: ask
                # again, and fall back to the publisher's own links if the model
                # cannot produce a plan this pipeline can execute.
                self.say(f"the model's plan could not be read ({exc}); asking again")
                self.ledger.decide(
                    self.name, "model-plan-unreadable",
                    f"planning by model returned a plan that could not be loaded "
                    f"({exc.__class__.__name__}: {exc}); "
                    + ("falling back to the supplied links" if self._links(request)
                       else "no links to fall back on"),
                )
                if self._links(request):
                    return self.derive(request)
                continue
            repairs = spec.tidy()
            for repair in repairs[:8]:
                self.say(f"  repaired: {repair}")
            problems = spec.problems()
            if not problems:
                self.say(
                    f"spec written: {len(spec.chapter_specs())} chapters, "
                    f"{len(spec.sources)} sources, "
                    f"{len(spec.probe_slots)} probes, {len(spec.figures)} figures, "
                    f"{len(spec.slots())} slots"
                )
                self.ledger.spec = spec
                self.ledger.brief = spec.to_brief()
                self.ledger.decide(
                    self.name, "spec-approved",
                    f"{request.title!r} planned with {len(spec.sources)} candidate "
                    f"source(s) and {len(spec.probe_slots)} evidence probe(s)",
                )
                return spec

            self.say(f"spec check found {len(problems)} problem(s):")
            for problem in problems[:12]:
                self.say(f"  - {problem}")
            if attempt == 1 and repair:
                self.say("sending the problems back for a corrected plan")
                self.ledger.decide(
                    self.name, "spec-repair-requested",
                    f"{len(problems)} validation problem(s) in the first plan: "
                    + "; ".join(problems[:4]),
                )
                continue
            if self._links(request):
                self.say("the model's plan would not pass its own checks; "
                         "planning from the supplied links instead")
                return self.derive(request)
            raise ValueError(
                "the Architect could not write a valid plan: " + "; ".join(problems[:6])
            )

        if self._links(request):
            self.say("the model would not return a usable plan; planning from the "
                     "supplied links instead")
            return self.derive(request)
        raise LLMError("the model did not return a usable plan")

    # ------------------------------------------------------- without a model
    @staticmethod
    def _links(request: BookSpec) -> list[str]:
        return [
            str(raw.get("url", "")).strip()
            for raw in request.sources
            if str(raw.get("url", "")).strip()
        ]

    def derive(self, request: BookSpec) -> BookSpec:
        """Plan a book from the source links alone, with no language model.

        Everything a model would be asked for here - which sentences count as
        evidence, which figures are worth a chart - is a question about the pages,
        not about the argument. So the pages answer it: each one is fetched, its
        quotable sentences become probes, and the outline is built around the
        evidence that actually exists.

        What this cannot do is choose *sources*. A publisher who wants a book
        built from nothing but a title must give links, or start a model.
        """
        from .. import http
        from ..knowledge.probes import (
            derive_probes, glossary_from, page_title, publisher_for, tier_for,
        )

        urls = []
        for url in self._links(request):
            urls.append(url if url.lower().startswith("https://")
                        else "https://" + url.split("://", 1)[-1])
        if not urls:
            self.say(
                "no language model and no source links, so there is nothing to plan "
                "from. Paste the pages the book should be built on, or start Ollama "
                "(`ollama pull qwen2.5:1.5b`) and try again."
            )
            raise LLMError(
                "with no language model the studio needs at least one source link "
                "to plan from; add links in the form, or run Ollama locally"
            )

        self.say(f"no language model available; reading {len(urls)} supplied link(s) "
                 "and building the plan from what they actually say")
        pages = http.parallel_fetch(urls, timeout=self.config.request_timeout,
                                    workers=self.config.fetch_workers).values()

        sources: list[dict] = []
        glossary: dict[str, str] = {}
        probe_slots: dict[str, str] = {}
        per_chapter: dict[int, list[tuple[str, dict]]] = {}

        for page in pages:
            if not page.live or len(page.text) < 200:
                self.say(f"  skipped {page.url}: {page.summary()}")
                continue
            key = _source_key(page.url)
            org = publisher_for(page.url)
            probes = derive_probes(page.text, org=org, limit=PROBES_PER_SOURCE)
            if not probes:
                self.say(f"  {org}: no quotable figure found on this page; skipped")
                continue
            sources.append({
                "key": key, "org": org,
                "title": page_title(page.raw, fallback=page.url),
                "url": page.url, "published": "", "tier": tier_for(page.url),
                "slots": [], "probes": [
                    {"key": p.key, "claim": p.claim, "pattern": p.pattern,
                     "required": False}
                    for p in probes
                ],
            })
            for term, gloss in glossary_from(page.text, limit=3).items():
                glossary.setdefault(term, gloss)
            self.say(f"  {org}: {len(probes)} quotable figure(s) found")

        if not sources:
            raise LLMError(
                "none of the supplied links carried a figure that could be quoted; "
                "check that the pages are public and contain numbers"
            )

        flat = [
            (source["key"], probe)
            for source in sources
            for probe in source["probes"]
        ]
        if len(flat) < MIN_DERIVED_SLOTS:
            raise LLMError(
                f"only {len(flat)} quotable figure(s) were found in "
                f"{len(sources)} link(s); a book needs at least {MIN_DERIVED_SLOTS} to "
                "be evidenced, so add more links, or start a language model to find "
                "sources for you"
            )

        # Spread the probes over the chapters, so no chapter borrows a single
        # number and no page has to carry a whole book on its own. Three probes
        # is the least a chapter can carry: two evidence movements, an opening
        # and a close.
        chapters = max(1, request.chapters)
        if len(flat) // chapters < PROBES_PER_CHAPTER:
            new_chapters = max(1, len(flat) // PROBES_PER_CHAPTER)
            if new_chapters < chapters:
                self.say(
                    f"  {len(flat)} usable figure(s) supports {new_chapters} "
                    f"chapter(s), not {chapters}; planning {new_chapters}"
                )
                chapters = new_chapters

        for index, (key, probe) in enumerate(flat):
            chapter_index = index % chapters + 1
            slot = f"{key}_{probe['key']}"
            probe_slots[f"{key}:{probe['key']}"] = slot
            per_chapter.setdefault(chapter_index, []).append((key, probe))
            for source in sources:
                if source["key"] == key and slot not in source["slots"]:
                    source["slots"].append(slot)

        outline: list[dict] = []
        figures: list[dict] = []
        for chapter_index in range(1, chapters + 1):
            entries = per_chapter.get(chapter_index, [])
            movements: list[dict] = [{
                "key": "open",
                "intent": f"Open chapter {chapter_index} with the situation the "
                          "reader is in, in plain words, before any figure.",
                "slots": [], "terms": [],
            }]
            items: list[dict] = []
            slots_in_order: list[tuple[str, str]] = []
            for key, probe in entries:
                slots_in_order.append((key, f"{key}_{probe['key']}"))
                items.append({
                    "claim": f"{key}:{probe['key']}",
                    "value": _first_group(probe["pattern"]),
                    "label": _figure_label(probe["claim"], key),
                })
            items = _dedupe_labels(items)

            # One movement per few figures, not per source: a page with ten
            # quotable numbers should carry a chapter through several movements
            # rather than all of them in one lump.
            for number, chunk in enumerate(
                _chunks(slots_in_order, PROBES_PER_MOVEMENT), start=1
            ):
                orgs = sorted({_source_label(sources, key) for key, _ in chunk})
                movements.append({
                    "key": "evidence_" + chunk[0][0].split("_")[0]
                            + (f"_{number}" if number > 1 else ""),
                    "intent": f"Set out {len(chunk)} figure(s) that "
                              f"{' and '.join(orgs)} publish"
                              + (f" (figure {number} of {number} in this run)"
                                 if number > 1 else "")
                              + ", each followed by the reference it was read from.",
                    "slots": [slot for _, slot in chunk],
                    "terms": [],
                })
            movements.append({
                "key": "close",
                "intent": f"Close chapter {chapter_index} on what the reader should "
                          "do with these figures.",
                "slots": [], "terms": [],
            })
            outline.append({
                "title": _chapter_title(
                    request, chapter_index, chapters,
                    [probe for _, probe in entries], orgs_in_chapter(sources, entries),
                ),
                "purpose": (
                    f"What the cited sources publish about "
                    f"{_chapter_title(request, chapter_index, chapters, [p for _, p in entries], orgs_in_chapter(sources, entries)).lower()}, "
                    "and what a reader should make of it."
                )[:300],
                "movements": movements,
            })
            if items:
                figures.append({
                    "key": f"ch{chapter_index}_figures",
                    "chapter": chapter_index,
                    "kind": "bar" if len(items) > 1 else "stat",
                    "title": f"What chapter {chapter_index} rests on",
                    "caption": "Figures as published by the sources named below.",
                    "items": items[:5],
                })

        if len(glossary) < 4:
            glossary.update(_unit_glossary())

        min_words, max_words = self._word_range(request, chapters, per_chapter)

        spec = BookSpec(
            slug=request.slug, title=request.title,
            introduction=request.introduction, audience=request.audience,
            author=request.author,
            voice=request.voice, language=request.language,
            chapters=chapters, min_words=min_words,
            max_words=max_words, jargon=[], glossary=glossary,
            outline=outline, sources=sources, probe_slots=probe_slots,
            slot_titles={
                slot: f"what the sources report for {slot.replace('_', ' ')}"
                for slot in probe_slots.values()
            },
            figures=figures, cover_palette=request.cover_palette,
            origin="derived",
            notes=(
                "Planned without a language model: the outline is built from the "
                "quotable figures in the source links supplied, and the word range "
                "is set to what that evidence can carry."
            ),
        )
        repairs = spec.tidy()
        for repair in repairs[:6]:
            self.say(f"  repaired: {repair}")
        problems = spec.problems()
        if problems:
            raise ValueError(
                "the supplied links did not yield a runnable plan: "
                + "; ".join(problems[:5])
            )
        self.say(
            f"plan derived: {chapters} chapters, {len(sources)} source(s), "
            f"{len(probe_slots)} figure(s) quoted, {len(figures)} chart(s)"
        )
        self.ledger.spec = spec
        self.ledger.brief = spec.to_brief()
        self.ledger.decide(
            self.name, "spec-derived",
            f"{request.title!r} planned from {len(sources)} supplied link(s) and "
            f"{len(probe_slots)} quotable figure(s), without a language model",
        )
        return spec

    # ----------------------------------------------------------------- prompt
    def _word_range(self, request: BookSpec, chapters: int,
                    per_chapter: dict) -> tuple[int, int]:
        """A word range the evidence can actually reach.

        Asked for 600-900 words and handed one page, no model can write 900 words
        of new material without inventing some of it. So the range is set to the
        size of what the sources really say, and the change is announced rather
        than quietly discovered later as a rejected chapter.
        """
        available = []
        for index in range(1, chapters + 1):
            quoted = sum(
                len(str(probe["claim"]).split())
                for _, probe in per_chapter.get(index, [])
            )
            available.append(quoted + CONNECTIVE_WORDS)
        low = max(MIN_DERIVED_WORDS, int(min(available or [0]) * 0.85))
        high = max(low + 60, int(max(available or [0]) * 1.3) + 10)

        min_words = min(request.min_words, low)
        max_words = max(min_words + 60, min(request.max_words, high))
        if (min_words, max_words) != (request.min_words, request.max_words):
            self.say(
                f"  the links carry about {min(available)}-{max(available)} words of "
                f"quotable evidence per chapter, so the word range is "
                f"{min_words}-{max_words}, not {request.min_words}-{request.max_words}"
            )
        return min_words, max_words
    def _prompt(self, request: BookSpec, draft: BookSpec, attempt: int) -> str:
        pinned = ""
        if request.sources:
            lines = [
                f"- {raw.get('url')}"
                + (f"  (use this exact URL, do not substitute)" if raw.get("url") else "")
                for raw in request.sources
                if raw.get("url")
            ]
            pinned = (
                "\n\nThe publisher requires these exact URLs to be used:\n"
                + "\n".join(lines)
            )
        feedback = ""
        if attempt > 1 and draft.sources:
            feedback = (
                "\n\nYour previous attempt was rejected. Produce a completely "
                "corrected plan."
            )
        return (
            f"TITLE\n{request.title}\n\n"
            f"INTRODUCTION\n{request.introduction}\n\n"
            f"CHAPTERS: exactly {request.chapters}\n"
            f"LENGTH: {request.min_words}-{request.max_words} words per chapter\n"
            f"{pinned}{feedback}\n\n"
            f"{PLAN_HINT}"
        )

    # ------------------------------------------------------------------ merge
    def _merge(self, request: BookSpec, data: dict) -> BookSpec:
        """Keep what only the publisher knows; take the rest from the model."""
        pinned_urls = [
            str(raw.get("url", "")).strip()
            for raw in request.sources
            if str(raw.get("url", "")).strip()
        ]
        sources = [raw for raw in (data.get("sources") or []) if isinstance(raw, dict)]
        sources = _merge_pinned(sources, pinned_urls)

        figures = [raw for raw in (data.get("figures") or []) if isinstance(raw, dict)]
        spec = BookSpec.from_dict(
            {
                "slug": request.slug,
                "title": request.title or data.get("title", ""),
                "introduction": request.introduction,
                "audience": data.get("audience") or request.audience,
                "author": request.author,
                "voice": data.get("voice") or request.voice,
                "language": request.language,
                "chapters": int(data.get("chapters") or request.chapters),
                "min_words": int(data.get("min_words") or request.min_words),
                "max_words": int(data.get("max_words") or request.max_words),
                "jargon": data.get("jargon") or request.jargon,
                "glossary": data.get("glossary") or request.glossary,
                "outline": data.get("outline") or [],
                "sources": sources,
                "probe_slots": data.get("probe_slots") or {},
                "corroboration": data.get("corroboration") or {},
                "slot_titles": data.get("slot_titles") or {},
                "figures": figures,
                "cover_palette": request.cover_palette,
                "origin": "ai",
                "notes": request.notes,
            }
        )
        spec.probe_slots = _prune_probe_slots(spec)
        return spec


PROBES_PER_SOURCE = 10
PROBES_PER_MOVEMENT = 2
PROBES_PER_CHAPTER = 3
MIN_DERIVED_SLOTS = 8
MIN_DERIVED_WORDS = 120
CONNECTIVE_WORDS = 70


def _chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)] or [[]]


def _figure_label(claim: str, key: str) -> str:
    """A chart label a reader can tell apart, taken from the claim itself.

    Four bars all called "PIB" say nothing, so the label is the words the source
    put around its own number, cut off before the number arrives.
    """
    words = [w for w in re.split(r"\s+", str(claim or "")) if w]
    words = words[3:] if words[:1] == [key] else words
    label: list[str] = []
    for word in words:
        if re.search(r"\d", word):
            break
        label.append(word)
        if len(label) >= 7:
            break
    text = " ".join(label).strip(" ,;:") or str(claim or "")[:24]
    return text[:40]


def _dedupe_labels(items: list[dict]) -> list[dict]:
    """Charts cannot show two bars with the same name, so number the repeats."""
    seen: dict[str, int] = {}
    for item in items:
        label = str(item.get("label", ""))
        seen[label] = seen.get(label, 0) + 1
        if seen[label] > 1:
            item["label"] = f"{label} ({seen[label]})"[:44]
    return items


def _source_key(url: str) -> str:
    """A stable, readable name for one page.

    The host alone is not enough: three press releases on one site are three
    sources, and a plan that gave them all one key would put their claims in the
    same bucket and collapse them into a single figure.
    """
    host = re.sub(r"^https?://(www\.)?", "", url or "").split("/")[0]
    digest = hashlib.sha1((url or "").encode("utf-8", "ignore")).hexdigest()[:6]
    return f"{slugify(host, 'source')[:28]}-{digest}"


def _source_label(sources: list[dict], key: str) -> str:
    for source in sources:
        if source.get("key") == key:
            return str(source.get("org", key))[:28]
    return key


def _first_group(pattern: str) -> str:
    import re

    match = re.search(r"\(\?P<([A-Za-z_][A-Za-z0-9_]*)>", pattern or "")
    return match.group(1) if match else ""


def _chapter_title(request: BookSpec, index: int, total: int,
                   probes: list | None = None, orgs: list | None = None) -> str:
    """A title per chapter, from the introduction if it offers one, else the evidence.

    Three chapters all called "The Evidence in Brief" is not a table of contents,
    so when the introduction does not supply a distinct line per chapter the title
    is the subject this chapter's own figures are about.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", request.introduction)
                 if len(s.strip()) > 12]
    # An introduction sentence only makes a title if it is already a title-length
    # phrase; a whole sentence of explanation reads as a heading that says nothing.
    if len(sentences) >= total:
        for sentence in sentences:
            phrase = " ".join(sentence.rstrip(".").split()[:8])
            if len(phrase.split()) <= 7 and len(phrase.split()) >= 2:
                return phrase[:80].strip(" ,;:")

    for probe in probes or []:
        claim = str(probe.get("claim", ""))
        for org in orgs or []:
            claim = claim.replace(f"{org} reports that ", "")
        title = _topic_of(claim)
        if title:
            return title

    # Nothing in the first sentence is worth a heading - a caption, a fragment, a
    # name. Rather than invent one, say whose figures the chapter is made of.
    who = (orgs or [""])[0] or "the sources"
    return f"What {who} reports"


# Words that end a subject phrase: past them, the sentence has started saying
# something else, and a title cut there reads like a phrase rather than a
# fragment.
_TITLE_STOP = {
    "is", "are", "was", "were", "be", "been", "has", "have", "had", "will",
    "would", "can", "could", "may", "might", "must", "should", "does", "do",
    "did", "accounts", "account", "crossed", "reached", "rose", "grew", "grows",
    "saw", "sees", "makes", "made", "shows", "showed", "became", "remains",
    "stands", "represents", "reflects", "reflecting", "drives", "driving",
    "means", "help", "helps", "continue", "continued", "enable", "enables",
    "enabling", "contributed", "contribute", "recorded", "reports", "report",
}
_TITLE_LEAD = {
    "in", "on", "at", "for", "from", "with", "over", "under", "about", "after",
    "before", "during", "by", "to", "as", "that", "this", "these", "those",
    "the", "a", "an", "its", "it", "their", "his", "her", "our", "your",
    "further", "since", "meanwhile", "overall", "additionally", "also", "of",
    "off", "per", "than", "then", "so", "yet", "only", "just", "now", "here",
    "there", "when", "while", "where", "which", "who", "contrast", "fact",
    "addition", "practice", "turn", "parallel", "part", "total", "up", "down",
}

# A digit inside a name is part of the name: "P2M" and "NPCI2" are not figures.
_FIGURE_IN_WORD = re.compile(r"(?<![A-Za-z])\d")


def _topic_of(claim: str, words_wanted: int = 6) -> str:
    """The subject a source sentence is about, in its own words.

    A title carrying a figure would repeat that figure in the chapter's opening
    line, where it has no citation of its own to lean on, so the phrase is cut
    before the first number rather than after it.
    """
    words = [w for w in re.split(r"\s+", str(claim or "").strip()) if w]
    while words and words[0].lower().strip(",.:;") in _TITLE_LEAD:
        words.pop(0)

    kept: list[str] = []
    for word in words:
        bare = word.lower().strip(",.:;()")
        if _FIGURE_IN_WORD.search(word):
            break
        if bare in _TITLE_STOP or bare in _TITLE_LEAD:
            if kept:
                break
            continue
        kept.append(word.strip(",;:()"))
        if len(kept) >= words_wanted:
            break
    while kept and kept[-1].lower().strip(",.:;()") in _TITLE_STOP | _TITLE_LEAD:
        kept.pop()

    title = " ".join(kept).strip(" ,;:-")
    return title[:72] if len(title.split()) >= 2 else ""


def orgs_in_chapter(sources: list[dict], entries: list) -> list[str]:
    """Publisher names for the sources a chapter draws on, in order of appearance."""
    out: list[str] = []
    for key, _ in entries:
        label = _source_label(sources, key)
        if label not in out:
            out.append(label)
    return out


def _unit_glossary() -> dict[str, str]:
    """Enough glossary to satisfy the editor, said plainly and truthfully."""
    return {
        "crore": "an Indian unit of ten million, written 1 crore",
        "lakh": "an Indian unit of one hundred thousand, written 1 lakh",
        "per cent": "out of every hundred, written per cent",
        "figure": "a number the cited source publishes",
        "source": "the organisation whose page the number was read from",
    }


def _merge_pinned(sources: list[dict], pinned_urls: list[str]) -> list[dict]:
    """A pinned URL is never dropped, even if the model ignored it."""
    seen = {str(raw.get("url", "")).strip() for raw in sources}
    return sources + [
        {"key": "", "org": "", "title": "", "url": url, "published": "",
         "tier": "official", "slots": [], "probes": []}
        for url in pinned_urls
        if url not in seen
    ]


def _prune_probe_slots(spec: BookSpec) -> dict:
    """Keep slot assignments that point at a probe which actually exists."""
    known = spec.claim_ids()
    return {
        claim_id: slot
        for claim_id, slot in spec.probe_slots.items()
        if claim_id in known and str(slot).strip()
    }