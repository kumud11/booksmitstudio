"""Brief-compliance checks.

These are deliberately dumb, regex-level rules. That is the point: a rule that a
human can read is a rule the Editor can defend and the Writer can be told to fix.
Anything subtler than this belongs in the Editor's language pass, not here.
"""

from __future__ import annotations

import re

from .models import (
    Draft,
    Issue,
    Severity,
    all_citation_marks,
    citations_in,
    count_words,
    numeric_tokens,
    numbers_equivalent,
)

# Prose may not contain list markers, headings or tables inside a chapter body.
LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+\S", re.M)
BOLD_LINE_RE = re.compile(r"^\s*\*\*.+\*\*\s*$", re.M)
HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.M)
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$", re.M)

# A figure, not a digit inside a name: "86%" and "2,001 crore" count, "P2M" and
# "FY2026" do not.
_STATED_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])[\d\u20b9]")

# Words that would break the "no jargon without explanation" rule if used raw.
JARGON = {
    "UPI": r"\bUPI\b",
    "QR code": r"\bQR code",
    "NPCI": r"\bNPCI\b",
    "MDR": r"\bMDR\b",
    "P2M": r"\bP2M\b",
    "IMPS": r"\bIMPS\b",
    "soundbox": r"\bsoundbox",
    "turn-around time": r"turn-around time",
    "auto-reversal": r"auto-reversal",
    "chargeback": r"\bchargeback",
    "UPI Lite": r"\bUPI Lite\b",
    "UPI 123Pay": r"\bUPI ?123Pay\b",
    "credit line": r"\bcredit line\b",
}

# Phrases a press release would use and a mentor would not.
TONE_BANNED = (
    "groundbreaking",
    "revolutionary",
    "leverage",
    "utilise",
    "utilize",
    "synergy",
    "ecosystem",
    "holistic",
    "seamless",
    "cutting-edge",
    "game-changer",
    "robust",
    "foster",
    "facilitate",
    "aforementioned",
    "in conclusion",
    "it is worth noting that",
    "delve",
    "landscape",
    "journey",
)

HEDGE_BANNED = ("obviously", "clearly", "simply put", "of course you know")


def jargon_patterns(brief: dict) -> dict[str, str]:
    """The terms that must be explained on first use, with a regex for each.

    A spec names its own jargon list, so a book on any subject polices its own
    terms. An empty list means "nothing to police": the UPI defaults apply only
    when a brief carries no jargon key at all.
    """
    if "jargon" in (brief or {}):
        terms = brief["jargon"] or ()
        if not terms:
            return {}
        out: dict[str, str] = {}
        for term in terms:
            text = str(term).strip()
            if text:
                out[text] = r"\s*".join(re.escape(part) for part in text.split())
        return out
    return JARGON


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'\u201c(])", text or "")
    return [p.strip() for p in parts if p.strip()]


