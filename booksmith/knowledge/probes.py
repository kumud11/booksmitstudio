"""Read a page and find the sentences worth citing.

A human researcher picks the sentence that carries the number and writes a probe
around it. Without a language model nobody is around to pick, so this module does
the mechanical half of that job: find sentences that carry a figure, and turn each
one into a regex that will match it again tomorrow, with every number captured
into a named group so the Writer can quote it and the FactChecker can re-check it.

The judgement left out on purpose: nothing here decides what a book should argue.
It only decides which sentences are quotable evidence.
"""

from __future__ import annotations

import re

from ..models import EvidenceProbe

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\u201c])")

UNIT_WORDS = (
    "crore", "lakh", "billion", "million", "trillion", "per cent", "percent",
    "%", "rupees", "lakh crore",
)

NUMBER = re.compile(
    r"(?:\u20b9|Rs\.?|INR|US\$|\$|EUR|\u20ac)?\s?"
    r"\d[\d,]*(?:\.\d+)?\s?"
    r"(?:%|per cent|crore|lakh|billion|million|trillion)?",
    re.I,
)

INTERESTING = re.compile(
    r"(?:\u20b9|Rs\.?|INR|\$)\s*\d|\d[\d,.]*\s*(?:%|per cent|crore|lakh|billion|million)"
    r"|\d{2,}",
    re.I,
)

SKIP = re.compile(
    r"(?:https?://|www\.|©|copyright|share this|follow us|advertisement|"
    r"cookie|privacy policy|all rights reserved)",
    re.I,
)

# Captions and section labels carry numbers but say nothing: "Fig 3: UPI Monthly
# Transaction Volume" is a label on a chart, not a fact anyone published.
CAPTION = re.compile(
    r"^\s*(?:fig(?:ure)?|table|chart|exhibit|graph|box|note|notes|source|"
    r"annex|table\s+of\s+contents|key\s+takeaways)\b",
    re.I,
)
SECTION_MARK = re.compile(r"^\s*(?:[IVXLC]{1,6}\.?|[A-Z]\.|\d{1,2}\.)\s")

MAX_CLAIM_CHARS = 600

DEFINITION = re.compile(
    r"\b([A-Z][A-Za-z0-9/&.\-]{2,30})\s*"
    r"(?:\(([^)]{2,24})\))?\s*,?\s+"
    r"(?:which|that is|means|refers to|stands for|also called|also known as|"
    r"is defined|are defined|is the|are the|is a|are a)\b",
)

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
HEADING_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)


def sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    return [s.strip() for s in SENTENCE_SPLIT.split(cleaned) if s.strip()]


