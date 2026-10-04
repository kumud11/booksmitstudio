#!/usr/bin/env python3
"""BookSmith - run the multi-agent book pipeline.

No installation and no API key required for the bundled book:

    python run.py

With a language model (uses it for planning, drafting and editing, falls back
cleanly):

    python run.py --backend anthropic
    ANTHROPIC_API_KEY=sk-... python run.py

Any book whose plan is in a spec file:

    python run.py --spec books/my-book/spec.json
    python run.py --book upi --out output/upi-run2

Useful flags:

    python run.py --rounds 4            give reviewers a larger budget
    python run.py --out output/run2      write somewhere else
    python run.py --no-live              skip network; demonstrates the gate
    python run.py --quiet                just the summary
    python run.py --list-books           what is available to run

A new book from the command line, planned by the Architect or, with no model,
assembled from the links you pin:

    python run.py --title "Pay Me on UPI" --intro "How digital payments changed \\
        small business in India." --urls https://... --out output/upi
    python run.py --title "..." --intro "..." --urls https://... \\
        --backend offline --save-spec books/pay-me-on-upi/spec.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from booksmith.config import RunConfig
from booksmith.orchestrator import Orchestrator
from booksmith.spec import BUNDLED, BookSpec, bundled_spec, slugify


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Research and write a cited book with a team of agents.",
    )
    parser.add_argument("--book", default="upi", choices=sorted(BUNDLED),
                        help="which bundled book to make (default: upi)")
    parser.add_argument("--spec", default=None,
                        help="path to a book spec JSON file; overrides --book")
    parser.add_argument("--title", default=None,
                        help="plan a new book from this title instead of a spec")
    parser.add_argument("--intro", default=None,
                        help="the new book's introduction (with --title)")
    parser.add_argument("--urls", default="",
                        help="source links for the new book, comma separated; with "
                             "--backend offline these are the whole book")
    parser.add_argument("--audience", default="", help="who the new book is for")
    parser.add_argument("--author", default="",
                        help="byline for the cover (default: the agents)")
    parser.add_argument("--voice", default="", help="voice for the new book")
    parser.add_argument("--save-spec", default=None,
                        help="write the plan for a new book here and stop")
    parser.add_argument("--out", default="output", help="output directory (default: output)")
    parser.add_argument("--rounds", type=int, default=3,
                        help="max review rounds per chapter (default: 3)")
    parser.add_argument("--backend", default="auto",
                        choices=["auto", "offline", "anthropic", "openai", "gemini",
                                 "ollama"],
                        help="language model backend (default: auto)")
    parser.add_argument("--model", default=None,
                        help="override the model id, e.g. qwen2.5:7b for ollama")
    parser.add_argument("--no-live", action="store_true",
                        help="disable all network access; nothing will verify")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip the fact-checker's live re-fetch pass")
    parser.add_argument("--target-words", type=int, default=None,
                        help="target words per chapter (default: midpoint of the spec)")
    parser.add_argument("--timeout", type=int, default=30, help="per-request timeout (s)")
    parser.add_argument("--workers", type=int, default=8, help="concurrent fetches")
    parser.add_argument("--quiet", action="store_true", help="less console output")
    parser.add_argument("--list-books", action="store_true",
                        help="list the bundled books and exit")
    return parser.parse_args(argv)


def load_spec(args) -> BookSpec:
    if args.spec:
        path = Path(args.spec)
        if not path.exists():
            raise SystemExit(f"no such spec file: {path}")
        return BookSpec.load(path)
    if args.title:
        return plan_new_book(args)
    return bundled_spec(args.book)


def plan_new_book(args) -> BookSpec:
    """Ask the Architect for a plan, or build one from the links given.

    The plan is written next to the output as `spec.json` so the run can be
    repeated, edited or handed to the studio without planning it again.
    """
    from booksmith.agents.architect import ArchitectAgent
    from booksmith.ledger import Ledger
    from booksmith.spec import spec_from_form

    if not args.intro:
        raise SystemExit("--title needs --intro: say what the book is about")
    request = spec_from_form(
        title=args.title,
        introduction=args.intro,
        audience=args.audience,
        voice=args.voice,
        chapters=3,
        urls=args.urls,
        author=args.author,
    )
    request.slug = slugify(args.title)
    config = RunConfig(
        out_dir=args.out,
        backend=args.backend,
        model=args.model,
        verbose=not args.quiet,
    )
    ledger = Ledger()
    spec = ArchitectAgent(config, ledger).run(request)

    path = Path(args.out) / "spec.json"
    spec.save(path)
    if not args.quiet:
        print(f"plan written to {path}")
    if args.save_spec:
        spec.save(Path(args.save_spec))
        if not args.quiet:
            print(f"plan also written to {args.save_spec}")
        raise SystemExit(0)
    return spec


def build_config(args, spec: BookSpec) -> RunConfig:
    chapters = spec.chapters
    min_words, max_words = spec.min_words, spec.max_words
    words = args.target_words or spec.target_words()
    words = max(min_words + 60, min(max_words - 60, words))
    return RunConfig(
        out_dir=args.out,
        trace_dir=f"{args.out}/trace",
        spec=spec,
        max_rounds=args.rounds,
        chapters=chapters,
        min_words=min_words,
        max_words=max_words,
        target_words=words,
        request_timeout=args.timeout,
        fetch_workers=args.workers,
        offline=args.no_live,
        verify_live=not (args.no_verify or args.no_live),
        backend=args.backend,
        model=args.model,
        verbose=not args.quiet,
    )


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.list_books:
        for name, title in BUNDLED.items():
            print(f"{name:10} {title}")
        return 0

    spec = load_spec(args)
    problems = spec.problems()
    if problems:
        print(f"this spec cannot be run as it stands:", file=sys.stderr)
        for problem in problems[:10]:
            print(f"  - {problem}", file=sys.stderr)
        return 3

    config = build_config(args, spec)
    try:
        return Orchestrator(config, spec).run()
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())