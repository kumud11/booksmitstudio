"""The studio server: routes, the shelf, and one background run per book.

Standard library only: `http.server` for the transport, `threading` so a run does
not block the page, and the same `Orchestrator` the command line uses, so what the
studio produces is byte-for-byte what `python run.py` produces.

Books live in `books/<slug>/`:

    spec.json          the plan, written by the Architect and reusable forever
    studio.log         the run transcript
    output/            book.md, book.html, review.md, ledger.json, assets/
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import traceback
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from ..config import RunConfig
from ..llm import LLMError, resolve_backend
from ..orchestrator import Orchestrator
from ..spec import BookSpec, spec_from_form
from ..agents.architect import ArchitectAgent
from . import pages

DEFAULT_PORT = 8765
MAX_FORM_BYTES = 64 * 1024

OUTPUT_FILES = (
    ("preview.html", "the whole book in one file, with its evidence"),
    ("book.html", "the book, figures inlined"),
    ("book.md", "the book, markdown"),
    ("review.md", "what every agent did"),
    ("ledger.json", "every source, claim, issue and decision"),
    ("assets/cover.svg", "cover"),
)


@dataclass
class Run:
    """One book's state on the shelf, and its background run."""

    slug: str
    title: str
    directory: Path
    state: str = "planned"          # planned | running | done | failed
    log: list[str] = field(default_factory=list)
    problem: str = ""
    model_choice: str = "auto"   # auto | offline, chosen on the form
    stats: dict = field(default_factory=dict)
    plan: list = field(default_factory=list)
    exit_code: int | None = None
    thread: threading.Thread | None = None
    flushed: float = 0.0

    def say(self, line: str) -> None:
        for part in str(line).splitlines() or [""]:
            self.log.append(part)
        if len(self.log) > 4000:
            del self.log[:1000]

    def text(self) -> str:
        return "\n".join(self.log)

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "title": self.title,
            "state": self.state,
            "log": self.text(),
            "problem": self.problem,
            "stats": self.stats,
            "plan": self.plan,
            "exit_code": self.exit_code,
        }