def check_draft(draft: Draft, brief: dict, glossary: dict) -> list[Issue]:
    """Every rule the brief states, expressed as an Issue list."""
    issues: list[Issue] = []
    where = f"ch{draft.chapter_index}"
    body = draft.body or ""

    # --- length ---------------------------------------------------------
    words = count_words(body)
    if words < brief["min_words"]:
        issues.append(Issue(
            Severity.BLOCKING, "too-short",
            f"chapter is {words} words, brief requires at least {brief['min_words']}",
            where, "pad_to_length",
            "Add another movement from the plan, or expand existing paragraphs with "
            "explanatory detail drawn from the claim cards.",
        ))
    if words > brief["max_words"]:
        issues.append(Issue(
            Severity.BLOCKING, "too-long",
            f"chapter is {words} words, brief allows at most {brief['max_words']}",
            where, "trim_to_length",
            "Cut the least load-bearing paragraph; do not drop a cited fact.",
        ))
    elif brief["min_words"] <= words < brief["min_words"] + 40:
        issues.append(Issue(
            Severity.MINOR, "close-to-minimum",
            f"chapter is {words} words, only just above the {brief['min_words']} minimum",
            where, "pad_to_length",
        ))

    # --- no bullet points, headings or tables in the prose ---------------
    for label, pattern, code in (
        ("a list marker", LIST_MARKER_RE, "bullet-in-prose"),
        ("a bold-only line", BOLD_LINE_RE, "bold-line-in-prose"),
        ("a heading", HEADING_RE, "heading-in-prose"),
        ("a table row", TABLE_RE, "table-in-prose"),
    ):
        hit = pattern.search(body)
        if hit:
            issues.append(Issue(
                Severity.BLOCKING, code,
                f"the brief requires flowing prose but found {label}: "
                f"{hit.group(0).strip()[:60]!r}",
                where, "flatten_prose",
                "Rewrite that passage as a sentence.",
            ))

    # --- takeaway line ---------------------------------------------------
    takeaway = draft.takeaway_line()
    if not takeaway:
        issues.append(Issue(
            Severity.BLOCKING, "missing-takeaway",
            "no line starting with 'Takeaway:' before the reference list",
            where, "add_takeaway",
            "Add one sentence beginning exactly with 'Takeaway:'.",
        ))
    else:
        if not takeaway.startswith("Takeaway:"):
            issues.append(Issue(
                Severity.BLOCKING, "takeaway-prefix",
                f"takeaway must start with 'Takeaway:' but starts with "
                f"{takeaway[:30]!r}",
                where, "add_takeaway",
            ))
        if len(takeaway) > 260:
            issues.append(Issue(
                Severity.MINOR, "takeaway-long",
                f"takeaway is {count_words(takeaway)} words; keep it to one line",
                where, "shorten_takeaway",
            ))

    # --- citations -------------------------------------------------------
    marks = all_citation_marks(body)
    used = citations_in(body)
    declared = sorted(int(r["n"]) for r in draft.references)
    if not marks:
        issues.append(Issue(
            Severity.BLOCKING, "no-citations",
            "chapter body carries no citations but states facts",
            where, "add_citations",
            "Every fact, figure and date needs a bracketed citation.",
        ))
    missing_entries = [n for n in used if n not in declared]
    if missing_entries:
        issues.append(Issue(
            Severity.BLOCKING, "missing-reference-entry",
            f"citations {missing_entries} are used in the text but have no "
            "entry in the reference list",
            where, "rebuild_references",
            "Add the reference entries, or drop the citation marker.",
        ))
    unused_entries = [n for n in declared if n not in used]
    if unused_entries:
        issues.append(Issue(
            Severity.MAJOR, "unused-reference",
            f"reference list includes {unused_entries}, which the text never cites",
            where, "rebuild_references",
            "Remove those entries, or cite them.",
        ))
    if declared and declared != list(range(1, len(declared) + 1)):
        issues.append(Issue(
            Severity.MAJOR, "reference-numbering",
            f"reference list should be numbered 1..{len(declared)} consecutively; "
            f"found {declared}",
            where, "rebuild_references",
        ))
    for ref in draft.references:
        if not ref.get("url", "").startswith("http"):
            issues.append(Issue(
                Severity.BLOCKING, "reference-no-url",
                f"reference [{ref.get('n')}] has no working link",
                where, "rebuild_references",
            ))
        for field in ("org", "title"):
            if not str(ref.get(field, "")).strip():
                issues.append(Issue(
                    Severity.BLOCKING, "reference-incomplete",
                    f"reference [{ref.get('n')}] is missing its {field}",
                    where, "rebuild_references",
                ))

    # Any paragraph that states a figure must carry a citation inside it. This is
    # the rule the brief asks for, and it is checked per paragraph rather than per
    # sentence because a citation legitimately sits at the end of the thought that
    # contains several sentences.
    for para in [p for p in body.split("\n\n") if p.strip()]:
        if _STATED_NUMBER_RE.search(para) and not re.search(r"\[\d+\]", para):
            issues.append(Issue(
                Severity.BLOCKING, "uncited-number",
                f"a paragraph states a fact or figure with no citation: "
                f"...{para.strip()[:120]}...",
                where, "attach_citation",
                "Attach the citation marker for the source that carries this fact.",
            ))
            break

    # --- jargon glossing -------------------------------------------------
    for term, pattern in jargon_patterns(brief).items():
        if not re.search(pattern, body, re.I):
            continue
        gloss = glossary.get(term, "")
        head = gloss.split(",")[0].split("(")[0].strip() if gloss else term
        first = re.search(pattern, body, re.I)
        if not first:
            continue
        window = body[max(0, first.start() - 400): first.start() + 320].lower()
        flat = re.sub(r"\s+", "", window)
        if _defines_term(window, term) or _in_flat(flat, head) or _in_flat(flat, term):
            continue
        issues.append(Issue(
            Severity.MAJOR, "jargon-not-explained",
            f"'{term}' is used without being explained the first time",
            where, "gloss_term",
            f"Explain it on first use, e.g. mention {head!r} in the same sentence "
            "or the one after.",
        ))

    # --- tone -------------------------------------------------------------
    for word in TONE_BANNED:
        hit = re.search(rf"\b{re.escape(word)}\b", body, re.I)
        if hit:
            issues.append(Issue(
                Severity.MAJOR, "tone-register",
                f"word {word!r} reads like a press release, not a mentor",
                where, "replace_register",
                "Use plain, everyday words instead.",
            ))
    for word in HEDGE_BANNED:
        if re.search(rf"\b{re.escape(word)}\b", body, re.I):
            issues.append(Issue(
                Severity.MINOR, "tone-dismissive",
                f"{word!r} can sound condescending to a nervous first-time owner",
                where, "replace_register",
            ))

    # --- micro-grammar and punctuation ------------------------------------
    # Checked paragraph by paragraph, because the blank line between paragraphs
    # is two whitespace characters and would otherwise look like a double space.
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    for pattern, code, message in (
        (r"[^\S\n]{2,}", "double-space", "contains a run of spaces mid-sentence"),
        (r"[^\S\n]+[,.!?;]", "space-before-punctuation",
         "has a space before a punctuation mark"),
        (r"[!?]{2,}", "repeated-punctuation", "repeats a punctuation mark"),
        (r"\bi\b", "wrong-i-form", "writes the pronoun 'i' without a capital"),
        (r"\b(teh|adn|recieve|seperate|occured|comitted|untill|wich|becuase)\b",
         "spelling", "contains a common misspelling"),
        (r"\b(its')\b", "apostrophe-confusion", "writes \"its'\" where \"it's\" is meant"),
        (r"\b([a-z]+ [A-Z][a-z]+)\b\s+\1\b", "word-repetition",
         "repeats a word back-to-back"),
    ):
        hit = None
        for para in paragraphs:
            hit = re.search(pattern, para)
            if hit:
                break
        if hit:
            issues.append(Issue(
                Severity.MAJOR, code,
                f"{message}: {hit.group(0).strip()[:50]!r}",
                where, "fix_typo", "Correct it.",
            ))

    # unbalanced quotes and brackets
    if body.count('"') % 2:
        issues.append(Issue(
            Severity.MAJOR, "unbalanced-quotes",
            "quotation marks are unbalanced", where, "fix_typo",
        ))
    for open_c, close_c in (("(", ")"), ("[", "]")):
        if body.count(open_c) != body.count(close_c):
            issues.append(Issue(
                Severity.MINOR, "unbalanced-brackets",
                f"{open_c!r} and {close_c!r} counts do not match",
                where, "fix_typo",
            ))

    # --- readability ------------------------------------------------------
    sentences = _split_sentences(body)
    if sentences:
        longest = max(sentences, key=lambda s: count_words(s))
        if count_words(longest) > 45:
            issues.append(Issue(
                Severity.MINOR, "sentence-too-long",
                f"longest sentence is {count_words(longest)} words "
                f"({longest.strip()[:80]!r})",
                where, "split_sentence",
            ))
        very_long = [s for s in sentences if count_words(s) > 55]
        if very_long:
            issues.append(Issue(
                Severity.MAJOR, "run-on-sentences",
                f"{len(very_long)} sentence(s) exceed 55 words",
                where, "split_sentence",
            ))
        staccato = sum(1 for s in sentences if count_words(s) <= 4)
        if len(sentences) >= 8 and staccato / len(sentences) > 0.35:
            issues.append(Issue(
                Severity.MINOR, "choppy-rhythm",
                f"{staccato} of {len(sentences)} sentences are four words or fewer",
                where, "vary_sentence_length",
            ))

    return issues


