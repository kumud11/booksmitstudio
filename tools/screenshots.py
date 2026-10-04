#!/usr/bin/env python3
"""Capture the screenshots the submission asks for, with nothing but Edge.

    python tools/screenshots.py            # writes docs/screenshots/*.png

Seven shots, all of real output rather than mock-ups:

    01-studio-form.png          the studio index page and its form
    02-run-in-progress.png      a run caught working: the live log
    03-book-page.png            the finished run: plan, stats, files, log
    04-book-cover.png           the book itself: cover, byline, contents
    05-chapter-figure.png       a chapter with its chart inlined
    06-evidence.png             the evidence section - reviews and claims
    07-cli-run.png              a real `run.py` console session

The studio is started for the shots that need it, on a port the OS picks and a
throwaway books directory, and shut down afterwards. It is started with
`--backend offline` so the run is reproducible: no model, no API key, just the
pages and the pipeline. Edge is driven headless with a temporary profile so a
running browser is never disturbed. A shot that comes out blank is deleted
rather than shipped: a loading spinner in a submission screenshot is worse than
no screenshot.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
BOOK = ROOT / "docs" / "sample-book" / "preview.html"

EDGE_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
]

MIN_PNG_BYTES = 12_000        # anything smaller is a blank page
SETTLE_MS = 9_000            # headless budget for pages with nothing to wait for

BOOK_PAGE_HEIGHT = 11_000     # tall enough to hold the whole book in one window

# The book is captured whole, then cut. Headless Edge will not scroll: ask it
# for `#evidence` and it hands back an empty frame, because the fragment is at
# the very bottom of the document and the window never moves. So one tall frame
# is taken and sliced by its own ink profile, which is also how each slice is
# checked for emptiness before it is written.
#
#   name                    how the slice is chosen
BOOK_SLICES = [
    ("04-book-cover.png", "top", 1_600),
    ("05-chapter-figure.png", "figure", 1_900),
    ("06-evidence.png", "tail", 1_900),
]

# The colours `booksmith.visuals` draws its charts in, from PALETTES[0].
CHART_COLOURS = {(15, 61, 62), (18, 112, 122), (232, 176, 75), (200, 85, 61),
                 (91, 125, 91)}


def find_browser() -> Path:
    for path in EDGE_CANDIDATES:
        if path.exists():
            return path
    for name in ("msedge", "chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise SystemExit(
        "no Chromium browser found. Install Edge or Chrome, or pass "
        "--browser <path to the executable>."
    )


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get(url: str, timeout: float = 20.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", "ignore")


def wait_for(url: str, seconds: float = 40.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            get(url, timeout=3)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


def start_run(base: str) -> str:
    """Post the studio form the way a publisher would, and return the slug."""
    sys.path.insert(0, str(ROOT))
    from booksmith.studio.pages import EXAMPLE_LINKS

    body = urllib.parse.urlencode({
        "title": "What UPI Cost a Small Shop",
        "introduction": "A short guide for a shopkeeper weighing up digital "
                       "payments: what a UPI payment costs, what it pays, and which "
                       "numbers come from the banks and the regulator.",
        "chapters": "2", "min_words": "600", "max_words": "900",
        "urls": EXAMPLE_LINKS,
    }).encode()
    request = urllib.request.Request(
        base + "/books", data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            location = response.headers.get("Location") or response.url
    except urllib.error.HTTPError as error:
        location = error.headers.get("Location", "") if error.headers else ""
    return location.rstrip("/").rsplit("/", 1)[-1]


def wait_for_finish(base: str, slug: str, seconds: float = 300.0) -> str:
    """Poll the status API the studio's own page polls."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            payload = json.loads(get(f"{base}/api/books/{slug}", timeout=10))
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            time.sleep(2)
            continue
        state = str(payload.get("state", ""))
        if state in ("done", "failed"):
            return state
        time.sleep(2)
    return "still-running"


def shoot(browser: Path, url: str, out: Path, height: int,
          profile: Path, settle: bool = False, no_js: bool = False,
          floor: int = MIN_PNG_BYTES) -> bool:
    """One headless screenshot. Returns True if the file looks like a page.

    `settle` asks Edge to spend a virtual-time budget before shooting. It is off
    by default because the studio's book page keeps polling while a run is in
    flight, and a page that never goes idle never reaches its budget - the shot
    would hang rather than fail.

    `no_js` is the other half of that problem: the log on a running book page is
    rendered by the server and only *refreshed* by JavaScript, so capturing with
    scripting off shows the page exactly as it stands at that moment, and the
    poll cannot hold the browser open.
    """
    command = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--run-all-compositor-stages-before-draw",
        f"--user-data-dir={profile}",
    ]
    if settle:
        command.append(f"--virtual-time-budget={SETTLE_MS}")
    if no_js:
        command.append("--blink-settings=scriptEnabled=false")
    command += [f"--window-size=1440,{height}", f"--screenshot={out}", url]

    def attempt(extra_args: bool = False) -> subprocess.CompletedProcess:
        # Edge often writes the file and then lingers; the file is the evidence.
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=75)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(command, 0, "", "lingered after writing")

    result = attempt()
    if not out.exists():
        # Older builds only understand --headless.
        command = [c if c != "--headless=new" else "--headless" for c in command]
        result = attempt()

    if not out.exists():
        print(f"    no file written: {str(result.stderr)[:160]}")
        return False
    size = out.stat().st_size
    if size < floor:
        print(f"    only {size:,} bytes - looks blank, discarding")
        out.unlink()
        return False
    return True


