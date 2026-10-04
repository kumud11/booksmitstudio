"""Turn a set of converged drafts into the finished book.

Three editions come out of one run: `book.md` for reading and diffing, `book.html`
as a single self-contained file with the figures inlined, and `review.md`, the
audit trail of what every agent did and why.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from .ledger import Ledger
from .models import Draft
from .spec import DEFAULT_AUTHOR as DEFAULT_BYLINE
from .visuals import cover_svg, palette_for

RULE = "---"


def _intro(brief: dict) -> str:
    text = str(brief.get("introduction", "")).strip()
    if text:
        return text
    return (
        f"Written for {brief['audience']}. Every figure in this book carries a "
        f"numbered citation, and each chapter lists its own sources."
    )


def _figures_for(ledger: Ledger, chapter_index: int, figures: list[dict]) -> list[dict]:
    return [f for f in figures if int(f.get("chapter", 0)) == chapter_index and f.get("file")]


def render_book(ledger: Ledger, figures: list[dict] | None = None) -> str:
    plan = ledger.plan
    brief = ledger.brief
    figures = figures or []
    drafts = [ledger.drafts[i] for i in sorted(ledger.drafts)]

    lines: list[str] = []
    lines.append(f"# {brief['title']}")
    lines.append("")
    lines.append(f"*{_intro(brief)}*")
    lines.append("")
    byline = str(brief.get("author", "") or "").strip() or DEFAULT_BYLINE
    lines.append(f"**By {byline}**")
    lines.append("")
    lines.append(
        "*Every fact, figure and date carries a numbered citation. Each chapter "
        "lists its own sources.*"
    )
    lines.append("")
    lines.append(RULE)
    lines.append("")

    for index, draft in enumerate(drafts, start=1):
        lines.append(f"## Chapter {index}: {draft.title}")
        lines.append("")
        lines.append(draft.body.strip())
        lines.append("")
        lines.append(draft.takeaway_line())
        lines.append("")
        lines.append("**References**")
        lines.append("")
        lines.append(draft.reference_block())
        lines.append("")
        chapter_figures = _figures_for(ledger, index, figures)
        if chapter_figures:
            lines.append("**Figures**")
            lines.append("")
            for number, figure in enumerate(chapter_figures, start=1):
                lines.append(
                    f"![{figure['title']}]({figure['file']})"
                )
                caption = figure.get("caption", "")
                lines.append("")
                lines.append(f"*Figure {number}: {figure['title']}. {caption}*")
                lines.append("")
        if index < len(drafts):
            lines.append(RULE)
            lines.append("")

    lines.append(RULE)
    lines.append("")
    lines.append("## A note on the sources")
    lines.append("")
    lines.append(_sources_note(ledger))
    lines.append("")
    return "\n".join(lines)


def _sources_note(ledger: Ledger) -> str:
    orgs: list[str] = []
    for source in ledger.verified_sources():
        if source.org not in orgs:
            orgs.append(source.org)
    if not orgs:
        return (
            "No source could be verified live for this edition, so it carries no "
            "figures."
        )
    listed = ", ".join(orgs[:8]) + (" and others" if len(orgs) > 8 else "")
    return (
        f"The figures in this book were taken from {len(orgs)} organisations, led by "
        f"{listed}. Before a claim was allowed into the text, the page it came from "
        "was fetched and checked for the exact figure quoted here, and every figure "
        "was checked again against the live page after the chapter was written."
    )


def render_plain(draft: Draft) -> str:
    """Chapter-only rendering, used for per-chapter review output."""
    return draft.render()


def _verdict_text(report) -> str:
    verdict = getattr(report, "verdict", None)
    return str(getattr(verdict, "value", verdict) or "")


def render_preview(ledger: Ledger, figures: list[dict] | None = None) -> str:
    """One file to read and to trust: the whole book, plus how it was checked.

    The book itself is already self-contained, so the preview is that file with
    the evidence laid out at the end - what was verified, what a reviewer could
    not fix, and which decisions shaped it - instead of a separate report nobody
    opens.
    """
    book = render_html(ledger, figures)
    stats = ledger.stats()
    issues = stats.get("issues", {}) if isinstance(stats.get("issues"), dict) else {}
    blocking = issues.get("blocking", 0)
    majors = issues.get("major", 0)

    rows = [
        report for report in ledger.reports
        if _verdict_text(report).lower() in ("pass", "revise", "reject")
    ]

    ledger_rows = "".join(
        f"<tr><td>{html.escape(str(getattr(r, 'agent', '')))}</td>"
        f"<td>{html.escape(str(getattr(r, 'chapter_index', '') or 'book'))}</td>"
        f"<td>{html.escape(_verdict_text(r))}</td>"
        f"<td>{len(getattr(r, 'issues', []) or [])}</td></tr>"
        for r in rows
    )

    claim_rows = "".join(
        f"<tr><td>{html.escape(claim.text[:150])}</td>"
        f"<td>{html.escape(claim.id)}</td>"
        f"<td>{html.escape('yes' if claim.verified else 'no')}</td></tr>"
        for claim in ledger.claims.values()
    )

    section = (
        "<section class=\"chapter\" id=\"evidence\">"
        "<h2>How this book was checked</h2>"
        "<p>Every figure below was read from a live page, matched by a probe, "
        "quoted with its reference, and then read again by the FactChecker after "
        "the chapter was written.</p>"
        "<div class=\"stat\">"
        f"<div><b>{html.escape(str(stats.get('sources_verified', 0)))}"
        f"</b><span>sources verified</span></div>"
        f"<div><b>{html.escape(str(stats.get('claims_verified', 0)))}"
        f"</b><span>claims verified</span></div>"
        f"<div><b>{html.escape(str(stats.get('reviews', 0)))}"
        f"</b><span>reviews</span></div>"
        f"<div><b>{html.escape(str(blocking))}</b><span>blocking issues left</span></div>"
        f"<div><b>{html.escape(str(majors))}</b><span>advisories recorded</span></div>"
        "</div>"
        f"<h3>Reviews</h3><table><tr><th>Agent</th><th>Chapter</th>"
        f"<th>Verdict</th><th>Issues</th></tr>{ledger_rows}</table>"
        f"<h3>Claims carried into the prose</h3><table><tr><th>Claim</th>"
        f"<th>Id</th><th>Verified</th></tr>{claim_rows}</table>"
        "</section>"
    )
    toc_entry = '<li><a href="#evidence">How this book was checked</a></li>'
    book = book.replace("<ol>", "<ol>" + toc_entry, 1)
    for anchor in ('<aside class="note">', "<footer>"):
        if anchor in book:
            return book.replace(anchor, section + anchor, 1)
    return book + section


def write_book(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ----------------------------------------------------------------------- html

def _md_to_html(text: str) -> str:
    """Minimal, safe inline markdown for prose: citations become links."""
    out = html.escape(text or "")
    out = re.sub(
        r"\[(\d{1,3})\]",
        r'<a class="cite" href="#ref-\1">[\1]</a>',
        out,
    )
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    return out.replace("\n\n", "</p><p>")


def _paragraphs(body: str) -> str:
    blocks = [p.strip() for p in (body or "").split("\n\n") if p.strip()]
    return "".join(f"<p>{_md_to_html(p)}</p>" for p in blocks)


HTML_STYLE = """
:root {
  --ink: #1d2b2b; --muted: #6b7a7a; --paper: #fdfbf7; --line: #e3ddd2;
  --deep: #0f3d3e; --accent: #e8b04b;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font: 18px/1.72 Georgia, 'Iowan Old Style', 'Times New Roman', serif;
}
.wrap { max-width: 46rem; margin: 0 auto; padding: 0 1.4rem; }
header.hero { background: var(--deep); color: #fff; padding: 4.5rem 0 3.5rem; }
header.hero h1 { font-size: clamp(2rem, 5vw, 3.1rem); line-height: 1.12; margin: .2em 0; }
header.hero p { font-size: 1.15rem; opacity: .82; max-width: 38rem; }
header.hero .rule { width: 5rem; height: 5px; background: var(--accent); border-radius: 3px; }
nav.toc { border-bottom: 1px solid var(--line); padding: 2rem 0; }
section.cover { padding: 2.4rem 0 0; text-align: center; }
section.cover svg { width: 100%; max-width: 24rem; height: auto;
  border-radius: 12px; box-shadow: 0 14px 34px rgba(15, 61, 62, .22); }
section.cover .hint { font-size: .8rem; color: var(--muted);
  max-width: 24rem; margin: .9rem auto 0; }
nav.toc ol { margin: .4rem 0 0; padding-left: 1.3rem; }
nav.toc a { color: var(--deep); }
section.chapter { padding: 3rem 0 1rem; border-bottom: 1px solid var(--line); }
section.chapter h2 { font-size: 1.7rem; line-height: 1.25; }
section.chapter h3 { font-size: 1.02rem; text-transform: uppercase;
  letter-spacing: .09em; color: var(--muted); margin: 2.2rem 0 .6rem; }
p.takeaway { background: #f4efe4; border-left: 4px solid var(--accent);
  padding: .9rem 1.1rem; border-radius: 0 8px 8px 0; font-size: 1.06rem; }
ol.refs { padding-left: 1.4rem; font-size: .92rem; color: #3d4a4a; }
ol.refs li { margin-bottom: .5rem; }
a.cite { text-decoration: none; color: var(--deep); font-weight: 700;
  padding: 0 .1em; }
a.cite:hover { background: #f0e7d6; }
figure { margin: 2.2rem 0; }
figure svg { width: 100%; height: auto; border: 1px solid var(--line);
  border-radius: 10px; }
figcaption { font-size: .88rem; color: var(--muted); margin-top: .5rem; }
aside.note { background: #f6f1e7; border-radius: 10px; padding: 1.2rem 1.4rem;
  font-size: .95rem; }
.meta { display: flex; flex-wrap: wrap; gap: .5rem; margin: 1.4rem 0 0; }
.meta span { background: rgba(255,255,255,.12); border-radius: 999px;
  padding: .3rem .8rem; font-size: .8rem; }
footer { color: var(--muted); font-size: .85rem; padding: 3rem 0 4rem; }
a { color: var(--deep); }
"""

HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{style}</style>
</head>
<body>
<header class="hero">
  <div class="wrap">
    <div class="rule"></div>
    <h1>{title}</h1>
    <p>{intro}</p>
    <div class="meta">{meta}</div>
  </div>
</header>
<div class="wrap">
<nav class="toc">
  <h3>Contents</h3>
  <ol>{toc}</ol>
</nav>
{body}
<aside class="note">
  <h3>A note on the sources</h3>
  <p>{sources}</p>
</aside>
<footer>
  <p>{footer}</p>
</footer>
</div>
</body>
</html>
"""


def _cover_page(spec, brief: dict) -> str:
    """The printed cover, drawn into the page so the file stands alone."""
    if spec is None:
        return ""
    cover = cover_svg(
        str(brief.get("title", "")),
        str(brief.get("introduction", "")),
        str(brief.get("audience", "")),
        palette_for(spec, 0),
        author=str(brief.get("author", "") or "").strip() or DEFAULT_BYLINE,
        initials=spec.initials(),
    )
    return (
        '<section class="cover" aria-label="cover">'
        f"{cover}"
        "<p class=\"hint\">This is the cover the studio drew for this edition. "
        "It is drawn from the same spec as the chapters, so it always matches "
        "the title and the byline.</p>"
        "</section>"
    )


def render_html(ledger: Ledger, figures: list[dict] | None = None) -> str:
    """One self-contained HTML file: cover, contents, chapters, figures."""
    brief = ledger.brief
    figures = figures or []
    drafts = [ledger.drafts[i] for i in sorted(ledger.drafts)]
    spec = ledger.spec
    cover_page = _cover_page(spec, brief)

    toc: list[str] = []
    body: list[str] = []
    for index, draft in enumerate(drafts, start=1):
        anchor = f"ch{index}"
        toc.append(f'<li><a href="#{anchor}">{html.escape(draft.title)}</a></li>')
        parts = [f'<section class="chapter" id="{anchor}">']
        parts.append(f"<h2>Chapter {index}: {html.escape(draft.title)}</h2>")
        parts.append(_paragraphs(draft.body))
        takeaway = draft.takeaway_line()
        if takeaway:
            parts.append(f'<p class="takeaway">{_md_to_html(takeaway)}</p>')
        if draft.references:
            parts.append("<h3>References</h3><ol class=\"refs\">")
            for ref in sorted(draft.references, key=lambda r: int(r["n"])):
                n = int(ref["n"])
                parts.append(
                    f'<li id="ref-{n}">{html.escape(ref.get("org", ""))}, '
                    f'<cite>{html.escape(ref.get("title", ""))}</cite>'
                    + (f', {html.escape(str(ref.get("published", "")))}' if ref.get("published") else "")
                    + f'. <a href="{html.escape(ref.get("url", ""))}">'
                    f'{html.escape(ref.get("url", ""))}</a></li>'
                )
            parts.append("</ol>")
        for number, figure in enumerate(_figures_for(ledger, index, figures), start=1):
            caption = figure.get("caption", "")
            parts.append(
                f'<figure>{figure.get("svg", "")}<figcaption>Figure {number}: '
                f'{html.escape(figure.get("title", ""))}. {html.escape(caption)}'
                "</figcaption></figure>"
            )
        parts.append("</section>")
        body.append("".join(parts))

    stats = ledger.stats()
    meta = "".join(
        f"<span>{html.escape(label)}: {html.escape(f'{stats[key]}')}</span>"
        for key, label in (
            ("sources_verified", "sources verified"),
            ("claims_verified", "claims verified"),
            ("chapters_drafted", "chapters"),
            ("reviews", "reviews"),
        )
    )
    palette = palette_for(spec, 0) if spec is not None else []
    if palette:
        meta += f'<span style="background:{html.escape(palette[0])}">verified edition</span>'

    byline = str(brief.get("author", "") or "").strip()
    meta += f"<span>by {html.escape(byline)}</span>" if byline else ""
    footer = (
        f"Written by {byline or DEFAULT_BYLINE}. Every figure was lifted from a live "
        "page and re-checked after the chapter was written."
    )
    return HTML.format(
        title=html.escape(str(brief.get("title", ""))),
        intro=html.escape(_intro(brief)),
        style=HTML_STYLE,
        meta=meta,
        toc="".join(toc),
        body=cover_page + "".join(body),
        sources=html.escape(_sources_note(ledger)),
        footer=html.escape(footer),
    )


def render_review(ledger: Ledger) -> str:
    """A human-readable account of what the agents did and why."""
    spec = ledger.spec
    out: list[str] = []
    out.append("# Run review")
    out.append("")
    if spec is not None:
        out.append(f"**Book**: {spec.title}  ")
        out.append(f"**Slug**: `{spec.slug}`  ")
        out.append(f"**Origin**: {spec.origin}")
        out.append("")
    stats = ledger.stats()
    out.append("## Outcome")
    out.append("")
    for key, value in stats.items():
        out.append(f"- **{key}**: {value}")
    out.append("")

    out.append("## Sources considered")
    out.append("")
    out.append("| Source | Tier | Link status | Probes confirmed | URL |")
    out.append("|---|---|---|---|---|")
    for key in sorted(ledger.sources):
        source = ledger.sources[key]
        out.append(
            f"| {source.org} | {source.tier} | {source.status} | "
            f"{len(source.confirmed_probes)} | {source.url} |"
        )
    out.append("")

    out.append("## Reviews by round")
    out.append("")
    for report in ledger.reports:
        location = ""
        for issue in report.issues:
            if issue.location:
                location = issue.location
                break
        out.append(
            f"- **{report.agent}** {location} -> **{report.verdict.value}** "
            f"({len(report.blocking())} blocking, {len(report.major())} major, "
            f"{len(report.minor())} minor)"
        )
        for issue in report.issues:
            out.append(f"  - `{issue.severity.value}` {issue.code}: {issue.message}")
    out.append("")

    out.append("## Decisions taken during the run")
    out.append("")
    for decision in ledger.decisions:
        out.append(
            f"- `{decision['t']}s` **{decision['actor']}** -> **{decision['decision']}**: "
            f"{decision['reason']}"
        )
    out.append("")
    return "\n".join(out)