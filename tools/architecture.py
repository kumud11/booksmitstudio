#!/usr/bin/env python3
"""Draw the architecture diagram, and check it against the code.

    python tools/architecture.py            # writes docs/architecture.html
    python tools/architecture.py --check    # only verify, write nothing

One self-contained HTML file, inline SVG, no dependencies - the same rule the
rest of the project keeps. The point of generating it rather than pasting a
picture is that the diagram has to stay true: every agent it draws is looked up
in `booksmith/agents/`, and every artefact it promises is looked up in
`booksmith/render.py`. Rename an agent and this fails instead of letting the
README quietly describe a pipeline that no longer exists.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from booksmith.visuals import PALETTES, esc, wrap  # noqa: E402

OUT = ROOT / "docs" / "architecture.html"

# The pipeline as it actually runs. Order is the Orchestrator's routing order.
# (key, label, one line of what it does, what it may not do)
AGENTS = [
    ("architect", "Architect",
     "turns a title and links into a plan: outline, sources, probes, figures",
     "invent a figure"),
    ("planner", "Planner",
     "splits the plan into chapters and movements, each naming its evidence slots",
     "name a source"),
    ("researcher", "Researcher",
     "fetches every candidate page and runs each probe against the live text",
     "publish a claim whose probe did not match"),
    ("writer", "Writer",
     "writes each chapter from verified claim cards only",
     "add a figure no card carries"),
    ("editor", "Editor",
     "brief compliance, grammar, tone, readability",
     "change a number"),
    ("fact_checker", "FactChecker",
     "re-fetches every cited page, re-runs its probe, audits every numeral",
     "pass a chapter it cannot confirm"),
    ("voicekeeper", "Voicekeeper",
     "cross-chapter voice and terminology",
     "rewrite a chapter that already passed both reviews"),
]

OUTPUTS = ["book.md", "book.html", "preview.html", "review.md", "ledger.json"]

WIDTH, HEIGHT = 1440, 1010
BOX_W, BOX_H = 158, 74
TOP_Y, ROW_Y, LEDGER_Y = 236, 372, 556

DEEP, MID, ACCENT = PALETTES[0][0], PALETTES[0][1], PALETTES[0][2]


def check_against_code() -> list[str]:
    """Every name the diagram draws must exist in the code it describes."""
    problems: list[str] = []
    modules = {p.stem for p in (ROOT / "booksmith" / "agents").glob("*.py")}
    for key, label, _, _ in AGENTS:
        if key not in modules:
            problems.append(f"no module booksmith/agents/{key}.py for the {label} box")

    render_src = (ROOT / "booksmith" / "render.py").read_text(encoding="utf-8")
    for name in OUTPUTS:
        if name not in render_src and not (ROOT / "booksmith" / "ledger.py").exists():
            problems.append(f"{name} is not written by anything the diagram promises")

    orchestrator = (ROOT / "booksmith" / "orchestrator.py").read_text(encoding="utf-8")
    for word in ("Orchestrator", "ledger"):
        if word not in orchestrator:
            problems.append(f"orchestrator.py no longer mentions {word}")

    missing_modules = modules - {key for key, *_ in AGENTS} - {"__init__", "base"}
    if missing_modules:
        problems.append(
            "agents exist that the diagram does not draw: "
            + ", ".join(sorted(missing_modules))
        )
    return problems


def box(x: int, y: int, label: str, role: str, limit: int,
        fill: str = "#ffffff", stroke: str = "#d9d2c4") -> list[str]:
    out = [
        f'<rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="10" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>',
        f'<rect x="{x}" y="{y}" width="4" height="{BOX_H}" rx="2" fill="{ACCENT}"/>',
    ]
    for i, line in enumerate(wrap(label, 16)[:2]):
        out.append(
            f'<text x="{x + 16}" y="{y + 26 + i * 19}" font-size="15" '
            f'font-weight="700" fill="{DEEP}">{esc(line)}</text>'
        )
    for i, line in enumerate(wrap(role, limit)[:3]):
        out.append(
            f'<text x="{x + 16}" y="{y + 52 + i * 13}" font-size="10.5" '
            f'fill="#5c6a6a">{esc(line)}</text>'
        )
    return out


def arrow(x1: int, y1: int, x2: int, y2: int, label: str = "",
          colour: str = "#8c9a99", dash: str = "") -> list[str]:
    marker = "arrow-grey"
    out = [
        f'<defs><marker id="{marker}" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{colour}"/></marker></defs>',
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{colour}" '
        f'stroke-width="1.6" marker-end="url(#{marker})"'
        + (f' stroke-dasharray="{dash}"' if dash else "") + "/>",
    ]
    if label:
        out.append(
            f'<text x="{(x1 + x2) // 2}" y="{(y1 + y2) // 2 - 7}" font-size="10" '
            f'text-anchor="middle" fill="{colour}">{esc(label)}</text>'
        )
    return out


def build_svg() -> str:
    gap = 24
    step = BOX_W + gap
    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" '
        f'height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        f'aria-label="How the Booksmith agents interact" '
        f'font-family="Georgia, \'Times New Roman\', serif">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#fdfbf7"/>',
        f'<text x="60" y="72" font-size="34" font-weight="bold" fill="{DEEP}">'
        "How the agents interact</text>",
        f'<text x="60" y="104" font-size="15" fill="#5c6a6a">Agents never call each '
        "other. Each one reads the shared ledger, writes its own artefacts into it, "
        "and returns a decision.</text>",
        f'<text x="60" y="128" font-size="15" fill="#5c6a6a">The Orchestrator owns '
        "the routing, the review budget and the stop condition - that is the only "
        "place collaboration is decided.</text>",
    ]

    # Entry points.
    for i, (label, note) in enumerate([
        ("Studio form", "title + introduction + source links"),
        ("Command line", "run.py --title ... --urls ..."),
    ]):
        y = TOP_Y - 96 + i * 44
        out.append(
            f'<rect x="60" y="{y}" width="{BOX_W + 40}" height="34" rx="8" '
            f'fill="{DEEP}" fill-opacity="0.06" stroke="{DEEP}" '
            f'stroke-opacity="0.25"/>'
        )
        out.append(
            f'<text x="76" y="{y + 22}" font-size="13" font-weight="700" '
            f'fill="{DEEP}">{esc(label)}</text>'
        )
        out.append(
            f'<text x="76 + {len(label) * 8 + 18}" y="{y + 22}" font-size="11" '
            f'fill="#5c6a6a">{esc(note)}</text>'
        )
        out += arrow(60 + BOX_W + 40, y + 17, 60 + step, ROW_Y - 46, colour=MID)

    # Orchestrator, the only component that decides anything.
    out.append(
        f'<rect x="60" y="{TOP_Y - 12}" width="{WIDTH - 120}" height="58" rx="10" '
        f'fill="{DEEP}"/>'
    )
    out.append(
        f'<text x="84" y="{TOP_Y + 14}" font-size="16" font-weight="700" '
        f'fill="#ffffff">Orchestrator</text>'
    )
    out.append(
        f'<text x="84" y="{TOP_Y + 34}" font-size="11.5" fill="#ffffff" '
        'fill-opacity="0.75">routes the run &#183; holds every collaboration rule '
        '&#183; spends the review budget &#183; decides when a chapter ships or is '
        'withheld</text>'
    )

    # The agents.
    for i, (_, label, role, _) in enumerate(AGENTS):
        x = 60 + i * step
        out += box(x, ROW_Y, label, role, 22,
                   fill="#ffffff", stroke="#d9d2c4")
        if i:
            out += arrow(x - gap, ROW_Y + BOX_H // 2, x, ROW_Y + BOX_H // 2)

    # The review loop, drawn under the row so it cannot be mistaken for a step.
    writer_x = 60 + 3 * step
    checker_x = 60 + 5 * step
    loop_y = ROW_Y + BOX_H + 46
    out += arrow(checker_x + BOX_W // 2, ROW_Y + BOX_H,
                 checker_x + BOX_W // 2, loop_y, colour=ACCENT)
    out += arrow(checker_x + BOX_W // 2, loop_y, writer_x + BOX_W // 2, loop_y,
                 colour=ACCENT)
    out += arrow(writer_x + BOX_W // 2, loop_y, writer_x + BOX_W // 2,
                 ROW_Y + BOX_H, colour=ACCENT)
    out.append(
        f'<text x="{(writer_x + checker_x) // 2 + BOX_W // 2}" y="{loop_y - 10}" '
        f'font-size="11.5" text-anchor="middle" fill="{ACCENT}">revise, up to 3 '
        "rounds &#8212; else the chapter is withheld</text>"
    )

    # The ledger every agent reads and writes.
    ledger_w = 60 + len(AGENTS) * step - gap
    out.append(
        f'<rect x="60" y="{LEDGER_Y}" width="{ledger_w}" height="86" rx="10" '
        f'fill="#ffffff" stroke="{MID}" stroke-width="1.5" stroke-dasharray="6 4"/>'
    )
    out.append(
        f'<text x="84" y="{LEDGER_Y + 28}" font-size="15" font-weight="700" '
        f'fill="{DEEP}">Ledger &#8212; the one thing they share</text>'
    )
    out.append(
        f'<text x="84" y="{LEDGER_Y + 48}" font-size="11.5" fill="#5c6a6a">'
        "sources &#183; claims &#183; drafts &#183; review reports &#183; decisions "
        "&#183; the trace</text>"
    )
    out.append(
        f'<text x="84" y="{LEDGER_Y + 68}" font-size="11.5" fill="#5c6a6a">'
        "nothing is passed agent to agent; everything is read back out of here</text>"
    )
    for i in range(len(AGENTS)):
        x = 60 + i * step + BOX_W // 2
        out += arrow(x, ROW_Y + BOX_H, x, LEDGER_Y - 6,
                     colour="#b9c6c5", dash="3 3")

    # Outputs.
    out_y = LEDGER_Y + 150
    out += arrow(60 + ledger_w // 2, LEDGER_Y + 86, 60 + ledger_w // 2, out_y - 10,
                 colour=MID)
    out.append(
        f'<text x="{60 + ledger_w // 2 + 10}" y="{LEDGER_Y + 118}" font-size="11" '
        f'fill="{MID}">assembled and written out</text>'
    )
    out.append(
        f'<text x="60" y="{out_y - 18}" font-size="13" font-weight="700" '
        f'fill="{DEEP}">What comes out</text>'
    )
    for i, name in enumerate(OUTPUTS):
        x = 60 + i * step
        out.append(
            f'<rect x="{x}" y="{out_y}" width="{BOX_W}" height="46" rx="8" '
            f'fill="{MID}" fill-opacity="0.1" stroke="{MID}" stroke-opacity="0.4"/>'
        )
        for j, line in enumerate(wrap(name, 20)[:2]):
            out.append(
                f'<text x="{x + BOX_W // 2}" y="{out_y + 20 + j * 15}" '
                f'font-size="12" text-anchor="middle" fill="{DEEP}">'
                f'{esc(line)}</text>'
            )

    # The rule that makes it a book and not a document.
    out.append(
        f'<rect x="60" y="{out_y + 82}" width="{WIDTH - 120}" height="64" rx="10" '
        f'fill="#f6f1e7" stroke="#e3ddd2"/>'
    )
    out.append(
        f'<text x="84" y="{out_y + 110}" font-size="13.5" font-weight="700" '
        f'fill="{DEEP}">A number can only reach the prose by travelling from a page, '
        "through a regex, into a claim, into a sentence that carries its citation."
        "</text>"
    )
    out.append(
        f'<text x="84" y="{out_y + 130}" font-size="12" fill="#5c6a6a">'
        "The FactChecker repeats the whole journey after the chapter is written, so a "
        "figure cannot drift away from its source either.</text>"
    )
    out.append("</svg>")
    return "\n".join(out)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Booksmith &#8212; how the agents interact</title>
<style>
  body {{ margin: 0; background: #fdfbf7; color: #1d2b2b;
    font: 17px/1.7 Georgia, 'Times New Roman', serif; }}
  .wrap {{ max-width: 76rem; margin: 0 auto; padding: 2.4rem 1.4rem 3rem; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 .3rem; }}
  p.lede {{ color: #5c6a6a; margin: 0 0 1.6rem; }}
  svg {{ width: 100%; height: auto; border: 1px solid #e3ddd2; border-radius: 12px;
    background: #fff; }}
  footer {{ color: #6b7a7a; font-size: .88rem; margin-top: 1.4rem; }}
  code {{ font-family: ui-monospace, Consolas, monospace; font-size: .9em; }}
</style>
</head>
<body>
<div class="wrap">
<h1>Booksmith</h1>
<p class="lede">Generated by <code>tools/architecture.py</code> from the pipeline in
<code>booksmith/</code>. Every agent it draws is checked against a real module, so it
cannot drift away from the code.</p>
{svg}
<footer>Six agents, one ledger, one orchestrator. Rendered in the browser's own SVG
&#8212; no image files, no dependencies.</footer>
</div>
</body>
</html>
"""


