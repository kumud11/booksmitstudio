"""Do the screenshots actually contain a page?

I cannot look at these, so this reads them instead: it decodes each PNG with
nothing but zlib, undoes the scanline filters, and reports the things that
distinguish a real screenshot from a blank page or a half-painted one.

  dimensions      the window we asked for
  colours         a blank page has a handful; a rendered page has thousands
  ink             how much of the frame is not the background colour
  bands           how many horizontal bands carry ink, i.e. is content stacked
                  down the page or stuck in one place
"""

from __future__ import annotations

import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

SHOTS = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")


def read_chunks(data: bytes):
    pos, width, height, depth, colour, idat = 8, 0, 0, 0, 0, bytearray()
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + length
    return width, height, depth, colour, bytes(idat)


def paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)


def analyse(path: Path) -> dict:
    raw = read_chunks(path.read_bytes())[0:2]
    width, height = raw
    _, _, depth, colour, idat = read_chunks(path.read_bytes())
    if depth != 8:
        return {"size": (width, height), "skipped": f"bit depth {depth}"}
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    stride = width * channels
    data = zlib.decompress(idat)

    previous = bytearray(stride)
    colours = Counter()
    ink = 0
    sampled = 0
    palette_seen = Counter()
    bands = 0
    band_ink = 0
    step = max(1, height // 700)          # sample rows, keep it quick
    offset = 0
    background = None

    for y in range(height):
        filter_type = data[offset]
        line = bytearray(data[offset + 1:offset + 1 + stride])
        offset += 1 + stride
        if filter_type == 1:
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif filter_type == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = previous[i]
                upleft = previous[i - channels] if i >= channels else 0
                line[i] = (line[i] + paeth(left, up, upleft)) & 0xFF

        if y % step == 0:
            row_ink = 0
            for x in range(0, width, 3):
                at = x * channels
                pixel = bytes(line[at:at + 3]) if channels >= 3 else bytes(line[at:at + 1])
                colours[pixel] += 1
                sampled += 1
                if background is None:
                    background = pixel
                if pixel != background:
                    ink += 1
                    row_ink += 1
                label = PALETTE.get(tuple(pixel))
                if label:
                    palette_seen[label] += 1
            if row_ink:
                band_ink += 1
                if band_ink > 2:
                    bands += 1
                    band_ink = 0
        previous = line

    return {
        "size": (width, height),
        "colours": len(colours),
        "ink": ink / sampled if sampled else 0,
        "bands": bands,
        "top": colours.most_common(1)[0] if colours else (),
        "palette": dict(palette_seen),
    }


# The colours the book's own charts are drawn in. A frame that is supposed to
# show a figure has to contain them; prose alone will not.
PALETTE = {(15, 61, 62): "deep", (232, 176, 75): "accent", (18, 112, 122): "mid",
           (200, 85, 61): "warm"}


def palette_hits(counts: Counter) -> dict:
    found = {}
    for pixel, hits in counts.items():
        label = PALETTE.get(tuple(pixel))
        if label:
            found[label] = found.get(label, 0) + hits
    return found


def main() -> int:
    print(f"{'shot':28} {'size':>12} {'colours':>8} {'ink':>7} {'bands':>6}  palette")
    problems = []
    for path in sorted(SHOTS.glob("*.png")):
        info = analyse(path)
        if "skipped" in info:
            print(f"{path.name:28} {str(info['size']):>12}   {info['skipped']}")
            continue
        width, height = info["size"]
        ink = info["ink"]
        palette = ", ".join(f"{label}:{hits}" for label, hits
                            in sorted(info["palette"].items()))
        print(f"{path.name:28} {f'{width}x{height}':>12} {info['colours']:>8} "
              f"{ink * 100:>6.1f}% {info['bands']:>6}  {palette}")
        if info["colours"] < 40:
            problems.append(f"{path.name}: only {info['colours']} colours - looks blank")
        if ink < 0.01:
            problems.append(f"{path.name}: {ink * 100:.1f}% ink - looks empty")
        if info["bands"] < 3:
            problems.append(f"{path.name}: content in {info['bands']} band(s) only")
        if height < 900:
            problems.append(f"{path.name}: only {height}px tall")
    print()
    for line in problems:
        print("  !", line)
    print("no problems" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())