"""Typed artefacts that the agents hand to each other.

The whole design rests on one rule: a fact may only enter the book by travelling
from a `Source`, through a `Claim`, into a `Draft`. Nothing is allowed to appear
in prose that is not carried by a claim whose evidence was read off a live page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    BLOCKING = "blocking"   # cannot ship: wrong fact, dead link, missing citation
    MAJOR = "major"         # should fix: readability, tone, brief non-compliance
    MINOR = "minor"         # nice to fix: polish


class Verdict(str, Enum):
    PASS = "pass"
    REVISE = "revise"
    REJECT = "reject"


# Authority ranking used by the Researcher when two sources disagree.
TIER_RANK = {"official": 0, "regulator": 1, "reputable_press": 2, "other": 3}


@dataclass
class EvidenceProbe:
    """A testable assertion about what a source page must literally contain.

    `pattern` is applied to the fetched page text. Named capture groups become
    `Claim.values`, which is the *only* channel through which a number can reach
    the prose. If the page stops matching, the fact-checker fails the citation.
    """

    key: str
    claim: str                      # plain-English statement of the fact
    pattern: str                    # regex, may use named groups
    required: bool = True


@dataclass
class SourceSeed:
    """A candidate source, before the Researcher has looked at it."""

    key: str
    org: str
    title: str
    url: str
    published: str
    tier: str = "official"
    slots: tuple[str, ...] = ()
    probes: tuple[EvidenceProbe, ...] = ()


@dataclass
class Source:
    """A candidate source after live verification."""

    key: str
    org: str
    title: str
    url: str
    published: str
    tier: str
    slots: list[str] = field(default_factory=list)
    reachable: bool = False
    status: str = "unchecked"
    status_detail: str = ""
    # probe key -> {"snippet": readable context, "match": whole regex match}
    evidence: dict[str, dict[str, str]] = field(default_factory=dict)
    probe_matches: dict[str, bool] = field(default_factory=dict)

    @property
    def authority(self) -> int:
        return TIER_RANK.get(self.tier, 9)

    @property
    def confirmed_probes(self) -> list[str]:
        return [k for k, ok in self.probe_matches.items() if ok]

    @property
    def usable(self) -> bool:
        """Reachable and at least one probe actually matched the live page."""
        return self.reachable and bool(self.confirmed_probes)

    def values_for(self, pattern: str) -> dict[str, str]:
        """Re-run a probe pattern over the matched text to lift named captures.

        A capture only exists if the exact pattern that produced the evidence is
        re-applied to the exact text that matched it, so a number in the book can
        be traced back to a character range on a live page.
        """
        import re

        names = re.findall(r"\(\?P<([A-Za-z_][A-Za-z0-9_]*)>", pattern)
        if not names:
            return {}
        out: dict[str, str] = {}
        for record in self.evidence.values():
            match = re.search(pattern, record.get("match", ""), re.I | re.S)
            if not match:
                continue
            for name in names:
                try:
                    value = match.group(name)
                except (IndexError, KeyError):
                    continue
                if value is not None and name not in out:
                    out[name] = value.strip()
            if len(out) == len(names):
                break
        return out


@dataclass
class Claim:
    """One checkable statement, tied to one or more verified sources."""

    id: str
    slot: str
    text: str                      # how the writer may express it
    probe_keys: list[str] = field(default_factory=list)
    source_keys: list[str] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)   # named captures
    verified: bool = False
    source_dead: bool = False      # URL stopped resolving
    unsupported: bool = False      # evidence no longer on the page

    def render(self) -> str:
        """How the claim is shown to the Writer as a usable card."""
        bits = [self.text]
        if self.values:
            pairs = ", ".join(f"{k}={v}" for k, v in sorted(self.values.items()))
            bits.append(f"(use exactly: {pairs})")
        return " - ".join(bits)


@dataclass
class Movement:
    """A beat in a chapter outline: a purpose plus the claim slots it needs."""

    key: str
    intent: str
    slots: tuple[str, ...] = ()
    terms: tuple[str, ...] = ()      # jargon this beat must gloss on first use


@dataclass
class ChapterPlan:
    index: int
    title: str
    purpose: str
    movements: list[Movement] = field(default_factory=list)
    target_words: int = 760
    must_cover: list[str] = field(default_factory=list)


@dataclass
class BookPlan:
    title: str
    audience: str
    voice: str
    chapters: list[ChapterPlan] = field(default_factory=list)
    glossary: dict[str, str] = field(default_factory=dict)
    notes: str = ""


@dataclass
class Issue:
    severity: Severity
    code: str
    message: str
    location: str = ""
    fix_kind: str = ""      # mechanical fix the Writer can apply without a model
    hint: str = ""


@dataclass
class Report:
    agent: str
    issues: list[Issue] = field(default_factory=list)
    verdict: Verdict = Verdict.PASS
    metrics: dict[str, str] = field(default_factory=dict)

    def blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.BLOCKING]

    def major(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.MAJOR]

    def minor(self) -> list[Issue]:
        return [i for i in self.issues if i.severity is Severity.MINOR]

    def blocking_codes(self) -> list[str]:
        return [i.code for i in self.blocking()]

    def extend(self, other: "Report") -> None:
        self.issues.extend(other.issues)

    def render(self) -> str:
        if not self.issues:
            return f"{self.agent}: PASS"
        lines = [f"{self.agent}: {len(self.issues)} issue(s) -> {self.verdict.value.upper()}"]
        for issue in sorted(self.issues, key=lambda i: list(Severity).index(i.severity)):
            where = f" @{issue.location}" if issue.location else ""
            lines.append(
                f"  [{issue.severity.value.upper()}] {issue.code}{where}: {issue.message}"
            )
        return "\n".join(lines)


@dataclass
class Draft:
    chapter_index: int
    title: str
    body: str                       # prose only, no takeaway, no reference list
    takeaway: str = ""
    references: list[dict] = field(default_factory=list)   # n -> ref dict
    reference_map: dict[int, dict] = field(default_factory=dict)
    claim_ids_used: list[str] = field(default_factory=list)
    citations_used: list[int] = field(default_factory=list)
    backend: str = ""
    revision: int = 0

    def word_count(self) -> int:
        return count_words(self.body)

    def takeaway_line(self) -> str:
        text = self.takeaway.strip()
        if not text:
            return ""
        if text.lower().startswith("takeaway:"):
            return text
        return "Takeaway: " + text

    def reference_block(self) -> str:
        lines = []
        for ref in sorted(self.references, key=lambda r: int(r["n"])):
            org = ref.get("org", "")
            title = ref.get("title", "")
            url = ref.get("url", "")
            date = ref.get("published", "")
            date_part = f", {date}" if date else ""
            lines.append(f"[{ref['n']}] {org}, “{title}”{date_part}. {url}")
        return "\n\n".join(lines)

    def render(self) -> str:
        parts = [f"## {self.title}", "", self.body.strip()]
        takeaway = self.takeaway_line()
        if takeaway:
            parts += ["", takeaway]
        if self.references:
            parts += ["", "**References**", "", self.reference_block()]
        return "\n".join(parts)


# ---------------------------------------------------------------- text helpers

_WORD_RE = re.compile(r"[A-Za-z0-9₹%'’\-\.]+")
_CITATION_RE = re.compile(r"\[(\d{1,3})\]")
# 24,161.69 / 24,161 / ₹314 / 86% / FY2025-26 / 8 March 2022 / 1.5 crore
_NUMBER_RE = re.compile(
    r"(?:₹\s*)?\d[\d,]*(?:\.\d+)?\s*(?:%|per cent|crore|lakh|billion|million)?",
    re.I,
)
_DATE_RE = re.compile(
    r"\b(?:\d{1,2}\s+)?(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{4}\b",
    re.I,
)
# P2M, P2P, FY2025-26, Q3: a digit inside a name is part of the name, not a
# figure anyone asserted, so these are lifted out before numbers are read.
_CODE_RE = re.compile(r"\b[A-Za-z]+\d[A-Za-z0-9\-]*\b")


def count_words(text: str) -> int:
    """Word count that keeps '₹314' and 'FY2025-26' as single words."""
    return len(_WORD_RE.findall(text or ""))


def citations_in(text: str) -> list[int]:
    """Citation numbers in order of first appearance, de-duplicated."""
    seen: list[int] = []
    for match in _CITATION_RE.finditer(text or ""):
        n = int(match.group(1))
        if n not in seen:
            seen.append(n)
    return seen


def all_citation_marks(text: str) -> list[int]:
    return [int(m.group(1)) for m in _CITATION_RE.finditer(text or "")]


def numeric_tokens(text: str) -> list[str]:
    """Every number-ish token in the text, normalised for comparison."""
    tokens: list[str] = []
    codes: list[re.Match] = list(_CODE_RE.finditer(text or ""))
    for match in codes:
        tokens.append(match.group(0).lower())
    plain = _CODE_RE.sub(" ", text or "")
    for match in _NUMBER_RE.finditer(plain):
        raw = match.group(0)
        cleaned = raw.replace("₹", "").replace(",", "").strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not cleaned or cleaned == ".":
            continue
        tokens.append(cleaned.lower())
    for match in _DATE_RE.finditer(plain):
        tokens.append(re.sub(r"\s+", " ", match.group(0)).lower())
    return tokens


def normalise_number(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("₹", "").replace(",", "")).strip().lower()


def numbers_equivalent(token: str, candidate: str) -> bool:
    """Tolerant numeric equality used by the fact-checker's number audit.

    Handles '86' == '86%' == '86 per cent', '1.5' == '1.50', and Indian-lakh
    style spacing. It is deliberately strict about digits, because a wrong digit
    is exactly the failure mode we want to catch.
    """
    tok = normalise_number(token)
    cand = normalise_number(candidate)
    if not tok or not cand:
        return False
    tok_core = re.sub(r"[%]|per cent|crore|lakh|billion|million", "", tok).strip()
    cand_core = re.sub(r"[%]|per cent|crore|lakh|billion|million", "", cand).strip()
    for a, b in ((tok, cand), (tok_core, cand_core)):
        try:
            if abs(float(a) - float(b)) < 1e-9:
                return True
        except ValueError:
            continue
    # '5-6' style ranges and '2025-26' year spans compare as their first number.
    a = tok_core.split("-")[0]
    b = cand_core.split("-")[0]
    try:
        return abs(float(a) - float(b)) < 1e-9
    except ValueError:
        return tok_core in cand_core or cand_core in tok_core