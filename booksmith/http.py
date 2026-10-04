"""Zero-dependency helpers for fetching and reading public web sources.

Everything here uses the Python standard library on purpose: the whole system
must run with `python run.py` on a clean checkout, with no `pip install`.
"""

from __future__ import annotations

import concurrent.futures
import gzip
import html
import re
import ssl
import time
import urllib.error
import urllib.request
import zlib

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Some official publishers sit behind a WAF that answers 403 to unknown clients
# while serving the page normally to a browser. Those links are still good
# citations for a human reader, so the verifier reports them separately instead
# of calling them broken.
BOT_PROTECTED_HOSTS = ("npci.org.in", "moneycontrol.com")

TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
WS_RE = re.compile(r"[ \t\r\f\v]+")
NL_RE = re.compile(r"\n\s*\n\s*\n+")


class FetchResult:
    __slots__ = ("url", "status", "final_url", "content_type", "text", "error", "raw")

    def __init__(self, url, status, final_url, content_type, text, error="", raw=""):
        self.url = url
        self.status = status
        self.final_url = final_url
        self.content_type = content_type
        self.text = text
        self.error = error
        self.raw = raw

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def bot_blocked(self) -> bool:
        return self.status in (401, 403, 429) and any(
            h in self.url for h in BOT_PROTECTED_HOSTS
        )

    @property
    def live(self) -> bool:
        """Reachable by this client, whether or not a WAF answered."""
        return self.ok or self.bot_blocked

    def summary(self) -> str:
        if self.ok:
            return f"HTTP {self.status} ({self.content_type or 'unknown'})"
        if self.bot_blocked:
            return f"HTTP {self.status} bot-protected but reachable in a browser"
        return f"HTTP {self.status} {self.error}".strip()


def strip_html(raw: str) -> str:
    """Turn a page into readable text, keeping paragraph breaks."""
    txt = SCRIPT_RE.sub(" ", raw)
    txt = re.sub(r"<(br|/p|/div|/li|/tr|/h[1-6])[^>]*>", "\n", txt, flags=re.I)
    txt = TAG_RE.sub(" ", txt)
    txt = html.unescape(txt)
    # A few publishers escape their entities before sending them, so one pass
    # leaves "&#39;" behind as literal characters. A second pass clears those -
    # and, on a page that escaped its own tags as well, turns them back into tags,
    # which then have to come out again rather than into the book's prose.
    txt = html.unescape(txt)
    txt = TAG_RE.sub(" ", txt)
    txt = WS_RE.sub(" ", txt)
    txt = "\n".join(line.strip() for line in txt.split("\n"))
    return NL_RE.sub("\n\n", txt).strip()


def _decompress_pdf_stream(data: bytes) -> bytes:
    if data[:2] == b"\x78\x9c" or data[:1] == b"\x78":
        try:
            return zlib.decompress(data)
        except zlib.error:
            try:
                return zlib.decompressobj().decompress(data)
            except zlib.error:
                return b""
    if data[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(data)
        except OSError:
            return b""
    return data


_PDF_ESCAPES = {
    b"\\n": b"\n", b"\\r": b"\n", b"\\t": b" ", b"\\b": b"", b"\\f": b"",
    b"\\(": b"(", b"\\)": b")", b"\\\\": b"\\",
}


def extract_pdf_text(raw: bytes) -> str:
    """Best-effort text extraction for text-based PDFs, stdlib only.

    Good enough to prove that a quoted phrase really appears in an official
    circular, which is all the fact-checker needs.
    """
    chunks: list[bytes] = []
    for match in re.finditer(rb"stream\r?\n", raw):
        start = match.end()
        end = raw.find(b"endstream", start)
        if end == -1:
            continue
        inflated = _decompress_pdf_stream(raw[start:end])
        if inflated:
            chunks.append(inflated)
    if not chunks:
        chunks = [raw]

    out: list[str] = []
    for chunk in chunks:
        for token in re.finditer(rb"\((?:\\.|[^()\\])*\)|<[0-9A-Fa-f\s]+>", chunk):
            blob = token.group(0)
            if blob.startswith(b"<"):
                hexdigits = re.sub(rb"[^0-9A-Fa-f]", b"", blob)
                if len(hexdigits) % 2:
                    hexdigits += b"0"
                try:
                    raw_bytes = bytes.fromhex(hexdigits.decode("ascii"))
                except ValueError:
                    continue
                if len(raw_bytes) >= 2:
                    try:
                        out.append(raw_bytes.decode("utf-16-be", "ignore"))
                    except Exception:
                        out.append(raw_bytes.decode("latin-1", "ignore"))
                continue
            body = blob[1:-1]
            for esc, rep in _PDF_ESCAPES.items():
                body = body.replace(esc, rep)
            body = re.sub(rb"\\([0-7]{1,3})", lambda m: bytes([int(m.group(1), 8) & 0xFF]), body)
            out.append(body.decode("latin-1", "ignore"))
        out.append("\n")
    return NL_RE.sub("\n\n", "".join(out)).strip()


def fetch(url: str, timeout: int = 30, max_bytes: int = 6_000_000) -> FetchResult:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read(max_bytes)
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "pdf" in ctype or raw[:5] == b"%PDF-":
                body = raw
                text = extract_pdf_text(raw)
            else:
                body = raw.decode("utf-8", "ignore")
                text = strip_html(body)
            return FetchResult(url, resp.status, resp.geturl(), ctype, text, raw=body)
    except urllib.error.HTTPError as exc:
        return FetchResult(url, exc.code, url, "", "", f"HTTPError {exc.code}")
    except Exception as exc:  # noqa: BLE001 - report, never crash the run
        return FetchResult(url, 0, url, "", "", f"{type(exc).__name__}: {exc}")


def parallel_fetch(urls: list[str], timeout: int = 30, workers: int = 8):
    """Fetch many URLs concurrently. Returns url -> FetchResult (input order kept)."""
    results: dict[str, FetchResult] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, u, timeout): u for u in urls}
        for future in concurrent.futures.as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception as exc:  # noqa: BLE001
                results[url] = FetchResult(url, 0, url, "", "", f"{type(exc).__name__}: {exc}")
    return results


def find_evidence(text: str, pattern: str, window: int = 260):
    """Locate `pattern` in page text.

    Returns ``(snippet, start, matched_text)`` where ``snippet`` is a readable
    window of surrounding context, ``start`` is the match offset, and
    ``matched_text`` is the whole match - which is what the Researcher re-parses
    to pull out a probe's named capture groups.

    Matching is case-insensitive and dot-matches-newline, because official pages
    break their own sentences and tables across many newlines. A probe should not
    fail merely because a publisher's HTML wrapped a line.

    Returns None when the pattern is absent, which is how the Researcher detects
    a source that no longer supports the claim attached to it, and how the
    Fact-checker catches a citation that has drifted away from its source.
    """
    match = re.search(pattern, text, re.I | re.S)
    if not match:
        return None
    start = max(0, match.start() - window)
    end = min(len(text), match.end() + window)
    snippet = WS_RE.sub(" ", text[start:end].replace("\n", " ").strip())
    return snippet, match.start(), match.group(0)


def wait_a_moment(seconds: float) -> None:
    time.sleep(seconds)