def slice_book(whole: Path, out: Path, where: str, height: int) -> Path:
    """Cut one shot out of the captured book page, and check it is not empty."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pngslice import Image

    page = Image.load(whole)
    bands = page.bands()
    if not bands:
        raise ValueError("the captured book page has no content at all")

    if where == "top":
        top = 0
    elif where == "tail":
        top = max(0, bands[-1][0] - 120)
    else:
        # A figure, located by its own colours. The charts are drawn from a fixed
        # palette, so the rows carrying those colours *are* the chart - and the
        # cover is skipped, since it is one enormous block of the same teal.
        rows = page.row_palette(CHART_COLOURS)
        ranked = sorted(range(1400, page.height), key=lambda y: rows[y], reverse=True)
        best = ranked[0] if ranked else 0
        while best > 1400 and sum(rows[best - 40:best + 40]) == 0:
            best -= 1
        top = max(0, min(best - height // 3, page.height - height))
    top = min(top, max(0, page.height - height))
    piece = page.crop(top, top + height)
    piece.save(out)

    ink = sum(1 for hits in piece.row_ink() if hits > 2)
    if ink < height // 20:
        raise ValueError(f"the {where} slice is nearly empty ({ink} rows of ink)")
    chart = sum(piece.row_palette(CHART_COLOURS))
    print(f"    rows {top}-{top + height}, {ink} rows of content, "
          f"{chart:,} chart-coloured pixels")
    return out


TERMINAL_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>run</title>
<style>
  body {{ margin:0; background:#0f1417; font:15px/1.62 ui-monospace, Consolas,
    "Cascadia Mono", monospace; color:#d7e0e3; }}
  .win {{ max-width:1040px; margin:0 auto; padding:1.1rem 1.3rem 1.6rem; }}
  .bar {{ display:flex; align-items:center; gap:.5rem; padding-bottom:.9rem;
    border-bottom:1px solid #223038; margin-bottom:1rem; }}
  .dot {{ width:11px; height:11px; border-radius:50%; }}
  .t {{ margin-left:.5rem; color:#8b9aa1; font-size:13px; }}
  pre {{ margin:0; white-space:pre-wrap; word-break:break-word; }}
  .p {{ color:#6ee7a8; }} .c {{ color:#8b9aa1; }} .w {{ color:#f0c674; }}
  .h {{ color:#7fb4ff; font-weight:bold; }} .g {{ color:#6ee7a8; }}
  .r {{ color:#ff8b7a; }}
</style></head><body><div class="win">
<div class="bar"><span class="dot" style="background:#ff5f57"></span>
<span class="dot" style="background:#febc2e"></span>
<span class="dot" style="background:#28c840"></span>
<span class="t">{title}</span></div>
<pre>{body}</pre></div></body></html>
"""


def render_terminal(lines: list[str], title: str, out: Path) -> None:
    """Turn captured console output into a terminal card worth screenshotting."""
    import html as html_mod

    painted = []
    for line in lines:
        text = html_mod.escape(line)
        if line.startswith(">>>"):
            painted.append(f'<span class="p">{text}</span>')
        elif re.match(r"^(==|--|ch\d|Researcher|Writer|Editor|FactChecker|Voicekeeper"
                      r"|Architect|Planner)", line):
            painted.append(f'<span class="h">{text}</span>')
        elif "wrote" in line or "PASS" in line or "checks passed" in line:
            painted.append(f'<span class="g">{text}</span>')
        elif line.startswith(("  ", "\t")):
            painted.append(f'<span class="c">{text}</span>')
        elif any(w in line for w in ("warn", "failed", "WARN", "error")):
            painted.append(f'<span class="r">{text}</span>')
        else:
            painted.append(f'<span class="w">{text}</span>')
    out.write_text(
        TERMINAL_PAGE.format(title=html_mod.escape(title), body="\n".join(painted)),
        encoding="utf-8",
    )


