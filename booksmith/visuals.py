"""Figures, drawn from verified evidence only.

Every number on a chart is read out of a `Claim` the Researcher captured from a
live page with a regex named group. A figure whose claim never verified is not
drawn at all - the chapter gets a caption saying so rather than a plausible-looking
picture of nothing.

The output is plain SVG written by hand, because the whole project runs on the
standard library: no plotting package, no fonts to install, no binary artefacts.
The SVG is written to `assets/` and also inlined into the HTML edition, so the
book is one file you can email.
"""

from __future__ import annotations

import re
from pathlib import Path

INK = "#1d2b2b"
MUTED = "#6b7a7a"
PAPER = "#fdfbf7"
GRID = "#e3ddd2"

PALETTES = [
    ["#0f3d3e", "#12707a", "#e8b04b", "#c8553d", "#5b7d5b"],
    ["#2b2d42", "#5c80bc", "#ef8354", "#8f5d8f", "#4a4e69"],
    ["#1b3a2f", "#4c956c", "#d8a31a", "#bc4b51", "#6d8b74"],
    ["#3a2e39", "#7d5a50", "#c19a6b", "#9c6644", "#4f5d75"],
]

NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
SUFFIX_RE = re.compile(r"(crore|lakh|billion|million|per cent|%)", re.I)


class Point:
    """One plotted value, with the text exactly as the source printed it."""

    __slots__ = ("label", "text", "number", "suffix", "claim_id")

    def __init__(self, label: str, text: str, claim_id: str = ""):
        self.label = label
        self.text = text
        self.claim_id = claim_id
        match = NUMBER_RE.search(text or "")
        self.number = float(match.group(0).replace(",", "")) if match else 0.0
        suffix = SUFFIX_RE.search(text or "")
        self.suffix = suffix.group(1).lower() if suffix else ""


def palette_for(spec, index: int = 0) -> list[str]:
    chosen = [c for c in (spec.cover_palette or []) if str(c).startswith("#")]
    if len(chosen) >= 3:
        return chosen
    return PALETTES[index % len(PALETTES)]


# --------------------------------------------------------------------- helpers

def esc(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def wrap(text: str, width: int) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def _open(width: int, height: int, title: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}" '
        f'font-family="Georgia, \'Times New Roman\', serif">',
        f'<rect width="{width}" height="{height}" fill="{PAPER}"/>',
    ]


def _footer(out: list[str], width: int, height: int, caption: str) -> list[str]:
    if not caption:
        return out
    for i, line in enumerate(wrap(caption, 78)[:2]):
        out.append(
            f'<text x="{width / 2:.0f}" y="{height - 26 + i * 16}" fill="{MUTED}" '
            f'font-size="12" text-anchor="middle">{esc(line)}</text>'
        )
    return out


# ---------------------------------------------------------------------- charts

def bar_chart(title: str, points: list[Point], caption: str = "",
              colors: list[str] | None = None, width: int = 720) -> str:
    height = 380
    left, right, top, bottom = 70, 30, 70, 96
    plot_w = width - left - right
    plot_h = height - top - bottom
    colors = colors or PALETTES[0]
    peak = max((abs(p.number) for p in points), default=0.0) or 1.0

    out = _open(width, height, title)
    out.append(
        f'<text x="{left}" y="34" fill="{INK}" font-size="20" font-weight="bold">'
        f"{esc(title)}</text>"
    )
    for i in range(5):
        value = peak * i / 4
        y = top + plot_h - plot_h * i / 4
        out.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{left - 10}" y="{y + 4:.1f}" fill="{MUTED}" font-size="11" '
            f'text-anchor="end">{esc(_short(value))}</text>'
        )
    count = max(1, len(points))
    slot = plot_w / count
    bar_w = min(120.0, slot * 0.55)
    for i, point in enumerate(points):
        cx = left + slot * (i + 0.5)
        bar_h = plot_h * (abs(point.number) / peak)
        colour = colors[i % len(colors)]
        out.append(
            f'<rect x="{cx - bar_w / 2:.1f}" y="{top + plot_h - bar_h:.1f}" '
            f'width="{bar_w:.1f}" height="{bar_h:.1f}" rx="6" fill="{colour}" '
            f'opacity="0.92"/>'
        )
        out.append(
            f'<text x="{cx:.1f}" y="{top + plot_h - bar_h - 10:.1f}" fill="{INK}" '
            f'font-size="15" text-anchor="middle" font-weight="bold">'
            f"{esc(point.text)}</text>"
        )
        for j, line in enumerate(wrap(point.label, 18)[:2]):
            out.append(
                f'<text x="{cx:.1f}" y="{top + plot_h + 24 + j * 16}" fill="{MUTED}" '
                f'font-size="12" text-anchor="middle">{esc(line)}</text>'
            )
    out.append(
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" '
        f'y2="{top + plot_h}" stroke="{INK}" stroke-width="2"/>'
    )
    out = _footer(out, width, height, caption)
    out.append("</svg>")
    return "\n".join(out)


