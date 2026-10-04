"""Read, measure and cut a PNG, with nothing but zlib and struct.

    from pngslice import load, save, row_ink, crop

Headless Edge will only photograph what fits in one window, and asking it to
scroll to `#evidence` gives back an empty frame. So the book is captured whole,
once, at full height - and then cut here, using the ink profile to decide where
the content actually is. No image library, no browser, no guessing.

Rows are stored as bytes after undoing each scanline filter, which is also how
`row_ink` measures them: the point of the module is that a screenshot can be
*checked* as well as cut.
"""

from __future__ import annotations

import struct
import zlib
from collections import Counter
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)


def _chunks(data: bytes):
    pos = 8
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            yield kind, body
        elif kind == b"IDAT":
            yield kind, body
        elif kind == b"IEND":
            return
        pos += 12 + length


class Image:
    """One decoded image: rows of bytes, plus where its ink is."""

    def __init__(self, width: int, height: int, channels: int, rows: list[bytes]):
        self.width = width
        self.height = height
        self.channels = channels
        self.rows = rows

    # ------------------------------------------------------------- reading
    @classmethod
    def load(cls, path: Path) -> "Image":
        data = Path(path).read_bytes()
        width = height = depth = colour = 0
        idat = bytearray()
        for kind, body in _chunks(data):
            if kind == b"IHDR":
                width, height, depth, colour = struct.unpack(">IIBB", body[:10])
            elif kind == b"IDAT":
                idat += body
        if depth != 8:
            raise SystemExit(f"{path}: only 8-bit PNGs are supported (got {depth})")
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
        stride = width * channels
        raw = zlib.decompress(bytes(idat))
        rows: list[bytes] = []
        previous = bytearray(stride)
        offset = 0
        for _ in range(height):
            kind = raw[offset]
            line = bytearray(raw[offset + 1:offset + 1 + stride])
            offset += 1 + stride
            if kind == 1:
                for i in range(channels, stride):
                    line[i] = (line[i] + line[i - channels]) & 0xFF
            elif kind == 2:
                for i in range(stride):
                    line[i] = (line[i] + previous[i]) & 0xFF
            elif kind == 3:
                for i in range(stride):
                    left = line[i - channels] if i >= channels else 0
                    line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
            elif kind == 4:
                for i in range(stride):
                    left = line[i - channels] if i >= channels else 0
                    upleft = previous[i - channels] if i >= channels else 0
                    line[i] = (line[i] + _paeth(left, previous[i], upleft)) & 0xFF
            rows.append(bytes(line))
            previous = line
        return cls(width, height, channels, rows)

    # ------------------------------------------------------------ measuring
    def background(self) -> bytes:
        """The most common colour in the frame: the page behind everything."""
        colours = Counter()
        for y in range(0, self.height, max(1, self.height // 400)):
            row = self.rows[y]
            for x in range(0, self.width, 4):
                at = x * self.channels
                colours[row[at:at + min(3, self.channels)]] += 1
        return colours.most_common(1)[0][0] if colours else b"\xff\xff\xff"

    def row_ink(self, background: bytes | None = None) -> list[int]:
        """How many pixels in each row differ from the background."""
        background = background or self.background()
        width, channels = self.width, self.channels
        span = min(3, channels)
        counts = []
        for row in self.rows:
            hits = 0
            for x in range(0, width, 3):
                at = x * channels
                if row[at:at + span] != background:
                    hits += 1
            counts.append(hits)
        return counts

    def bands(self, minimum: int = 2, gap: int = 40) -> list[tuple[int, int]]:
        """Runs of rows that carry ink, as (first_row, last_row)."""
        ink = self.row_ink()
        spans: list[tuple[int, int]] = []
        start = None
        quiet = 0
        for y, hits in enumerate(ink):
            if hits >= minimum:
                if start is None:
                    start = y
                quiet = 0
            elif start is not None:
                quiet += 1
                if quiet >= gap:
                    spans.append((start, y - quiet))
                    start = None
        if start is not None:
            spans.append((start, len(ink) - 1))
        return spans

    def row_palette(self, wanted: set[tuple[int, int, int]]) -> list[int]:
        """Per-row counts of a few exact colours.

        The charts are drawn from a fixed palette, so a frame that is supposed
        to show one contains those colours and a page of prose does not. This is
        how a figure gets found in a page that is eleven thousand pixels tall.
        """
        width, channels = self.width, self.channels
        span = min(3, channels)
        counts = []
        for row in self.rows:
            hits = 0
            for x in range(0, width, 2):
                at = x * channels
                if tuple(row[at:at + span]) in wanted:
                    hits += 1
            counts.append(hits)
        return counts

    # -------------------------------------------------------------- cutting
    def crop(self, top: int, bottom: int) -> "Image":
        top = max(0, min(top, self.height - 1))
        bottom = max(top + 1, min(bottom, self.height))
        return Image(self.width, bottom - top, self.channels, self.rows[top:bottom])

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        colour = {1: 0, 2: 4, 3: 2, 4: 6}[self.channels]
        header = struct.pack(">IIBBBBB", self.width, len(self.rows), 8, colour,
                             0, 0, 0)
        raw = bytearray()
        for row in self.rows:
            raw.append(0)                    # filter: none, so it is easy to read back
            raw += row
        path.write_bytes(
            PNG_SIGNATURE
            + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + _chunk(b"IEND", b"")
        )
        return path


def _chunk(kind: bytes, body: bytes) -> bytes:
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))


def crop(image: Image, top: int, bottom: int) -> Image:
    return image.crop(top, bottom)