def _in_flat(flat_window: str, phrase: str) -> bool:
    """Compare ignoring spacing, so 'UPI123Pay' matches 'UPI 123Pay'."""
    return re.sub(r"\s+", "", phrase).lower() in flat_window


def _defines_term(window: str, term: str) -> bool:
    """True when the window reads like an explanation of the term."""
    target = re.escape(term.lower())
    patterns = (
        rf"{target}\s*,?\s*(?:which|that|is|means|stands for)\b",
        rf"\bis\s+(?:a|an|the)\b[^.]{{0,140}}?{target}",
        rf"\bmeans\b[^.]{{0,140}}?{target}",
        rf"\b(referred to as|called|known as|that is,)\b[^.]{{0,160}}?{target}",
        rf"\bstands for\b[^.]{{0,140}}",
        rf"{target}[^.]{{0,140}}?\b(?:which|that is|which is)\b",
        rf"in simple terms[^.]{{0,180}}?{target}",
    )
    return any(re.search(p, window, re.I) for p in patterns)


def unexplained_numbers(text: str, allowed_values: dict) -> list[str]:
    """Numeric tokens in `text` that no allowed value accounts for.

    Shared by the Fact-checker's audit and the Writer's trimmer, so the Writer
    cannot keep a sentence the Fact-checker would reject.
    """
    return [
        token
        for token in numeric_tokens(text)
        if not _allowed(token, allowed_values)
    ]