def line_chart(title: str, points: list[Point], caption: str = "",
               colors: list[str] | None = None, width: int = 720) -> str:
    height = 380
    left, right, top, bottom = 70, 30, 70, 84
    plot_w = width - left - right
    plot_h = height - top - bottom
    colour = (colors or PALETTES[0])[0]
    values = [abs(p.number) for p in points] or [0.0]
    peak, floor = max(values), min(values)
    if peak - floor < 1e-9:
        peak, floor = peak + 1, max(0.0, floor - 1)

    out = _open(width, height, title)
    out.append(
        f'<text x="{left}" y="34" fill="{INK}" font-size="20" font-weight="bold">'
        f"{esc(title)}</text>"
    )
    for i in range(5):
        value = floor + (peak - floor) * i / 4
        y = top + plot_h - plot_h * i / 4
        out.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{left - 10}" y="{y + 4:.1f}" fill="{MUTED}" font-size="11" '
            f'text-anchor="end">{esc(_short(value))}</text>'
        )
    step = plot_w / max(1, len(points) - 1) if len(points) > 1 else plot_w
    coords = []
    for i, point in enumerate(points):
        x = left + (step * i if len(points) > 1 else plot_w / 2)
        y = top + plot_h - plot_h * (abs(point.number) - floor) / (peak - floor)
        coords.append((x, y))
    out.append(
        '<polyline fill="none" '
        f'stroke="{colour}" stroke-width="3" stroke-linejoin="round" '
        f'points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in coords)}"/>'
    )
    for (x, y), point in zip(coords, points):
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{colour}"/>')
        out.append(
            f'<text x="{x:.1f}" y="{y - 14:.1f}" fill="{INK}" font-size="13" '
            f'text-anchor="middle" font-weight="bold">{esc(point.text)}</text>'
        )
        out.append(
            f'<text x="{x:.1f}" y="{top + plot_h + 24:.1f}" fill="{MUTED}" '
            f'font-size="12" text-anchor="middle">{esc(point.label)}</text>'
        )
    out.append(
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" '
        f'y2="{top + plot_h}" stroke="{INK}" stroke-width="2"/>'
    )
    out = _footer(out, width, height, caption)
    out.append("</svg>")
    return "\n".join(out)


def donut_chart(title: str, points: list[Point], caption: str = "",
                colors: list[str] | None = None, width: int = 720) -> str:
    height = 380
    colors = colors or PALETTES[0]
    total = sum(abs(p.number) for p in points) or 1.0
    cx, cy, r, thickness = 250, height / 2 + 6, 108, 44

    out = _open(width, height, title)
    out.append(
        f'<text x="36" y="34" fill="{INK}" font-size="20" font-weight="bold">'
        f"{esc(title)}</text>"
    )
    angle = -90.0
    for i, point in enumerate(points):
        sweep = 360.0 * (abs(point.number) / total)
        out.append(
            f'<circle cx="{cx}" cy="{cy:.0f}" r="{r}" fill="none" '
            f'stroke="{colors[i % len(colors)]}" stroke-width="{thickness}" '
            f'stroke-dasharray="{sweep * 3.14159 / 180 * r:.1f} '
            f'{2 * 3.14159 * r - sweep * 3.14159 / 180 * r:.1f}" '
            f'transform="rotate({angle:.1f} {cx} {cy:.0f})"/>'
        )
        angle += sweep
    out.append(
        f'<text x="{cx}" y="{cy:.0f}" fill="{INK}" font-size="15" '
        f'text-anchor="middle">{esc(_short(total))}</text>'
    )
    for i, point in enumerate(points):
        y = 150 + i * 54
        out.append(
            f'<rect x="430" y="{y - 14}" width="16" height="16" rx="3" '
            f'fill="{colors[i % len(colors)]}"/>'
        )
        out.append(
            f'<text x="456" y="{y}" fill="{INK}" font-size="15" '
            f'font-weight="bold">{esc(point.text)}</text>'
        )
        for j, line in enumerate(wrap(point.label, 40)[:2]):
            out.append(
                f'<text x="456" y="{y + 18 + j * 16}" fill="{MUTED}" font-size="12">'
                f"{esc(line)}</text>"
            )
    out = _footer(out, width, height, caption)
    out.append("</svg>")
    return "\n".join(out)