def quotable(text: str, limit: int = 3) -> list[str]:
    """The sentences on a page most worth turning into claims.

    Ranked by how much a reader could be told from them: a unit or a currency
    beats a bare number, a full sentence beats a table row, and anything that
    reads like site furniture is dropped outright.
    """
    scored: list[tuple[int, str]] = []
    for sentence in sentences(text):
        if not INTERESTING.search(sentence) or SKIP.search(sentence):
            continue
        if CAPTION.match(sentence) or SECTION_MARK.match(sentence):
            continue
        # Markup that survived the page's own escaping is not quotable prose.
        if "<" in sentence or ">" in sentence:
            continue
        words = sentence.split()
        if not 6 <= len(words) <= 45:
            continue
        # A row lifted out of a table reads as a list of proper nouns rather than a
        # sentence anyone wrote, so it is not quoted even when it holds numbers.
        capitalised = sum(1 for w in words if w[:1].isupper())
        if capitalised > max(2, len(words) // 2):
            continue
        if sentence.count(",") > 6 or len(NUMBER.findall(sentence)) > 4:
            continue
        score = 2
        if re.search(r"(?:\u20b9|Rs\.?|INR|\$)\s*\d", sentence, re.I):
            score += 3
        if re.search(r"\d[\d,.]*\s*(?:%|per cent|crore|lakh|billion|million)", sentence, re.I):
            score += 3
        if sentence[0:1].isupper():
            score += 1
        if 10 <= len(words) <= 30:
            score += 1
        if sentence.endswith((".", "!", "?")):
            score += 1
        scored.append((score, sentence))

    scored.sort(key=lambda pair: (-pair[0], len(pair[1])))
    picked: list[str] = []
    seen_numbers: set[str] = set()
    for _, sentence in scored:
        numbers = {n.strip() for n in NUMBER.findall(sentence)}
        # Two claims carrying the same figures are the same claim twice.
        if numbers and numbers <= seen_numbers:
            continue
        picked.append(sentence)
        seen_numbers |= numbers
        if len(picked) >= limit:
            break
    return picked


def pattern_for(sentence: str) -> str:
    """A regex that matches this sentence on a page, numbers captured.

    Whitespace in the source collapses to `\\s+` so a line break in the HTML never
    breaks the probe, and every figure becomes a named group the Writer may quote.
    """
    parts: list[str] = []
    last = 0
    index = 0
    for match in NUMBER.finditer(sentence):
        literal = sentence[last:match.start()]
        if literal.strip():
            parts.append(_escape_literal(literal))
        parts.append(f"(?P<figure{index}>\\s*{_escape_literal(match.group(0))})")
        index += 1
        last = match.end()
    tail = sentence[last:]
    if tail.strip():
        parts.append(_escape_literal(tail))
    if index == 0:
        return ""
    return "".join(parts)


def _escape_literal(text: str) -> str:
    """Escape regex syntax, but let whitespace stay flexible."""
    chunks = re.split(r"(\s+)", text)
    out = []
    for chunk in chunks:
        if not chunk:
            continue
        if chunk.isspace():
            out.append(r"\s+")
        else:
            out.append(re.escape(chunk))
    return "".join(out)


def derive_probes(text: str, org: str = "", limit: int = 3) -> list[EvidenceProbe]:
    """Evidence probes for a page, taken from its own quotable sentences."""
    probes: list[EvidenceProbe] = []
    for index, sentence in enumerate(quotable(text, limit=limit)):
        pattern = pattern_for(sentence)
        if len(pattern) < 20:
            continue
        # The claim is the sentence as the source wrote it. Cutting it short
        # would leave a fragment that means less than the original and quotes
        # badly, so the full sentence is kept and the Writer breaks it up if the
        # source made it long.
        claim = sentence if len(sentence) <= MAX_CLAIM_CHARS else sentence[:MAX_CLAIM_CHARS]
        probes.append(EvidenceProbe(
            key=f"figure{index + 1}",
            claim=f"{org + ' reports that ' if org else ''}{claim}",
            pattern=pattern,
            required=False,
        ))
    return probes


def glossary_from(text: str, limit: int = 6) -> dict[str, str]:
    """Terms the page defines for itself, glossed in the page's own words."""
    out: dict[str, str] = {}
    for sentence in sentences(text):
        match = DEFINITION.search(sentence)
        if not match:
            continue
        term = match.group(1).strip()
        if len(term) < 3 or term.lower() in out:
            continue
        if term.isupper() and len(term) > 12:
            continue
        gloss = sentence.rstrip(".").strip()
        if len(gloss) > 200:
            continue
        out[term] = gloss
        if len(out) >= limit:
            break
    return out


def page_title(raw_html: str, fallback: str = "") -> str:
    """The page's own headline, which beats its <title> for a reference list.

    Publishers often give every press release the same <title> ("Press Release
    Page"), so the heading on the page is the part worth citing.
    """
    for pattern in (HEADING_RE, TITLE_RE):
        match = pattern.search(raw_html or "")
        if not match:
            continue
        text = re.sub(r"<[^>]+>", " ", match.group(1))
        text = re.sub(r"\s+", " ", text).strip(" |-\u2013\u2014")
        text = re.sub(r"\s*[|\-]\s*[A-Z][\w. ]{2,}$", "", text)
        if len(text) >= 12:
            return text[:160]
    return fallback


TIER_BY_HOST = {
    "npci.org.in": "official",
    "npci.org": "official",
    "paytm.com": "official",
    "bhimupi.org.in": "official",
    "rbi.org.in": "regulator",
    "sebi.gov.in": "regulator",
    "indiabudget.gov.in": "regulator",
    "egazette.gov.in": "regulator",
    "financialservices.gov.in": "regulator",
    "thehindu.com": "reputable_press",
    "indianexpress.com": "reputable_press",
    "timesofindia.indiatimes.com": "reputable_press",
    "economictimes.indiatimes.com": "reputable_press",
    "livemint.com": "reputable_press",
    "business-standard.com": "reputable_press",
    "moneycontrol.com": "reputable_press",
    "reuters.com": "reputable_press",
    "pib.gov.in": "official",
}


def tier_for(url: str) -> str:
    """What kind of publisher a domain is, by domain alone.

    Only the hosts whose nature is not in doubt are named; everything else stays
    `other`, which the Researcher treats as unproven rather than as poor.
    """
    host = re.sub(r"^https?://(www\.)?", "", url or "").split("/")[0].lower()
    if host in TIER_BY_HOST:
        return TIER_BY_HOST[host]
    for known, tier in TIER_BY_HOST.items():
        if host.endswith("." + known) or host == known:
            return tier
    return "other"


def publisher_for(url: str) -> str:
    """A short, honest name for whoever published the page.

    Without a model there is nobody to read the masthead, so the domain does the
    identifying: `www.rbi.org.in` is called RBI. It is a placeholder the publisher
    can overwrite in spec.json, and it never invents an organisation that is not
    the one serving the page.
    """
    host = re.sub(r"^https?://(www\.)?", "", url or "").split("/")[0].lower()
    label = host.split(".")[0] if host else "source"
    if not label or label in ("co", "com", "org", "gov", "in", "www"):
        parts = [p for p in host.split(".") if p not in ("www", "in", "com", "co")]
        label = parts[0] if parts else label or "source"
    if len(label) <= 4 and label.isalpha():
        return label.upper()
    return label.replace("-", " ").title()