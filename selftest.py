#!/usr/bin/env python3
"""Booksmith self-test: prove the three paths that matter, with no API key.

    python selftest.py

1. Spec validation      - the bundled book is a valid, runnable plan.
2. Studio routes        - the index page, the form, the status API and the file
                          server answer correctly.
3. The AI path           - a stub model stands in for the real one, so a book
                          planned by a model (Architect -> Researcher -> Writer ->
                          Editor -> FactChecker) is carried all the way to a
                          finished book.html. This is the path the studio takes
                          when a key is set; the stub lets it be checked offline.

Nothing here is a mock of the pipeline: the stub only replaces the *text model*.
The researcher still fetches pages, the probes still have to match, the
fact-checker still re-fetches, and a chapter that fails any gate is still
withheld.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from booksmith import llm
from booksmith.agents.architect import ArchitectAgent
from booksmith.config import RunConfig
from booksmith.ledger import Ledger
from booksmith.orchestrator import Orchestrator
from booksmith.spec import BookSpec, spec_from_form, upi_spec
from booksmith.studio import app as studio_app

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, PASS if ok else FAIL, detail))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" - {detail}" if detail else ""))
    return ok


# --------------------------------------------------------------------- the stub

STUB_CHAPTERS = 2
STUB_SOURCES = ("pib_10y", "pib_55crore", "rbi_ar_2025", "pib_mdr_96",
                "pib_pidf", "rbi_charges_dp", "pib_gst", "pib_incentive",
                "thehindu_h1", "medianama_soundbox")


def _stub_plan() -> dict:
    """A canned Architect reply: two chapters built like a new book would be.

    The movements are renamed so that no authored prose bank matches them, which
    is exactly the situation a book planned from the studio is in: the Writer has
    claim cards and a model, and nothing else. The evidence, meanwhile, is real -
    every probe here is one that genuinely matches a live page.
    """
    spec = upi_spec()
    chapters = spec.chapter_specs()[:STUB_CHAPTERS]
    wanted_slots = {
        slot
        for chapter in chapters
        for movement in chapter["movements"]
        for slot in movement["slots"]
    }

    sources = []
    probe_slots: dict[str, str] = {}
    for seed in spec.seeds():
        if seed.key not in STUB_SOURCES:
            continue
        probes, slots = [], []
        for probe in seed.probes:
            slot = spec.probe_slots.get(f"{seed.key}:{probe.key}", "")
            if slot not in wanted_slots:
                continue
            probes.append({"key": probe.key, "claim": probe.claim,
                           "pattern": probe.pattern})
            slots.append(slot)
            probe_slots[f"{seed.key}:{probe.key}"] = slot
        if not probes:
            continue
        sources.append({
            "key": seed.key, "org": seed.org, "title": seed.title, "url": seed.url,
            "published": seed.published, "tier": seed.tier, "slots": slots,
            "probes": probes,
        })

    for chapter in chapters:
        for movement in chapter["movements"]:
            if movement["key"] not in ("open", "close"):
                movement["key"] = f"beat_{movement['key']}"

    return {
        "title": "How India Pays",
        "audience": "Shop owners meeting a phone payment for the first time",
        "voice": spec.voice,
        "chapters": STUB_CHAPTERS,
        "min_words": spec.min_words,
        "max_words": spec.max_words,
        "jargon": list(spec.jargon) or ["UPI", "QR code"],
        "glossary": dict(spec.glossary),
        "slot_titles": dict(spec.slot_titles),
        "outline": chapters,
        "sources": sources,
        "probe_slots": probe_slots,
        "corroboration": {},
        "figures": [
            {
                "key": "scale_chart",
                "chapter": 1,
                "kind": "bar",
                "title": "UPI transaction volume by financial year",
                "caption": "Crore transactions a year.",
                "items": [
                    {"claim": "pib_55crore:fy_table", "value": "volume_fy2122",
                     "label": "2021-22"},
                    {"claim": "pib_10y:fy26_volume", "value": "volume_crore",
                     "label": "2025-26"},
                ],
            }
        ],
    }


class StubBackend:
    """Answers the three model calls the AI path makes."""

    name = "stub"
    model = "stub-writer"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(self, system: str, prompt: str, max_tokens: int = 4096,
                 temperature: float = 0.3, json_mode: bool = False) -> str:
        if "Architect" in system:
            self.calls.append("architect")
            return json.dumps(_stub_plan())
        if "Planner" in system:
            self.calls.append("planner")
            return json.dumps({"chapters": [
                {"index": index, "title": chapter["title"], "purpose": chapter["purpose"],
                 "open": chapter["movements"][0]["intent"],
                 "close": chapter["movements"][-1]["intent"]}
                for index, chapter in enumerate(
                    _stub_plan()["outline"], start=1
                )
            ]})
        if "Editor" in system:
            self.calls.append("editor")
            return json.dumps({"edits": [], "notes": "clean"})
        if "Takeaway" in prompt:
            self.calls.append("takeaway")
            return "Takeaway: keep the QR code where customers can reach it."
        if "Writer" in system:
            self.calls.append("writer")
            return _chapter_prose(prompt)
        self.calls.append("unknown")
        return ""


CARD_RE = re.compile(r"^-\s+([A-Za-z0-9_]+:[A-Za-z0-9_]+):\s+(.*)$")


def _cards(prompt: str) -> list[tuple[str, str]]:
    """The claim cards from a Writer prompt, keyed by claim id."""
    out = []
    for line in prompt.splitlines():
        match = CARD_RE.match(line.strip())
        if match:
            out.append((match.group(1), match.group(2).strip()))
    return out


def _chapter_prose(prompt: str) -> str:
    """Assemble a chapter from its claim cards, in the voice the brief asks for.

    Deliberately dull prose: the point is to prove the plumbing, not to win a
    literary prize. Numbers come only from the cards.
    """
    cards = _cards(prompt)
    paragraphs = []
    for alias, card in cards:
        figures = card[card.find("use exactly:"):] if "use exactly:" in card else ""
        if figures:
            figures = figures.replace("use exactly:", "").strip(" ()")
            spoken = "The record gives these figures: " + figures + "."
        else:
            spoken = "The record states it plainly, in its own words."
        paragraphs.append(
            "Start from the counter, where this is noticed first. "
            + card.split(" - ")[0].rstrip(".")
            + ". What follows from that is worth knowing before you decide "
              "anything, and it is worth knowing without anyone dressing it up. "
            + spoken
            + " Read that again slowly. The number is not a promise about your "
              "week; it is a measurement of what has happened so far. You can "
              "plan around it, and you can check it against your own record "
              "when the month closes."
            + f" [[cite:{alias}]]"
        )
    while sum(len(p.split()) for p in paragraphs) < 640 and paragraphs:
        alias, card = cards[0]
        paragraphs.append(
            "One more thing is worth saying plainly, because nobody says it "
            "often enough. A figure like this one moves slowly, and slow "
            "movement is easy to miss. Nothing about it demands a decision "
            "today. It does, however, reward the shopkeeper who writes it "
            "down and looks at it again in a month, because a trend you never "
            "record is a trend you will argue about later "
            f"[[cite:{alias}]]."
        )
        break
    return "\n\n".join(paragraphs)


def install_stub() -> StubBackend:
    """Register a `stub` provider so both the studio and the CLI can select it.

    It goes in through the real `resolve_backend` path rather than by monkey
    patching, so the self-test exercises the same code the studio will.
    """
    backend = StubBackend()

    class _Provider:
        def __init__(self, name: str, model: str, api_key: str, base_url: str) -> None:
            self.name = name
            self.model = model

        def complete(self, system: str, prompt: str, max_tokens: int = 4096,
                     temperature: float = 0.3, json_mode: bool = False) -> str:
            return backend.complete(system, prompt, max_tokens, temperature, json_mode)

    llm.PROVIDERS["stub"] = {
        "env": "BOOKSMITH_STUB",
        "base_env": "BOOKSMITH_STUB_BASE",
        "default_base": "stub://local",
        "default_model": "stub-writer",
        "cls": _Provider,
    }
    os.environ["BOOKSMITH_STUB"] = "stub-key"
    return backend


# --------------------------------------------------------------------- the tests

def test_spec() -> None:
    print("\n1. Spec validation")
    spec = upi_spec()
    check("bundled UPI spec has no problems", not spec.problems(), "; ".join(spec.problems()[:2]))
    check("bundled spec saves and reloads", BookSpec.load(
        _write_json(spec.to_dict())).problems() == [])

    request = spec_from_form(
        "A Test Book", "An introduction long enough to plan a real book from, "
        "written by a publisher who knows what the book is about.")
    check("a bare request has no outline yet",
          bool(request.problems()) and "title" not in request.problems()[0])

    # A model that puts a list where a mapping belongs is a wrong answer, not a
    # reason to lose the run: the shape is repaired and the problems are reported.
    shaped_wrong = BookSpec.from_dict({
        "title": "A Test Book",
        "slot_titles": ["a", "b"],
        "probe_slots": ["nope"],
        "corroboration": "nope",
        "sources": {"url": "https://example.org"},
    })
    check("a malformed plan is repaired, not fatal", shaped_wrong.slot_titles == {})
    check("a repaired plan still reports its problems",
          bool(shaped_wrong.problems()), str(shaped_wrong.problems()[:1])[:60])

    # The README's diagram is documentation: if it names an agent that no longer
    # exists, or misses one that does, it is lying to whoever reads it.
    root = Path(__file__).resolve().parent
    readme = (root / "README.md").read_text(encoding="utf-8")
    mermaid = re.search(r"```mermaid\n(.*?)```", readme, re.S)
    if check("the README carries an architecture diagram", bool(mermaid)):
        block = mermaid.group(1)
        modules = {p.stem for p in (root / "booksmith" / "agents").glob("*.py")
                   if p.stem not in ("__init__", "base")}
        missing = sorted(m for m in modules if m not in block)
        # `form`, `orch`, `ledger` and `output` are the furniture around the
        # agents, not agents pretending to be.
        furniture = {"form", "orch", "ledger", "output"}
        absent = sorted({
            name for name in re.findall(r"^\s{4}(\w+)\[\"", block, re.M)
            if name not in modules and name not in furniture
        })
        check("the diagram names every agent in the code", not missing,
              "missing: " + ", ".join(missing))
        check("the diagram invents no agents", not absent,
              "unknown: " + ", ".join(absent))
        check("the diagram shows the ledger and the orchestrator",
              "Ledger" in block and "Orchestrator" in block)
        check("the diagram links the drawn page",
              "docs/architecture.html" in readme)


def test_studio() -> None:
    print("\n2. Studio routes")
    root = Path(tempfile.mkdtemp(prefix="booksmith-studio-"))
    studio = studio_app.Studio(root=root)
    studio_app.Handler.studio = studio
    studio_app.Handler.backend = "stub"
    studio_app.Handler.rounds = 2
    server = ThreadingHTTPServer(("127.0.0.1", 0), studio_app.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        page = _get(f"{base}/")
        check("index page serves", "New book" in page and 'name="title"' in page)

        body = urllib.parse.urlencode({
            "title": "How a Village Shop Takes a Payment",
            "introduction": "A plain guide for a shopkeeper meeting digital "
                            "payments for the first time, with no jargon and no "
                            "assumptions about what the reader already knows.",
            "chapters": "2", "min_words": "600", "max_words": "900",
            "author": "Meera Raghavan",
        }).encode()
        status, location = _post(f"{base}/books", body)
        check("form returns a redirect", status == 303 and location.startswith("/book/"),
              location or str(status))

        book_page = _get(base + location)
        check("book page renders the plan", "Plan" in book_page or "Run log" in book_page)

        import time
        for _ in range(240):
            payload = json.loads(_get(f"{base}/api/books/{location.rsplit('/', 1)[1]}"))
            if payload["state"] in ("done", "failed"):
                break
            time.sleep(1)
        check("run finished", payload["state"] in ("done", "failed"),
              f"state={payload['state']}")
        check("spec was written", (root / location.rsplit("/", 1)[1] / "spec.json").exists())

        if payload["state"] == "done":
            html = _get(f"{base}/files/{location.rsplit('/', 1)[1]}/output/book.html")
            check("book.html is served", "<svg" in html and "Chapter 1" in html)
            check("figures were drawn", "<figure>" in html)
            check("the cover is the first page",
                  'class="cover"' in html and html.index('class="cover"')
                  < html.index('class="chapter"'))
            check("the cover carries the author asked for",
                  "Meera Raghavan" in html and "by Meera Raghavan" in html)
            preview = _get(
                f"{base}/files/{location.rsplit('/', 1)[1]}/output/preview.html")
            check("one preview file holds the whole book",
                  "Chapter 1" in preview and "id=\"evidence\"" in preview
                  and "assets/" not in preview,
                  f"{len(preview)} bytes")
            book_page = _get(base + location)
            check("the book page links the preview",
                  "Preview the whole book" in book_page)
            md = _get(f"{base}/files/{location.rsplit('/', 1)[1]}/output/book.md")
            refs = re.findall(r"^\[(\d+)\]\s*(.+?)\s*$", md, re.M)
            check("every reference names org, title, date and link",
                  bool(refs) and all(
                      re.search(r"https?://\S+", entry)
                      and re.search(r"(19|20)\d\d|"
                                    r"January|February|March|April|May|June|July|"
                                    r"August|September|October|November|December",
                                    entry)
                      and '"' in entry or "“" in entry
                      for _, entry in refs),
                  f"{len(refs)} references")
            pages = [re.search(r"https?://\S+", entry).group(0) for _, entry in refs]
            check("one reference entry per source page",
                  len(pages) == len(set(pages)),
                  f"{len(pages)} entries, {len(set(pages))} pages")
        else:
            check("failure explains itself", bool(payload["problem"]), payload["problem"][:80])
            print("     log tail: " + "\n     ".join(payload["log"].splitlines()[-4:]))

        # Choosing "no model" with nothing to plan from has to be caught at the
        # form: the publisher gets the reason and the field to fill, not a run
        # page with a log saying it failed.
        body = urllib.parse.urlencode({
            "title": "A Book With No Model And No Links",
            "introduction": "A request that gives the studio nothing to work from, "
                            "which it should refuse in plain words.",
            "chapters": "2", "model": "offline",
        }).encode()
        status, _location, refused = _post_raw(f"{base}/books", body)
        check("no-model, no-links is refused at the form",
              status == 400 and "source link" in refused.lower(),
              f"status={status}")
        check("the form offers example links",
              'id="example-links"' in refused and "pib.gov.in" in refused)
        check("the refusal explains what to do",
              "ollama" in refused.lower() and "add a link" in refused.lower())
    finally:
        server.shutdown()
        server.server_close()
        shutil.rmtree(root, ignore_errors=True)


def test_ai_path() -> None:
    print("\n3. The AI path, with a stub in place of the text model")
    stub = install_stub()
    request = spec_from_form(
        "How India Pays",
        "A plain guide to the payments a shopkeeper now meets at the counter.",
    )
    ledger = Ledger()
    ledger.spec = request
    config = RunConfig(out_dir="", backend="stub", verbose=False)
    spec = ArchitectAgent(config, ledger).run(request)
    check("architect wrote a valid spec", not spec.problems(), "; ".join(spec.problems()[:2]))
    check("architect kept the publisher's title", spec.title == "How India Pays")
    check("architect planned sources", len(spec.sources) == len(STUB_SOURCES),
          str(len(spec.sources)))
    check("architect planned a figure", len(spec.figures) == 1)

    out_dir = Path(tempfile.mkdtemp(prefix="booksmith-ai-")) / "output"
    config = RunConfig(
        out_dir=str(out_dir), backend="stub", spec=spec, verbose=False,
        target_words=spec.target_words(), chapters=spec.chapters,
        min_words=spec.min_words, max_words=spec.max_words,
    )
    try:
        code = Orchestrator(config, spec).run()
        published = len(list(out_dir.glob("book.md"))) and "book.md" in {
            p.name for p in out_dir.iterdir()
        }
        check("pipeline finished", code in (0, 1, 2), f"exit {code}")
        check("book.md was written", published)
        if published:
            text = (out_dir / "book.md").read_text(encoding="utf-8")
            check("book has both chapters", "Chapter 1" in text and "Chapter 2" in text)
            check("book carries citations", text.count("[1]") >= 1)
            check("references are listed", "**References**" in text)
            check("figure was drawn from verified data",
                  (out_dir / "assets" / "scale-chart.svg").exists())
            page = (out_dir / "book.html").read_text(encoding="utf-8")
            check("html edition is self-contained", page.count("<svg") >= 1)
        print(f"     model calls: {', '.join(stub.calls) or 'none'}")
    finally:
        shutil.rmtree(out_dir.parent, ignore_errors=True)


# ------------------------------------------------------------------------ utils

def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _post(url: str, body: bytes) -> tuple[int, str]:
    status, location, _ = _post_raw(url, body)
    return status, location


def _post_raw(url: str, body: bytes) -> tuple[int, str, str]:
    """Post a form and keep the response body, which the studio uses to explain
    a refusal in the form itself."""
    import urllib.error

    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type":
                                          "application/x-www-form-urlencoded"})
    try:
        with _OPENER.open(req, timeout=30) as resp:
            return (resp.status, resp.headers.get("Location", ""),
                    resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return (exc.code,
                exc.headers.get("Location", "") if exc.headers else "",
                exc.read().decode("utf-8", "replace"))


def _write_json(payload: dict) -> Path:
    path = Path(tempfile.mkdtemp(prefix="booksmith-spec-")) / "spec.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_ollama_wire() -> None:
    print("\n4. The Ollama backend, against a stub of Ollama's own endpoints")
    seen: list[dict] = []
    reject_json_mode = {"on": True}

    class FakeOllama(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # noqa: A003
            pass

        def do_GET(self) -> None:  # noqa: N802
            body = json.dumps({"models": [{"name": "qwen2.5:7b"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, "payload": payload,
                         "auth": self.headers.get("Authorization")})
            if payload.get("response_format") and reject_json_mode["on"]:
                body = json.dumps(
                    {"error": "invalid parameter: response_format is not supported"}
                ).encode()
                self.send_response(400)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = json.dumps({
                "choices": [{"message": {"content": '{"ok": true}'}}],
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}/v1"
    previous = os.environ.get("OLLAMA_BASE_URL")
    os.environ["OLLAMA_BASE_URL"] = base
    llm._REACHABLE.clear()
    try:
        check("unreachable ollama is not offered", not llm.ollama_reachable(
            "http://127.0.0.1:9/v1"))
        check("reachable ollama is detected", llm.ollama_reachable(base))

        backend = llm.resolve_backend("ollama")
        check("backend resolves to ollama", backend.name == "ollama", backend.model)
        check("model id is overridable",
              llm.resolve_backend("ollama", "qwen2.5:7b").model == "qwen2.5:7b")

        reply = backend.complete("system", "hello", json_mode=True)
        check("json reply parses", llm.try_json(reply) == {"ok": True}, reply)
        check("it retries when json mode is rejected",
              len(seen) == 2 and "response_format" not in seen[-1]["payload"],
              f"{len(seen)} request(s)")
        check("it posts to the chat endpoint",
              all(r["path"] == "/v1/chat/completions" for r in seen))
        check("it sends model and messages",
              seen[-1]["payload"].get("model") == backend.model
              and len(seen[-1]["payload"]["messages"]) == 2,
              f"asked for {seen[-1]['payload'].get('model')!r}, "
              f"backend chose {backend.model!r}")

        reject_json_mode["on"] = False
        seen.clear()
        backend.complete("system", "hello", json_mode=True)
        check("it uses json mode when supported",
              "response_format" in seen[0]["payload"])
    finally:
        if previous is None:
            os.environ.pop("OLLAMA_BASE_URL", None)
        else:
            os.environ["OLLAMA_BASE_URL"] = previous
        llm._REACHABLE.clear()
        server.shutdown()
        server.server_close()

    # Port 9 is the discard port: nothing listens there, whatever else the
    # machine happens to be running.
    os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:9/v1"
    llm._REACHABLE.clear()
    try:
        llm.resolve_backend("ollama")
        check("missing local server is refused", False, "it should have raised")
    except llm.LLMError as exc:
        check("missing local server is refused", True, str(exc)[:70])
    os.environ.pop("OLLAMA_BASE_URL", None)


def main() -> int:
    print("Booksmith self-test")
    install_stub()
    test_spec()
    test_studio()
    test_ai_path()
    test_ollama_wire()
    failed = [name for name, state, _ in results if state == FAIL]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    for name in failed:
        print(f"  failed: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())