def stat_tiles(title: str, points: list[Point], caption: str = "",
               colors: list[str] | None = None, width: int = 720) -> str:
    height = 300
    colors = colors or PALETTES[0]
    count = max(1, len(points))
    gap = 24
    tile_w = (width - 48 - gap * (count - 1)) / count

    out = _open(width, height, title)
    out.append(
        f'<text x="24" y="34" fill="{INK}" font-size="20" font-weight="bold">'
        f"{esc(title)}</text>"
    )
    for i, point in enumerate(points):
        x = 24 + i * (tile_w + gap)
        out.append(
            f'<rect x="{x:.1f}" y="56" width="{tile_w:.1f}" height="150" rx="14" '
            f'fill="{colors[i % len(colors)]}" opacity="0.10"/>'
        )
        out.append(
            f'<rect x="{x:.1f}" y="56" width="{tile_w:.1f}" height="6" rx="3" '
            f'fill="{colors[i % len(colors)]}"/>'
        )
        for j, line in enumerate(wrap(point.text, 16)[:2]):
            out.append(
                f'<text x="{x + 20:.1f}" y="{110 + j * 30}" fill="{INK}" font-size="26" '
                f'font-weight="bold">{esc(line)}</text>'
            )
        for j, line in enumerate(wrap(point.label, 26)[:3]):
            out.append(
                f'<text x="{x + 20:.1f}" y="{166 + j * 18}" fill="{MUTED}" '
                f'font-size="12">{esc(line)}</text>'
            )
    out = _footer(out, width, height, caption)
    out.append("</svg>")
    return "\n".join(out)


CHART_BUILDERS = {
    "bar": bar_chart,
    "line": line_chart,
    "donut": donut_chart,
    "stat": stat_tiles,
}


# ----------------------------------------------------------------------- cover

def author_seal(initials: str, accent: str, cx: int, cy: int, r: int = 74) -> list[str]:
    """A printed-emblem mark for the author: ring, initials, two rules.

    A seal is the honest stand-in for a photograph here - there is no author
    portrait to show, and inventing a face would be worse than a mark.
    """
    return [
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{accent}" '
        f'stroke-width="3"/>',
        f'<circle cx="{cx}" cy="{cy}" r="{r - 11}" fill="#ffffff" '
        f'fill-opacity="0.07" stroke="#ffffff" stroke-opacity="0.35" '
        f'stroke-width="1"/>',
        f'<text x="{cx}" y="{cy + 15}" fill="#ffffff" font-size="42" '
        f'font-weight="bold" text-anchor="middle" letter-spacing="2">'
        f"{esc(initials or 'B')}</text>",
        f'<line x1="{cx - 26}" y1="{cy + 34}" x2="{cx + 26}" y2="{cy + 34}" '
        f'stroke="{accent}" stroke-width="2"/>',
    ]


def cover_svg(title: str, introduction: str, audience: str = "",
              colors: list[str] | None = None, width: int = 900,
              height: int = 1180, author: str = "", initials: str = "") -> str:
    colors = colors or PALETTES[0]
    deep, mid, accent = colors[0], colors[1], colors[2]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}" '
        f'font-family="Georgia, \'Times New Roman\', serif">',
        f'<defs><linearGradient id="coverbg" x1="0" y1="0" x2="0.4" y2="1">'
        f'<stop offset="0%" stop-color="{deep}"/>'
        f'<stop offset="100%" stop-color="{mid}"/></linearGradient></defs>',
        f'<rect width="{width}" height="{height}" fill="url(#coverbg)"/>',
    ]
    # A quiet grid of rules, so the cover reads as printed matter.
    for i in range(1, 9):
        y = 120 + i * 96
        out.append(
            f'<line x1="72" y1="{y}" x2="{width - 72}" y2="{y}" stroke="#ffffff" '
            f'stroke-opacity="0.07" stroke-width="1"/>'
        )
    out.append(
        f'<circle cx="{width - 130}" cy="190" r="150" fill="{accent}" '
        f'opacity="0.16"/>'
    )
    out.append(
        f'<circle cx="150" cy="{height - 180}" r="200" fill="#ffffff" opacity="0.05"/>'
    )

    out.append(
        f'<rect x="72" y="150" width="86" height="8" rx="4" fill="{accent}"/>'
    )
    y = 250
    for i, line in enumerate(wrap(title, 26)[:6]):
        size = 54 if i == 0 else 44
        out.append(
            f'<text x="72" y="{y}" fill="#ffffff" font-size="{size}" '
            f'font-weight="bold">{esc(line)}</text>'
        )
        y += size + 18

    y += 18
    for line in wrap(introduction, 62)[:6]:
        out.append(
            f'<text x="72" y="{y}" fill="#ffffff" fill-opacity="0.78" '
            f'font-size="21">{esc(line)}</text>'
        )
        y += 32

    if audience or author:
        base = height - 150
        out.append(
            f'<line x1="72" y1="{base}" x2="{width - 72}" '
            f'y2="{base}" stroke="#ffffff" stroke-opacity="0.25"/>'
        )
        y = base + 40
        if author:
            out.extend(author_seal(initials, accent, 128, y + 24, 46))
            for i, line in enumerate(wrap(f"By {author}", 46)[:3]):
                out.append(
                    f'<text x="196" y="{y + 18 + i * 30}" fill="#ffffff" '
                    f'font-size="21">{esc(line)}</text>'
                )
            y += 3 * 30 + 26
        for line in wrap(f"Written for {audience}", 52)[:2] if audience else []:
            out.append(
                f'<text x="72" y="{y}" fill="#ffffff" fill-opacity="0.72" '
                f'font-size="18" font-style="italic">{esc(line)}</text>'
            )
            y += 28
    out.append(
        f'<text x="72" y="{height - 46}" fill="#ffffff" fill-opacity="0.5" '
        f'font-size="13">Every figure cited. Every source linked.</text>'
    )
    out.append("</svg>")
    return "\n".join(out)