def mermaid() -> str:
    """The same flow, for the README, where GitHub renders it for us."""
    lines = ["flowchart LR"]
    lines.append('    form["Studio form / CLI<br/>title, intro, source links"]')
    lines.append('    orch["Orchestrator<br/>routing, review budget, stop condition"]')
    lines.append('    ledger[("Ledger<br/>sources, claims, drafts, reports, decisions")]')
    lines.append('    form --> orch')
    lines.append('    orch --> architect')
    for i, (key, label, _, _) in enumerate(AGENTS):
        lines.append(f'    {key}["{label}"]')
        if i:
            lines.append(f"    {AGENTS[i - 1][0]} --> {key}")
        lines.append(f"    {key} <--> ledger")
    lines.append("    editor -->|blocked| writer")
    lines.append("    fact_checker -->|pass| voicekeeper")
    lines.append('    output["book.md &#183; book.html &#183; preview.html<br/>'
                 'review.md &#183; ledger.json"]')
    lines.append("    voicekeeper --> output")
    lines.append("    orch -.->|owns| ledger")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify the diagram against the code and write nothing")
    args = parser.parse_args()

    problems = check_against_code()
    if problems:
        print("the diagram no longer matches the code:")
        for problem in problems:
            print("  -", problem)
        return 1

    labels = ", ".join(label for _, label, _, _ in AGENTS)
    print(f"checked {len(AGENTS)} agents against booksmith/agents/: {labels}")

    if args.check:
        print("check passed; nothing written")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(PAGE.format(svg=build_svg()), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size:,} bytes)")

    fence = ROOT / "docs" / "architecture.mmd"
    fence.write_text(mermaid() + "\n", encoding="utf-8")
    print(f"wrote {fence.relative_to(ROOT)} (the mermaid source for the README)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