def check_numbers_are_sourced(draft: Draft, allowed_values: dict) -> list[Issue]:
    """The number audit.

    Every numeric token in the prose must be explainable by a figure the
    Researcher lifted from a cited page, or by the chapter/series numbering the
    book itself introduces. This is the check that catches a hallucinated
    statistic even when a plausible citation is attached to it.
    """
    issues: list[Issue] = []
    where = f"ch{draft.chapter_index}"

    corpus = numeric_tokens(draft.body) + numeric_tokens(draft.takeaway_line())
    unexplained = [token for token in corpus if not _allowed(token, allowed_values)]

    if unexplained:
        unique = sorted(set(unexplained))
        issues.append(Issue(
            Severity.BLOCKING, "unsourced-number",
            f"{len(unexplained)} numeric token(s) in the prose are not present in "
            f"any cited source's captured evidence: {unique[:14]}",
            where, "remove_unsourced_numbers",
            "Rewrite the sentence without that figure, or cite a source that "
            "actually carries it.",
        ))
    return issues


# Numbers the book legitimately introduces about itself.
SELF_REFERENCE_NUMBERS = {
    "1", "2", "3", "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten",
}


def _allowed(token: str, allowed_values: dict) -> bool:
    core = re.sub(r"[%]|per cent|crore|lakh|billion|million", "", token).strip()
    if core in SELF_REFERENCE_NUMBERS or token in SELF_REFERENCE_NUMBERS:
        return True
    for value in allowed_values.values():
        if numbers_equivalent(token, value):
            return True
        for part in re.split(r"[,\s]+", str(value)):
            if part and numbers_equivalent(token, part):
                return True
    return False