class Studio:
    """The shelf: every book on disk, plus the runs in flight."""

    def __init__(self, root: Path | None = None, verbose: bool = False) -> None:
        self.root = Path(root or "books")
        self.root.mkdir(parents=True, exist_ok=True)
        self.runs: dict[str, Run] = {}
        self.verbose = verbose
        self.lock = threading.Lock()

    # ------------------------------------------------------------------ shelf
    def directory(self, slug: str) -> Path:
        return self.root / slug

    def spec_path(self, slug: str) -> Path:
        return self.directory(slug) / "spec.json"

    def log_path(self, slug: str) -> Path:
        return self.directory(slug) / "studio.log"

    def unique_slug(self, title: str) -> str:
        from ..spec import slugify

        base = slugify(title)
        slug, n = base, 2
        while self.spec_path(slug).exists() or slug in self.runs:
            slug = f"{base}-{n}"
            n += 1
        return slug

    def shelf(self) -> list[dict]:
        books: list[dict] = []
        for path in sorted(self.root.glob("*/spec.json")):
            try:
                spec = BookSpec.load(path)
            except Exception:  # noqa: BLE001 - a broken file must not hide the rest
                continue
            run = self.runs.get(spec.slug)
            state = run.state if run else "done"
            books.append({
                "slug": spec.slug,
                "title": spec.title,
                "state": state,
                "updated": self._updated(path),
                "summary": self._summary(spec),
            })
        for run in self.runs.values():
            if run.slug in {b["slug"] for b in books}:
                continue
            books.append({
                "slug": run.slug,
                "title": run.title,
                "state": run.state,
                "updated": self._updated(self.directory(run.slug)),
                "summary": "just requested",
            })
        # A request that never became a plan still belongs on the shelf: the log
        # is the only record of what happened, so hiding it would lose it.
        planned = {b["slug"] for b in books}
        for path in sorted(self.root.glob("*/studio.log")):
            slug = path.parent.name
            if slug in planned or self.spec_path(slug).exists():
                continue
            books.append({
                "slug": slug,
                "title": self._requested_title(slug) or slug.replace("-", " ").title(),
                "state": "failed",
                "updated": self._updated(path),
                "summary": "no plan was written - see the log",
            })
        return books

    def _requested_title(self, slug: str) -> str:
        """The title the publisher typed, kept next to the request itself."""
        path = self.directory(slug) / "request.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        return str(payload.get("title", "")).strip() if isinstance(payload, dict) else ""

    def _updated(self, path: Path) -> str:
        try:
            stamp = time.strftime("%d %b %H:%M", time.localtime(path.stat().st_mtime))
        except OSError:
            stamp = ""
        return stamp

    def _summary(self, spec: BookSpec) -> str:
        return (
            f"{len(spec.chapter_specs())} chapters, "
            f"{len(spec.sources)} sources, {spec.min_words}-{spec.max_words} words"
        )

    # ----------------------------------------------------------------- intake
    def request_book(self, fields: dict, backend: str = "auto") -> Run:
        """A new book request: plan it with the model, then write it."""
        title = str(fields.get("title", "")).strip()
        introduction = str(fields.get("introduction", "")).strip()
        if not title:
            raise ValueError("the book needs a title")
        if len(introduction) < 40:
            raise ValueError(
                "the introduction needs to be a sentence or two, so the model knows "
                "what the book is about"
            )
        chapters = _int(fields.get("chapters"), 3, 1, 12)
        min_words = _int(fields.get("min_words"), 600, 200, 4000)
        max_words = _int(fields.get("max_words"), 900, 300, 6000)
        if max_words <= min_words:
            max_words = min_words + 300

        urls = str(fields.get("urls", "")).strip()
        model_choice = str(fields.get("model", "")).strip() or "auto"
        if not urls and not self._model_available(
            "offline" if model_choice == "offline" else backend
        ):
            # Caught here rather than in the run, so the form comes back with the
            # reason and the field to fill instead of a failed run and a log.
            raise ValueError(
                "there is nothing to plan from yet: no writing model is answering, "
                "and no source links were pinned. Add a link or two below - public "
                "pages that carry the figures - and the book will be built from "
                "them, or start Ollama and a model will find the sources itself."
            )

        request = spec_from_form(
            title=title,
            introduction=introduction,
            audience=str(fields.get("audience", "")).strip(),
            chapters=chapters,
            min_words=min_words,
            max_words=max_words,
            voice=str(fields.get("voice", "")).strip(),
            urls=urls,
            author=str(fields.get("author", "")).strip(),
        )
        slug = self.unique_slug(title)
        request.slug = slug

        run = Run(slug=slug, title=title, directory=self.directory(slug))
        run.model_choice = model_choice
        with self.lock:
            self.runs[slug] = run
        run.say(f"Requested: {title}")
        run.say(
            f"{chapters} chapters of {min_words}-{max_words} words; "
            f"{len([s for s in request.sources if s.get('url')])} pinned source link(s)"
        )
        if run.model_choice == "offline":
            run.say(
                "No language model: the plan will be built from the links you "
                "pinned, and the chapters quoted from them."
            )
        return run

    @staticmethod
    def _model_available(backend: str) -> bool:
        """Whether a model is reachable for this request, asked once and cheaply.

        Planning with no model and no links is impossible, and finding that out
        three minutes into a run is worse than being asked for a link now.
        """
        from ..llm import LLMError, resolve_backend

        try:
            return resolve_backend(backend).name != "offline"
        except LLMError:
            return False

    # -------------------------------------------------------------------- run
    def start(self, run: Run, backend: str = "auto", rounds: int = 3) -> None:
        if run.state == "running":
            return
        run.state = "running"
        run.problem = ""
        thread = threading.Thread(
            target=self._run, args=(run, backend, rounds),
            name=f"booksmith-{run.slug}", daemon=True,
        )
        run.thread = thread
        thread.start()

    def _run(self, run: Run, backend: str, rounds: int) -> None:
        run.directory.mkdir(parents=True, exist_ok=True)
        out_dir = run.directory / "output"

        def log(line: str) -> None:
            run.say(line)
            self._flush(run)

        try:
            spec = self._plan(run, backend, log)
            run.plan = [
                {"title": c["title"], "purpose": c["purpose"]}
                for c in spec.chapter_specs()
            ]
            spec.save(self.spec_path(run.slug))
            log(f"Spec saved to {self.spec_path(run.slug)}")

            problems = spec.problems()
            if problems:
                run.problem = "; ".join(problems[:4])
                log("SPEC REFUSED: " + run.problem)
                run.state = "failed"
                return

            config = RunConfig(
                out_dir=str(out_dir),
                trace_dir=str(out_dir / "trace"),
                spec=spec,
                max_rounds=rounds,
                chapters=spec.chapters,
                min_words=spec.min_words,
                max_words=spec.max_words,
                target_words=spec.target_words(),
                backend=backend,
                verbose=False,
                log=log,
            )
            code = Orchestrator(config, spec).run()
            run.exit_code = code
            run.stats = _stats_from_ledger(out_dir / "ledger.json")
            if code == 0:
                run.state = "done"
                log("Done. Open the HTML edition to read it.")
            else:
                run.state = "failed"
                run.problem = (
                    "Some chapters did not pass the review gate; see review.md for "
                    "what is still wrong."
                )
                log(f"Finished with exit code {code}: some chapters were withheld.")
        except (LLMError, ValueError) as exc:
            run.state = "failed"
            run.problem = str(exc)
            log(f"FAILED: {exc}")
        except Exception as exc:  # noqa: BLE001 - report, never die silently
            run.state = "failed"
            run.problem = f"{type(exc).__name__}: {exc}"
            log("FAILED: " + traceback.format_exc())
        finally:
            self._flush(run)

    def _plan(self, run: Run, backend: str, log) -> BookSpec:
        """Ask the Architect to turn the request into a spec, or reuse a saved one."""
        spec_path = self.spec_path(run.slug)
        if spec_path.exists():
            try:
                saved = BookSpec.load(spec_path)
            except (OSError, ValueError):
                saved = None
            if saved is not None and not saved.problems():
                log(f"Reusing the plan already saved for {saved.title!r}.")
                return saved
            log("The saved plan is no longer usable; planning it again.")

        request = _spec_from_request(run)
        config = RunConfig(out_dir=str(run.directory / "output"), backend=backend,
                           verbose=False, log=log)
        from ..ledger import Ledger

        ledger = Ledger()
        ledger.spec = request
        log("Asking the Architect to plan the book...")
        architect = ArchitectAgent(config, ledger)
        planned = architect.run(request)
        log(
            f"Architect: {len(planned.sources)} source(s), "
            f"{len(planned.probe_slots)} probe(s), {len(planned.figures)} figure(s)"
        )
        return planned

    def _flush(self, run: Run, force: bool = False) -> None:
        """Mirror the transcript to disk, often enough to tail, rarely enough to be cheap."""
        now = time.monotonic()
        if not force and now - run.flushed < 0.5:
            return
        run.flushed = now
        try:
            path = self.log_path(run.slug)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(run.text(), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------ views
    def files_for(self, slug: str) -> list[dict]:
        out_dir = self.directory(slug) / "output"
        files: list[dict] = []
        for name, note in OUTPUT_FILES:
            if (out_dir / name).exists():
                files.append({"href": f"output/{name}", "name": name, "note": note})
        assets = out_dir / "assets"
        if assets.is_dir():
            for path in sorted(assets.glob("*.svg")):
                files.append({
                    "href": f"output/assets/{path.name}",
                    "name": f"assets/{path.name}",
                    "note": "figure" if path.name != "cover.svg" else "cover",
                })
        return files

    def backend_name(self, preference: str = "auto") -> str:
        try:
            return resolve_backend(preference).name
        except LLMError:
            return "offline"


def _int(value, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(str(value).strip())))
    except (TypeError, ValueError):
        return default


