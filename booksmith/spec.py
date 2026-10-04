"""A book, described as data.

Everything the pipeline needs to make *any* book lives in one JSON document: the
brief (title, audience, voice, length), the outline (chapters, movements, evidence
slots), the candidate sources with their regex evidence probes, the glossary, and
the figures to draw.

Two things produce a spec:

* `upi_spec()`, the curated book that ships with the project.
* the Architect agent, which reads a title and an introduction off the studio
  index page and writes the rest of this document with a language model.

Downstream agents read the spec and never import a topic module, so adding a book
means adding a spec, not editing the pipeline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .knowledge.brief import BRIEF as UPI_BRIEF
from .knowledge.brief import GLOSSARY as UPI_GLOSSARY
from .knowledge.outline import SKELETON as UPI_SKELETON
from .knowledge.sources import CORROBORATION as UPI_CORROBORATION
from .knowledge.sources import PROBE_SLOTS as UPI_PROBE_SLOTS
from .knowledge.sources import SEEDS as UPI_SEEDS
from .knowledge.sources import SLOT_TITLES as UPI_SLOT_TITLES
from .models import EvidenceProbe, SourceSeed
from .validators import JARGON

SPEC_VERSION = 2

DEFAULT_VOICE = (
    "A patient teacher talking to a newcomer across the counter. Warm, plain, "
    "concrete and encouraging. Short sentences. No jargon without an immediate "
    "plain-English explanation. Never condescending, never a press release."
)

DEFAULT_REFERENCE_RULES = (
    "Each chapter ends with its own numbered reference list.",
    "Each reference gives source organisation, title, date and a working link.",
    "Sources must be real and publicly accessible.",
    "Prefer official sources (regulators, government, standards bodies) and "
    "reputable news outlets.",
)

# Shown on the cover when the requester does not name an author. The agents do the
# writing, so the byline credits them rather than inventing a person.
DEFAULT_AUTHOR = "Planner, Researcher, Writer, Editor, FactChecker and Voicekeeper"

DEFAULT_FORMAT_RULES = (
    "Flowing prose only; no bullet points inside a chapter.",
    "Each chapter ends with a single line starting with 'Takeaway:'.",
    "The Takeaway line comes immediately before that chapter's reference list.",
    "The same tone and voice across every chapter.",
)

DEFAULT_QUALITY_RULES = (
    "Correct grammar, spelling and punctuation throughout.",
    "Every technical term is explained the first time it appears.",
    "No invented or broken sources.",
)

BAD_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "example.com", "example.org")


def slugify(text: str, fallback: str = "book") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:60] or fallback


def _as_list(value, default=None) -> list:
    if value is None:
        return list(default or [])
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, dict):
        return [value]
    try:
        return list(value)
    except TypeError:
        return list(default or [])


def _as_dict(value) -> dict:
    """A mapping field, whatever the model actually sent.

    A plan that puts a list where a mapping belongs is a repairable mistake, and
    repairing it is the Architect's job: `probe_slots`, `corroboration` and
    `slot_titles` all come back empty and `spec.problems()` gets to say so in a
    sentence. Crashing here instead would throw away the run over a typo.
    """
    if isinstance(value, dict):
        return dict(value)
    return {}


def _text_map(value) -> dict:
    """A mapping of short strings, tolerant of the wrong shape."""
    return {str(k): str(v) for k, v in _as_dict(value).items()}


def _probe_from_dict(raw: dict) -> EvidenceProbe:
    return EvidenceProbe(
        key=str(raw.get("key", "")).strip(),
        claim=str(raw.get("claim", "")).strip(),
        pattern=str(raw.get("pattern", "")),
        required=bool(raw.get("required", True)),
    )


def _seed_from_dict(raw: dict) -> SourceSeed:
    return SourceSeed(
        key=str(raw.get("key", "")).strip(),
        org=str(raw.get("org", "")).strip(),
        title=str(raw.get("title", "")).strip(),
        url=str(raw.get("url", "")).strip(),
        published=str(raw.get("published", "")),
        tier=str(raw.get("tier", "other")),
        slots=tuple(_as_list(raw.get("slots"))),
        probes=tuple(_probe_from_dict(p) for p in _as_list(raw.get("probes"))),
    )


def _compiles(pattern: str) -> bool:
    """True when a probe pattern is long enough to mean something and compiles."""
    text = str(pattern or "")
    if len(text) < 8:
        return False
    try:
        re.compile(text)
    except re.error:
        return False
    return True


def _movement_from(raw) -> dict:
    """Accept both the curated tuple shape and a plain object from the model."""
    if isinstance(raw, dict):
        return {
            "key": str(raw.get("key", "")).strip(),
            "intent": str(raw.get("intent", "")).strip(),
            "slots": tuple(_as_list(raw.get("slots"))),
            "terms": tuple(_as_list(raw.get("terms"))),
        }
    parts = list(raw) if isinstance(raw, (list, tuple)) else []
    return {
        "key": str(parts[0]).strip() if parts else "",
        "intent": str(parts[1]).strip() if len(parts) > 1 else "",
        "slots": tuple(_as_list(parts[2])) if len(parts) > 2 else (),
        "terms": tuple(_as_list(parts[3])) if len(parts) > 3 else (),
    }


def _chapter_from(raw) -> dict:
    if isinstance(raw, dict):
        title = str(raw.get("title", "")).strip()
        purpose = str(raw.get("purpose", "")).strip()
        movements = [_movement_from(m) for m in _as_list(raw.get("movements"))]
    else:
        title = str(raw.get("title", "")).strip()
        purpose = str(raw.get("purpose", "")).strip()
        movements = [_movement_from(m) for m in raw.get("movements", ())]
    return {"title": title, "purpose": purpose, "movements": movements}


@dataclass
class BookSpec:
    """One book. JSON-serialisable in both directions."""

    slug: str
    title: str
    introduction: str = ""
    audience: str = "Readers new to the subject"
    author: str = DEFAULT_AUTHOR
    voice: str = DEFAULT_VOICE
    language: str = "English"
    chapters: int = 3
    min_words: int = 600
    max_words: int = 900
    citation_style: str = "Every fact, figure and date carries a bracketed number like [1]."
    reference_rules: list[str] = field(default_factory=lambda: list(DEFAULT_REFERENCE_RULES))
    format_rules: list[str] = field(default_factory=lambda: list(DEFAULT_FORMAT_RULES))
    quality_rules: list[str] = field(default_factory=lambda: list(DEFAULT_QUALITY_RULES))
    jargon: list[str] = field(default_factory=list)
    glossary: dict = field(default_factory=dict)
    outline: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    probe_slots: dict = field(default_factory=dict)
    corroboration: dict = field(default_factory=dict)
    slot_titles: dict = field(default_factory=dict)
    figures: list = field(default_factory=list)
    cover_palette: list = field(default_factory=list)
    prose_bank: str = ""           # named bank in knowledge/prose.py, if any
    origin: str = "curated"
    notes: str = ""

    # ------------------------------------------------------------------ views
    def byline(self) -> str:
        """Who the cover credits. The agents are the author unless named."""
        return (self.author or "").strip() or DEFAULT_AUTHOR

    def initials(self) -> str:
        """One or two letters for the seal on the cover."""
        byline = self.byline()
        if byline == DEFAULT_AUTHOR:
            return "BS"          # the studio wrote this one
        words = [
            word for word in re.split(r"[^\w]+", byline)
            if word and word.lower() not in ("and", "the", "of", "for")
        ]
        if not words:
            return "B"
        if len(words) == 1:
            return words[0][:2].upper()
        return (words[0][0] + words[1][0]).upper()

    def to_brief(self) -> dict:
        """The brief shape the existing agents already consume."""
        return {
            "slug": self.slug,
            "title": self.title,
            "introduction": self.introduction,
            "audience": self.audience,
            "author": self.byline(),
            "language": self.language,
            "voice": self.voice,
            "chapters": self.chapters,
            "min_words": self.min_words,
            "max_words": self.max_words,
            "citation_style": self.citation_style,
            "reference_rules": list(self.reference_rules),
            "format_rules": list(self.format_rules),
            "quality_rules": list(self.quality_rules),
            "jargon": list(self.jargon),
            "origin": self.origin,
        }

    def chapter_specs(self) -> list[dict]:
        return [_chapter_from(raw) for raw in self.outline]

    def slots(self) -> set[str]:
        return {
            slot
            for chapter in self.chapter_specs()
            for movement in chapter["movements"]
            for slot in movement["slots"]
        }

    def target_words(self) -> int:
        mid = (self.min_words + self.max_words) // 2
        return max(self.min_words + 60, min(self.max_words - 60, mid))

    def seeds(self) -> tuple[SourceSeed, ...]:
        return tuple(_seed_from_dict(raw) for raw in self.sources)

    def seed_by_key(self) -> dict:
        return {seed.key: seed for seed in self.seeds()}

    def claim_ids(self) -> set[str]:
        return {
            f"{raw.get('key')}:{probe.get('key')}"
            for raw in self.sources
            for probe in _as_list(raw.get("probes"))
        }

    def figures_for(self, chapter_index: int) -> list[dict]:
        return [f for f in self.figures if int(f.get("chapter", 0)) == chapter_index]

    def paragraph_targets(self) -> dict:
        """Movement counts per chapter, so prompts can be specific about depth."""
        return {
            index: len(chapter["movements"])
            for index, chapter in enumerate(self.chapter_specs(), start=1)
        }

    # ------------------------------------------------------------------ checks
    def problems(self) -> list[str]:
        """Everything that would make the pipeline produce a bad book.

        The Architect runs this on the model's own draft and repairs what it can;
        the studio runs it before a run starts so a bad form submission is refused
        rather than half-generated.
        """
        issues: list[str] = []
        if not self.title.strip():
            issues.append("the book has no title")
        if len(self.introduction.strip()) < 40:
            issues.append("the introduction is too short to plan a book from")
        if not 1 <= self.chapters <= 12:
            issues.append(f"chapter count {self.chapters} is out of range 1-12")
        if self.min_words < 120 or self.max_words <= self.min_words:
            issues.append(
                f"word range {self.min_words}-{self.max_words} is not usable"
            )

        outline = self.chapter_specs()
        if len(outline) != self.chapters:
            issues.append(
                f"outline has {len(outline)} chapter(s) but the book asks for "
                f"{self.chapters}"
            )
        for index, chapter in enumerate(outline, start=1):
            if not chapter["title"]:
                issues.append(f"chapter {index} has no title")
            if len(chapter["movements"]) < 4:
                issues.append(
                    f"chapter {index} has {len(chapter['movements'])} movement(s); "
                    "a chapter needs at least 4 to reach its word count"
                )
            keys = [m["key"] for m in chapter["movements"]]
            if len(set(keys)) != len(keys):
                issues.append(f"chapter {index} repeats a movement key")
            if keys and keys[0] != "open":
                issues.append(f"chapter {index} does not open with an 'open' movement")
            if keys and keys[-1] != "close":
                issues.append(f"chapter {index} does not close with a 'close' movement")
            for movement in chapter["movements"]:
                if len(movement["intent"]) < 25:
                    issues.append(
                        f"chapter {index} movement {movement['key']!r} has too thin "
                        "an intent for a writer to follow"
                    )
        if len(self.slots()) < 8:
            issues.append(
                f"only {len(self.slots())} evidence slots planned; the outline needs at "
                "least 8 or the chapters cannot be evidenced"
            )

        for raw in self.sources:
            key = str(raw.get("key", "")).strip()
            url = str(raw.get("url", "")).strip()
            org = str(raw.get("org", "")).strip()
            if not key:
                issues.append("a source has no key")
                continue
            if not url.lower().startswith("https://"):
                issues.append(f"source {key} is not an https URL: {url!r}")
            if any(host in url.lower() for host in BAD_HOSTS):
                issues.append(f"source {key} points at a placeholder host: {url}")
            if not org:
                issues.append(f"source {key} has no organisation name")
            probes = _as_list(raw.get("probes"))
            if not probes:
                issues.append(f"source {key} has no evidence probes")
            seen: set[str] = set()
            for probe in probes:
                pkey = str(probe.get("key", "")).strip()
                pattern = str(probe.get("pattern", ""))
                if not pkey or pkey in seen:
                    issues.append(f"source {key} has a missing or duplicate probe key")
                    continue
                seen.add(pkey)
                if len(pattern) < 8:
                    issues.append(f"probe {key}:{pkey} has no usable pattern")
                    continue
                try:
                    re.compile(pattern)
                except re.error as exc:
                    issues.append(f"probe {key}:{pkey} is not a valid regex ({exc})")
                if not str(probe.get("claim", "")).strip():
                    issues.append(f"probe {key}:{pkey} states no claim")

        known = self.claim_ids()
        for claim_id, slot in self.probe_slots.items():
            if claim_id not in known:
                issues.append(f"probe_slots names unknown probe {claim_id!r}")
            elif not slot:
                issues.append(f"probe_slots gives {claim_id!r} an empty slot")
        if len(self.glossary) < 4:
            issues.append(
                f"only {len(self.glossary)} glossary entries; the editor needs the "
                "jargon list to police"
            )
        for figure in self.figures:
            fkey = str(figure.get("key", "")) or figure.get("title", "?")
            items = _as_list(figure.get("items"))
            if not items:
                issues.append(f"figure {fkey} plots nothing")
            for item in items:
                claim = str(item.get("claim", "")).strip()
                if claim and known and claim not in known:
                    issues.append(
                        f"figure {fkey} plots unknown claim {claim!r}"
                    )
        for key, witnesses in self.corroboration.items():
            if key not in {str(s.get('key')) for s in self.sources}:
                issues.append(f"corroboration names unknown source {key!r}")
            for witness in _as_list(witnesses):
                if witness not in {str(s.get('key')) for s in self.sources}:
                    issues.append(
                        f"corroboration for {key!r} names unknown witness {witness!r}"
                    )
        return issues

    # ------------------------------------------------------------------ repair
    def tidy(self) -> list[str]:
        """Fix the mechanical defects a model can plausibly get wrong.

        Only two kinds of change are allowed here, and neither can invent
        evidence: drop something that has nothing behind it, or fill a gap from
        something the model itself already supplied. An intent can be rebuilt from
        a slot title; a probe cannot be rebuilt from nothing. Anything still wrong
        after this is left for `problems()` to report, so the Architect can ask
        for a better plan instead of quietly shipping a thin one.
        """
        notes: list[str] = []
        known = self.claim_ids()

        sources, dropped_sources = [], []
        for raw in self.sources:
            probes = _as_list(raw.get("probes"))
            usable = [
                p for p in probes
                if str(p.get("key", "")).strip() and _compiles(p.get("pattern", ""))
            ]
            if not usable:
                dropped_sources.append(str(raw.get("key") or raw.get("url") or "?"))
                continue
            raw["probes"] = usable
            sources.append(raw)
        if dropped_sources:
            notes.append(
                f"dropped {len(dropped_sources)} source(s) with no usable evidence "
                f"probe: {', '.join(dropped_sources[:4])}"
            )
        self.sources = sources
        known = self.claim_ids()

        self.probe_slots = {
            claim_id: slot
            for claim_id, slot in self.probe_slots.items()
            if claim_id in known and str(slot).strip()
        }

        outline = []
        for index, raw in enumerate(self.chapter_specs(), start=1):
            movements = raw["movements"]

            for movement in movements:
                slots = tuple(
                    slot for slot in movement["slots"]
                    if slot in {self.probe_slots.get(cid) for cid in known}
                )
                if slots != movement["slots"]:
                    movement["slots"] = slots
                    notes.append(
                        f"ch{index} {movement['key']}: dropped "
                        f"{len(movement['slots']) - len(slots)} slot(s) with no probe"
                    )
                if not movement["intent"]:
                    titles = [
                        self.slot_titles.get(slot, slot)
                        for slot in movement["slots"]
                    ]
                    movement["intent"] = (
                        "Cover the evidence for " + "; ".join(titles[:2])
                        if titles else
                        f"Carry the chapter's {index} argument forward with a worked "
                        "example the reader can follow."
                    )
                    notes.append(f"ch{index} {movement['key']}: intent rebuilt")

            keys = [m["key"] for m in movements]
            if keys and keys[0] != "open":
                movements.insert(0, {
                    "key": "open",
                    "intent": f"Open chapter {index} with the situation the reader "
                              "is actually in, in plain words.",
                    "slots": (), "terms": (),
                })
                notes.append(f"ch{index}: added the opening movement")
            if movements and movements[-1]["key"] != "close":
                movements.append({
                    "key": "close",
                    "intent": f"Close chapter {index} on what the reader should do "
                              "differently tomorrow.",
                    "slots": (), "terms": (),
                })
                notes.append(f"ch{index}: added the closing movement")
            if len(movements) < 4:
                # Split the busiest movement rather than inventing a new topic:
                # each new movement keeps a slot the book already needs answered.
                spare = [
                    (slot, self.slot_titles.get(slot, slot))
                    for movement in movements
                    for slot in movement["slots"]
                ]
                while len(movements) < 4 and spare:
                    slot, title = spare.pop()
                    if any(slot in m["slots"] for m in movements):
                        spare = [(s, t) for s, t in spare
                                 if not any(s in m["slots"] for m in movements)]
                        if not spare:
                            break
                        continue
                    movements.insert(-1, {
                        "key": f"evidence_{len(movements)}",
                        "intent": f"Show the evidence for {title}.",
                        "slots": (slot,), "terms": (),
                    })
                    notes.append(f"ch{index}: split out movement for slot {slot!r}")

            seen: dict[str, int] = {}
            for movement in movements:
                key = movement["key"] or "movement"
                if key in seen:
                    seen[key] += 1
                    movement["key"] = f"{key}_{seen[key]}"
                else:
                    seen[key] = 0
            outline.append(raw)
        self.outline = outline

        figures = []
        for figure in self.figures:
            items = [
                item for item in _as_list(figure.get("items"))
                if isinstance(item, dict)
                and (not known or str(item.get("claim", "")) in known)
            ]
            if not items:
                notes.append(f"dropped figure {figure.get('key') or figure.get('title')!r}: "
                             "no item pointed at a verified claim")
                continue
            figure["items"] = items
            figures.append(figure)
        self.figures = figures

        return notes

    # ------------------------------------------------------------- persistence
    def to_dict(self) -> dict:
        payload = {
            "version": SPEC_VERSION,
            "slug": self.slug,
            "title": self.title,
            "introduction": self.introduction,
            "audience": self.audience,
            "author": self.author,
            "voice": self.voice,
            "language": self.language,
            "chapters": self.chapters,
            "min_words": self.min_words,
            "max_words": self.max_words,
            "citation_style": self.citation_style,
            "reference_rules": list(self.reference_rules),
            "format_rules": list(self.format_rules),
            "quality_rules": list(self.quality_rules),
            "jargon": list(self.jargon),
            "glossary": dict(self.glossary),
            "outline": self.chapter_specs(),
            "sources": [
                {
                    "key": s.key,
                    "org": s.org,
                    "title": s.title,
                    "url": s.url,
                    "published": s.published,
                    "tier": s.tier,
                    "slots": list(s.slots),
                    "probes": [
                        {"key": p.key, "claim": p.claim, "pattern": p.pattern,
                         "required": p.required}
                        for p in s.probes
                    ],
                }
                for s in self.seeds()
            ],
            "probe_slots": dict(self.probe_slots),
            "corroboration": {k: list(v) for k, v in self.corroboration.items()},
            "slot_titles": dict(self.slot_titles),
            "figures": list(self.figures),
            "cover_palette": list(self.cover_palette),
            "prose_bank": self.prose_bank,
            "origin": self.origin,
            "notes": self.notes,
        }
        return payload

    @classmethod
    def from_dict(cls, raw: dict) -> "BookSpec":
        raw = dict(raw or {})
        title = str(raw.get("title", "")).strip()
        return cls(
            slug=slugify(str(raw.get("slug") or title)),
            title=title,
            introduction=str(raw.get("introduction", "")),
            audience=str(raw.get("audience") or "Readers new to the subject"),
            author=str(raw.get("author") or ""),
            voice=str(raw.get("voice") or DEFAULT_VOICE),
            language=str(raw.get("language") or "English"),
            chapters=int(raw.get("chapters") or 3),
            min_words=int(raw.get("min_words") or 600),
            max_words=int(raw.get("max_words") or 900),
            citation_style=str(raw.get("citation_style") or
                               "Every fact, figure and date carries a bracketed number like [1]."),
            reference_rules=_as_list(raw.get("reference_rules"), DEFAULT_REFERENCE_RULES),
            format_rules=_as_list(raw.get("format_rules"), DEFAULT_FORMAT_RULES),
            quality_rules=_as_list(raw.get("quality_rules"), DEFAULT_QUALITY_RULES),
            jargon=_as_list(raw.get("jargon")),
            glossary=_text_map(raw.get("glossary")),
            outline=_as_list(raw.get("outline")),
            sources=_as_list(raw.get("sources")),
            probe_slots=_text_map(raw.get("probe_slots")),
            corroboration={
                str(k): _as_list(v)
                for k, v in _as_dict(raw.get("corroboration")).items()
            },
            slot_titles=_text_map(raw.get("slot_titles")),
            figures=_as_list(raw.get("figures")),
            cover_palette=_as_list(raw.get("cover_palette")),
            prose_bank=str(raw.get("prose_bank") or ""),
            origin=str(raw.get("origin") or "curated"),
            notes=str(raw.get("notes", "")),
        )

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return path

    @classmethod
    def load(cls, path: Path) -> "BookSpec":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# --------------------------------------------------------------------- factory

def upi_spec() -> BookSpec:
    """The curated UPI book, expressed as a spec."""
    return BookSpec(
        slug="upi",
        title=UPI_BRIEF["title"],
        introduction=(
            "A shopkeeper's guide to how India came to pay by phone: what actually "
            "happens when a customer scans your QR code, what it costs you, what to "
            "do when something goes wrong, and where the system is heading."
        ),
        audience=UPI_BRIEF["audience"],
        language=UPI_BRIEF["language"],
        voice=UPI_BRIEF["voice"],
        chapters=UPI_BRIEF["chapters"],
        min_words=UPI_BRIEF["min_words"],
        max_words=UPI_BRIEF["max_words"],
        citation_style=UPI_BRIEF["citation_style"],
        reference_rules=list(UPI_BRIEF["reference_rules"]),
        format_rules=list(UPI_BRIEF["format_rules"]),
        quality_rules=list(UPI_BRIEF["quality_rules"]),
        jargon=list(JARGON),
        glossary=dict(UPI_GLOSSARY),
        outline=[
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
            for chapter in UPI_SKELETON
        ],
        sources=[
            {
                "key": seed.key,
                "org": seed.org,
                "title": seed.title,
                "url": seed.url,
                "published": seed.published,
                "tier": seed.tier,
                "slots": list(seed.slots),
                "probes": [
                    {"key": p.key, "claim": p.claim, "pattern": p.pattern,
                     "required": p.required}
                    for p in seed.probes
                ],
            }
            for seed in UPI_SEEDS
        ],
        probe_slots=dict(UPI_PROBE_SLOTS),
        corroboration={k: list(v) for k, v in UPI_CORROBORATION.items()},
        slot_titles=dict(UPI_SLOT_TITLES),
        figures=UPI_FIGURES,
        cover_palette=["#0f3d3e", "#12707a", "#e8b04b", "#f6f1e7", "#c8553d"],
        prose_bank="upi",
        origin="curated",
        notes=(
            "Bundled demonstration book: chapters are backed by a curated prose bank "
            "so the pipeline can run with no API key."
        ),
    )


UPI_FIGURES: list[dict] = [
    {
        "key": "ch1_scale",
        "chapter": 1,
        "kind": "bar",
        "title": "UPI transaction volume by financial year",
        "caption": "Crore transactions a year, from the same official release.",
        "items": [
            {"claim": "pib_55crore:fy_table", "value": "volume_fy2122", "label": "2021-22"},
            {"claim": "pib_10y:fy26_volume", "value": "volume_crore", "label": "2025-26"},
        ],
    },
    {
        "key": "ch1_ticket",
        "chapter": 1,
        "kind": "stat",
        "title": "What a typical shop payment looks like",
        "caption": "Person-to-merchant payments are the small ones.",
        "items": [
            {"claim": "pib_10y:p2m_share", "value": "p2m_volume_pct", "label": "of UPI volume is paid to shops"},
            {"claim": "pib_10y:p2m_small_ticket", "value": "pct_below_500", "label": "of those are under Rs 500"},
        ],
    },
    {
        "key": "ch2_charges",
        "chapter": 2,
        "kind": "donut",
        "title": "Where the charge rules stand now",
        "caption": "UPI stays free for people and for nearly all shop payments.",
        "items": [
            {"claim": "pib_mdr_96:mdr_rate", "value": "rate_pct", "label": "MDR above Rs 2,000"},
            {"claim": "pib_mdr_96:mdr_cap", "value": "cap_amount", "label": "MDR cap on large tickets"},
        ],
    },
    {
        "key": "ch3_fraud",
        "chapter": 3,
        "kind": "bar",
        "title": "Reported digital-payment fraud value",
        "caption": "Rupees lost to reported fraud, 2021 against 2025.",
        "items": [
            {"claim": "rbi_fraud_dp:fraud_table", "value": "value_2021", "label": "2021"},
            {"claim": "rbi_fraud_dp:fraud_table", "value": "value_2025", "label": "2025"},
        ],
    },
]

BUNDLED: dict[str, str] = {"upi": "Pay Me on UPI"}


def bundled_spec(name: str = "upi") -> BookSpec:
    if name != "upi":
        raise KeyError(f"no bundled spec named {name!r}")
    return upi_spec()


def spec_from_form(
    title: str,
    introduction: str,
    audience: str = "",
    chapters: int = 3,
    min_words: int = 600,
    max_words: int = 900,
    voice: str = "",
    urls: str = "",
    palette: str = "",
    author: str = "",
) -> BookSpec:
    """The starting point the Architect expands: what the index page collects."""
    source_urls = [u.strip() for u in re.split(r"[\s,]+", urls or "") if u.strip()]
    slug = slugify(title)
    pal = [c for c in re.split(r"[\s,]+", palette or "") if c.startswith("#")]
    return BookSpec(
        slug=slug,
        title=title.strip(),
        introduction=introduction.strip(),
        audience=audience.strip() or "Readers new to the subject",
        author=author.strip(),
        voice=voice.strip() or DEFAULT_VOICE,
        chapters=max(1, min(12, int(chapters or 3))),
        min_words=int(min_words or 600),
        max_words=int(max_words or 900),
        glossary={},
        outline=[],
        sources=[{"key": "", "org": "", "title": "", "url": u, "published": "",
                  "tier": "other", "slots": [], "probes": []} for u in source_urls],
        origin="requested",
        cover_palette=pal[:5],
        notes=(
            "Created from the studio index page; the Architect fills in the rest. "
            "Pinned links start untiered on purpose - what a publisher is gets "
            "decided from the page itself, not from the form."
        ),
    )