def cli_run_lines(work: Path) -> list[str]:
    """A real offline run, captured exactly as the console shows it."""
    command = [
        sys.executable, "run.py", "--book", "upi",
        "--out", str(work / "out"), "--backend", "offline",
    ]
    environment = {"PYTHONIOENCODING": "utf-8"}
    environment.update({k: v for k, v in os.environ.items() if k.isupper()})
    finished = subprocess.run(command, cwd=ROOT, capture_output=True,
                              text=True, timeout=900, env=environment)
    output = (finished.stdout or "") + (finished.stderr or "")
    lines = [line for line in output.splitlines() if line.strip()]
    return [
        "$ python run.py --book upi --out out --backend offline",
        "# no API key, no model: the bundled book, built from its own evidence",
        "",
        *lines[:46],
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", default=None, help="path to Edge or Chrome")
    parser.add_argument("--keep-going", action="store_true",
                        help="carry on when a shot fails to capture")
    args = parser.parse_args()

    browser = Path(args.browser) if args.browser else find_browser()
    SHOTS.mkdir(parents=True, exist_ok=True)
    for stale in SHOTS.glob("*.png"):
        stale.unlink()

    print(f"browser: {browser}")
    taken, failed = [], []

    with tempfile.TemporaryDirectory(prefix="booksmith-shots-") as tmp:
        profile = Path(tmp) / "profile"
        work = Path(tmp) / "work"
        work.mkdir(parents=True, exist_ok=True)

        # The studio, on a port nothing else is using.
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        print(f"starting the studio on {base}")
        studio = subprocess.Popen(
            [sys.executable, "studio.py", "--port", str(port), "--no-browser",
             "--backend", "offline", "--books", str(work / "books")],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            if not wait_for(base + "/"):
                raise SystemExit("the studio never answered on its own port")

            target = SHOTS / "01-studio-form.png"
            print(f"  01-studio-form.png <- {base}/")
            if shoot(browser, base + "/", target, 1500, profile):
                taken.append(target.name)
            else:
                failed.append(target.name)

            # A real run, photographed while it works and again when it is done.
            # Nothing is staged: the form is posted exactly as a publisher would.
            slug = start_run(base)
            if not slug:
                raise SystemExit("the studio refused the run; nothing to photograph")
            print(f"  started: {slug}")

            time.sleep(11.0)
            target = SHOTS / "02-run-in-progress.png"
            print(f"  02-run-in-progress.png <- {base}/book/{slug}")
            if shoot(browser, f"{base}/book/{slug}", target, 2100, profile):
                taken.append(target.name)
            else:
                failed.append(target.name)

            state = wait_for_finish(base, slug, seconds=900)
            print(f"  run finished: {state}")
            if state != "done":
                print(f"    the run reported {state!r}; the book page shot will "
                      "show whatever the studio says")
            time.sleep(1.5)
            target = SHOTS / "03-book-page.png"
            print(f"  03-book-page.png <- {base}/book/{slug}")
            if shoot(browser, f"{base}/book/{slug}", target, 2400, profile):
                taken.append(target.name)
            else:
                failed.append(target.name)
        finally:
            studio.terminate()
            try:
                studio.wait(timeout=10)
            except subprocess.TimeoutExpired:
                studio.kill()

        # The finished book, read straight off disk - no server needed. Captured
        # whole, then cut into the shots a reader would want to see.
        whole = work / "book-full.png"
        print(f"  capturing the whole book at {BOOK_PAGE_HEIGHT}px")
        if shoot(browser, BOOK.as_uri(), whole, BOOK_PAGE_HEIGHT, profile,
                 settle=True, floor=400_000):
            for name, where, height in BOOK_SLICES:
                target = SHOTS / name
                print(f"  {name} <- the {where} of the book page")
                try:
                    slice_book(whole, target, where, height)
                    taken.append(name)
                except ValueError as exc:
                    print(f"    {exc}")
                    failed.append(name)
        else:
            failed.extend(name for name, _, _ in BOOK_SLICES)

        # The console, doing the work.
        print("  running the book from the command line")
        try:
            render_terminal(cli_run_lines(work), "run.py - Booksmith", work / "cli.html")
            target = SHOTS / "07-cli-run.png"
            print("  07-cli-run.png <- the console card")
            if shoot(browser, (work / "cli.html").as_uri(), target, 1500, profile):
                taken.append(target.name)
            else:
                failed.append(target.name)
        except subprocess.TimeoutExpired:
            print("    the command-line run took too long; skipping that shot")
            failed.append("07-cli-run.png")

    print()
    for name in sorted(SHOTS.glob("*.png")):
        print(f"  {name.name:28} {name.stat().st_size:>9,} bytes")
    print(f"\n{len(taken)} captured, {len(failed)} failed: {failed or 'none'}")
    if failed and not args.keep_going:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