def _spec_from_request(run: Run) -> BookSpec:
    """Rebuild what the publisher asked for, from request.json."""
    try:
        fields = json.loads(self_request_path(run).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        fields = {}
    chapters = _int(fields.get("chapters"), 3, 1, 12)
    min_words = _int(fields.get("min_words"), 600, 200, 4000)
    max_words = _int(fields.get("max_words"), 900, 300, 6000)
    if max_words <= min_words:
        max_words = min_words + 300
    return spec_from_form(
        title=fields.get("title") or run.title,
        introduction=fields.get("introduction", ""),
        audience=fields.get("audience", ""),
        chapters=chapters,
        min_words=min_words,
        max_words=max_words,
        voice=fields.get("voice", ""),
        urls=fields.get("urls", ""),
        author=fields.get("author", ""),
    )


def self_request_path(run: Run) -> Path:
    return run.directory / "request.json"


def _stats_from_ledger(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    stats = data.get("stats") or {}
    return {
        "sources verified": f"{stats.get('sources_verified', 0)}/{stats.get('sources_considered', 0)}",
        "claims verified": f"{stats.get('claims_verified', 0)}/{stats.get('claims_total', 0)}",
        "chapters": stats.get("chapters_drafted", 0),
        "reviews": stats.get("reviews", 0),
        "seconds": stats.get("elapsed_s", 0),
    }


# ------------------------------------------------------------------- the server

SAFE_HREF = re.compile(r"^[A-Za-z0-9_./-]+$")


class Handler(BaseHTTPRequestHandler):
    server_version = "BooksmithStudio/1.0"
    studio: Studio = None            # set by serve()
    backend: str = "auto"
    rounds: int = 3

    # -------------------------------------------------------------- plumbing
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        if self.studio is not None and self.studio.verbose:
            print(f"[studio] {fmt % args}", flush=True)

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text: str, status: int = 200) -> None:
        self._send(text.encode("utf-8"), "text/html; charset=utf-8", status)

    def _json(self, payload: dict, status: int = 200) -> None:
        self._send(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    # ----------------------------------------------------------------- routes
    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        try:
            if path in ("/", "/index.html"):
                self._html(pages.index_page(
                    self.studio.shelf(), self.studio.backend_name(self.backend)))
                return
            if path.startswith("/book/"):
                slug = path[len("/book/"):].strip("/")
                self._html(self._book_page(slug))
                return
            if path.startswith("/api/books/"):
                slug = path[len("/api/books/"):].strip("/")
                run = self._run_for(slug)
                if run is None:
                    self._json({"error": f"no book called {slug!r}"}, 404)
                    return
                self._json(run.to_dict())
                return
            if path.startswith("/files/"):
                self._file(path[len("/files/"):])
                return
            self._html(pages.error_page(f"Nothing here: {path}"), 404)
        except Exception as exc:  # noqa: BLE001 - a bad request must not kill the server
            self._html(pages.error_page(f"{type(exc).__name__}: {exc}"), 500)

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path not in ("/books", "/books/"):
            self._html(pages.error_page(f"Nothing posts here: {path}"), 404)
            return
        try:
            length = min(MAX_FORM_BYTES, int(self.headers.get("Content-Length") or 0))
            raw = self.rfile.read(length).decode("utf-8", "ignore")
            fields = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
        except Exception as exc:  # noqa: BLE001
            self._html(pages.error_page(f"could not read the form: {exc}"), 400)
            return

        try:
            run = self.studio.request_book(fields, self.backend)
        except ValueError as exc:
            self._html(pages.index_page(
                self.studio.shelf(), self.studio.backend_name(self.backend),
                str(exc), "bad"), 400)
            return

        save_request(run, fields)
        # "auto" means "whatever this studio was started with"; only an explicit
        # choice of no model overrides it.
        backend = "offline" if run.model_choice == "offline" else self.backend
        self.studio.start(run, backend, self.rounds)
        self.send_response(303)
        self.send_header("Location", f"/book/{run.slug}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ----------------------------------------------------------------- pieces
    def _run_for(self, slug: str) -> Run | None:
        run = self.studio.runs.get(slug)
        if run is not None:
            return run
        spec_path = self.studio.spec_path(slug)
        log_file = self.studio.log_path(slug)
        if not spec_path.exists():
            # A run that never got as far as a plan - it failed, or the studio was
            # stopped mid-flight - still has a log worth reading. Rebuild the run
            # from it so the URL the browser was redirected to keeps working.
            if not log_file.exists():
                return None
            run = Run(
                slug=slug,
                title=slug.replace("-", " ").title(),
                directory=self.studio.directory(slug),
                state="failed",
            )
            run.log = log_file.read_text(encoding="utf-8").splitlines()
            run.problem = (
                "This run did not finish, so there is no plan or book for it. "
                "The log below says where it stopped."
            )
            run.stats = _stats_from_ledger(
                self.studio.directory(slug) / "output" / "ledger.json"
            )
            return run

        spec = BookSpec.load(spec_path)
        run = Run(
            slug=slug,
            title=spec.title,
            directory=self.studio.directory(slug),
            state="done",
        )
        if log_file.exists():
            run.log = log_file.read_text(encoding="utf-8").splitlines()
        run.stats = _stats_from_ledger(
            self.studio.directory(slug) / "output" / "ledger.json"
        )
        run.plan = [
            {"title": c["title"], "purpose": c["purpose"]} for c in spec.chapter_specs()
        ]
        return run

    def _book_page(self, slug: str) -> str:
        run = self._run_for(slug)
        if run is None:
            return pages.error_page(f"No book called {slug!r}.")
        return pages.book_page(
            run.slug, run.title, run.state, run.text(),
            self.studio.files_for(run.slug), run.stats, run.plan, run.problem,
        )

    def _file(self, rest: str) -> None:
        parts = rest.split("/", 1)
        if len(parts) != 2:
            self._html(pages.error_page("bad file path"), 404)
            return
        slug, href = parts
        if not SAFE_HREF.match(href) or ".." in href:
            self._html(pages.error_page("bad file path"), 400)
            return
        target = (self.studio.directory(slug) / href).resolve()
        root = self.studio.directory(slug).resolve()
        if not str(target).startswith(str(root)) or not target.is_file():
            self._html(pages.error_page(f"no file at {href}"), 404)
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".md": "text/markdown; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(target.suffix, "application/octet-stream")
        self._send(target.read_bytes(), ctype)


def save_request(run: Run, fields: dict) -> None:
    """Keep exactly what the publisher asked for, next to the spec."""
    run.directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "title": fields.get("title", ""),
        "introduction": fields.get("introduction", ""),
        "audience": fields.get("audience", ""),
        "voice": fields.get("voice", ""),
        "author": fields.get("author", ""),
        "chapters": fields.get("chapters", ""),
        "min_words": fields.get("min_words", ""),
        "max_words": fields.get("max_words", ""),
        "urls": fields.get("urls", ""),
        "requested": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    self_request_path(run).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def serve(root: Path | None = None, port: int = DEFAULT_PORT,
          backend: str = "auto", rounds: int = 3,
          open_browser: bool = True, verbose: bool = False) -> None:
    studio = Studio(root=root, verbose=verbose)
    Handler.studio = studio
    Handler.backend = backend
    Handler.rounds = rounds

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    name = studio.backend_name(backend)
    print(f"Booksmith Studio on {url}", flush=True)
    print(f"  books: {studio.root.resolve()}", flush=True)
    print(f"  writing model: {name}", flush=True)
    if name == "offline":
        print(
            "  note: planning a new book needs a model. Start Ollama and pull one"
            " (`ollama pull qwen2.5`), or set ANTHROPIC_API_KEY, OPENAI_API_KEY or"
            " GEMINI_API_KEY. The bundled book still runs without any of these.",
            flush=True,
        )
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - a headless box is fine
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping", flush=True)
    finally:
        httpd.server_close()


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="studio.py", description="The Booksmith Studio index page."
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--books", default="books", help="where books live")
    parser.add_argument("--backend", default="auto",
                        choices=["auto", "offline", "anthropic", "openai", "gemini",
                                 "ollama"])
    parser.add_argument("--model", default=None,
                        help="model id, e.g. qwen2.5:7b for ollama")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.model:
        # Every agent resolves its backend from the environment, so setting this
        # here covers the Architect and the whole pipeline in one move.
        os.environ["BOOKSMITH_MODEL"] = args.model
    serve(
        root=Path(args.books),
        port=args.port,
        backend=args.backend,
        rounds=args.rounds,
        open_browser=not args.no_browser,
        verbose=args.verbose,
    )
    return 0