# --------------------------------------------------------------- from the ledger

def points_for(figure: dict, claims: dict) -> tuple[list[Point], list[str]]:
    """Resolve a figure's items against the claims the Researcher verified."""
    points: list[Point] = []
    missing: list[str] = []
    for item in figure.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("claim", "")).strip()
        claim = claims.get(claim_id)
        if claim is None or not getattr(claim, "verified", False):
            missing.append(claim_id or "?")
            continue
        name = str(item.get("value", "")).strip()
        text = claim.values.get(name, "") if name else ""
        if not text and claim.values:
            text = next(iter(claim.values.values()))
        if not text:
            missing.append(claim_id)
            continue
        label = str(item.get("label", "")).strip() or _shorten(claim.text, 44)
        points.append(Point(label, str(text).strip(), claim_id))
    return points, missing


def render_figure(figure: dict, claims: dict, colors: list[str]) -> str | None:
    """SVG for one figure, or None when its evidence did not verify."""
    kind = str(figure.get("kind", "bar")).lower()
    builder = CHART_BUILDERS.get(kind, bar_chart)
    points, missing = points_for(figure, claims)
    if not points:
        return None
    caption = str(figure.get("caption", "")).strip()
    if missing:
        caption = (caption + "  " if caption else "") + (
            "Not plotted: " + ", ".join(missing[:3]) + " (not verified)."
        )
    return builder(str(figure.get("title", "Figure")).strip(), points, caption, colors)


def render_all(spec, claims: dict) -> list[dict]:
    """Every drawable figure in the book, with the svg text attached."""
    out: list[dict] = []
    for index, figure in enumerate(spec.figures or []):
        colors = palette_for(spec, index)
        svg = render_figure(figure, claims, colors)
        out.append({
            "key": str(figure.get("key", f"figure{index + 1}")),
            "chapter": int(figure.get("chapter", 0)),
            "kind": str(figure.get("kind", "bar")),
            "title": str(figure.get("title", "")),
            "caption": str(figure.get("caption", "")),
            "svg": svg or "",
        })
    return out


def write_assets(out_dir: Path, spec, claims: dict) -> list[dict]:
    """Draw the figures and the cover, and write them to `assets/`."""
    assets = out_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    cover = cover_svg(
        spec.title,
        spec.introduction,
        spec.audience,
        palette_for(spec, 0),
        author=spec.byline(),
        initials=spec.initials(),
    )
    (assets / "cover.svg").write_text(cover, encoding="utf-8")

    written: list[dict] = []
    for index, figure in enumerate(render_all(spec, claims)):
        if not figure["svg"]:
            continue
        name = f"{_slug(figure['key']) or f'figure{index + 1}'}.svg"
        (assets / name).write_text(figure["svg"], encoding="utf-8")
        figure["file"] = f"assets/{name}"
        written.append(figure)
    return written


def _shorten(text: str, width: int) -> str:
    text = str(text or "").strip()
    if len(text) <= width:
        return text
    cut = text[:width].rsplit(" ", 1)[0]
    return (cut or text[:width]) + "..."


def _short(value: float) -> str:
    if abs(value) >= 100:
        return f"{value:,.0f}"
    if abs(value) >= 1:
        return f"{value:,.1f}".rstrip("0").rstrip(".")
    return f"{value:g}"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:48]