"""The studio index page.

One form, one job: collect a title and an introduction, then hand them to the
Architect. Everything below the form is status - what is being planned, which
agents are working, which chapters passed, and where the finished files are.

Kept as plain HTML and CSS in a string so the whole studio is stdlib, with no
build step and no template engine to install.
"""

from __future__ import annotations

import html
import json

# Three public pages about UPI in India, offered as a starting point so a
# publisher with no links of their own can still see the studio work a book in one
# click. They are ordinary Government of India press releases, they are pasted into
# a field the publisher can edit or delete, and every figure in them is still
# verified against the live page before it can reach a chapter.
EXAMPLE_LINKS = "\n".join([
    "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2257087&lang=1&reg=3",
    "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2286608&lang=1&reg=3",
    "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2200569&lang=1&reg=3",
])

# One click fills the links box. The links go into the field as text, so what is
# used is always visible and editable, never a hidden default.
EXAMPLE_BUTTON = (
    "<button type=\"button\" class=\"ghost\" id=\"example-links\">"
    "fill in three example links</button>"
    "<script>document.getElementById('example-links')"
    ".addEventListener('click', function () {"
    " var f = document.getElementById('urls');"
    " f.value = " + json.dumps(EXAMPLE_LINKS) + ";"
    " f.focus(); });</script>"
)

STYLE = """
:root {
  --ink:#16262b; --muted:#657577; --line:#e2ddd1; --paper:#fbf9f4;
  --deep:#0f3d3e; --mid:#12707a; --accent:#e8b04b; --bad:#b3452f; --good:#2f6f4e;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink);
  font:16px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; }
a { color:var(--mid); }
.masthead { background:linear-gradient(140deg,var(--deep),var(--mid));
  color:#fff; padding:2.6rem 0 2.2rem; }
.masthead .inner, main { max-width:62rem; margin:0 auto; padding:0 1.5rem; }
.masthead h1 { margin:0 0 .35rem; font-size:1.9rem; letter-spacing:-.01em; }
.masthead p { margin:0; opacity:.85; max-width:44rem; }
.pill { display:inline-block; background:rgba(255,255,255,.16); border-radius:999px;
  padding:.25rem .8rem; font-size:.78rem; margin-right:.4rem; }
main { padding-top:2rem; padding-bottom:5rem; }
.grid { display:grid; grid-template-columns:1.4fr .9fr; gap:1.6rem; align-items:start; }
@media (max-width:900px){ .grid { grid-template-columns:1fr; } }
.card { background:#fff; border:1px solid var(--line); border-radius:14px;
  padding:1.4rem 1.5rem; box-shadow:0 1px 2px rgba(20,30,30,.04); }
.card h2 { margin:0 0 .3rem; font-size:1.15rem; }
.card p.hint { margin:0 0 1.1rem; color:var(--muted); font-size:.9rem; }
label { display:block; font-weight:600; font-size:.9rem; margin:.9rem 0 .3rem; }
label .opt { font-weight:400; color:var(--muted); }
input[type=text], textarea, select, input[type=number] {
  width:100%; padding:.65rem .75rem; border:1px solid var(--line); border-radius:9px;
  font:inherit; background:#fdfdfb; color:inherit; }
textarea { min-height:8.5rem; resize:vertical; }
textarea:focus, input:focus, select:focus { outline:2px solid var(--mid);
  outline-offset:1px; }
.row { display:flex; gap:.9rem; flex-wrap:wrap; }
.row > div { flex:1 1 8rem; }
button { margin-top:1.2rem; background:var(--deep); color:#fff; border:0;
  border-radius:9px; padding:.8rem 1.4rem; font:inherit; font-weight:600;
  cursor:pointer; }
button:hover { background:#12494b; }
button.ghost { margin-top:.5rem; background:transparent; color:var(--mid);
  border:1px solid var(--line); font-weight:500; padding:.4rem .8rem; font-size:.86rem; }
button.ghost:hover { background:#eef4f3; color:var(--deep); }
a.preview { display:inline-block; margin-top:1rem; background:var(--accent);
  color:#3a2a05; border-radius:9px; padding:.6rem 1.1rem; font-weight:600;
  text-decoration:none; }
a.preview:hover { background:#f0c273; }
button[disabled] { background:#9fb0b0; cursor:not-allowed; }
.alert { border-radius:10px; padding:.8rem 1rem; font-size:.92rem; margin:1rem 0; }
.alert.bad { background:#fbeeeb; color:var(--bad); border:1px solid #f0cfc7; }
.alert.info { background:#eef5f5; color:var(--deep); border:1px solid #cfe0e0; }
.list { list-style:none; padding:0; margin:0; }
.list li { border-top:1px solid var(--line); padding:.8rem 0; }
.list li:first-child { border-top:0; }
.title { font-weight:600; text-decoration:none; color:var(--ink); }
.meta { color:var(--muted); font-size:.82rem; margin-top:.15rem; }
.tag { display:inline-block; font-size:.72rem; letter-spacing:.04em;
  text-transform:uppercase; border-radius:5px; padding:.1rem .45rem;
  background:#eef2f2; color:var(--muted); margin-left:.4rem; }
.tag.run { background:#fdf1d9; color:#8a6412; }
.tag.done { background:#e6f1ea; color:var(--good); }
.tag.fail { background:#fbeeeb; color:var(--bad); }
pre.log { background:#101c1e; color:#cfe3e0; border-radius:10px; padding:1rem;
  overflow:auto; max-height:26rem; font:12.5px/1.55 ui-monospace,SFMono-Regular,
  Consolas,monospace; white-space:pre-wrap; }
table.files { width:100%; border-collapse:collapse; font-size:.9rem; }
table.files td { padding:.45rem .3rem; border-top:1px solid var(--line); }
.stat { display:flex; gap:1.2rem; flex-wrap:wrap; margin:.6rem 0 1rem; }
.stat div { background:#fff; border:1px solid var(--line); border-radius:10px;
  padding:.6rem .9rem; min-width:7rem; }
.stat b { display:block; font-size:1.3rem; }
.stat span { color:var(--muted); font-size:.78rem; }
details summary { cursor:pointer; font-weight:600; margin:.6rem 0; }
.plan li { color:var(--muted); font-size:.88rem; }
"""


def page(body: str, status: int = 200) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Booksmith Studio</title><style>" + STYLE + "</style></head><body>"
        + body + "</body></html>"
    )


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


def index_page(books: list[dict], backend: str, message: str = "", message_kind: str = "") -> str:
    """The front door: the form on the left, the shelf on the right."""
    shelf = []
    for book in books:
        shelf.append(
            "<li>"
            f"<a class=\"title\" href=\"/book/{esc(book['slug'])}\">{esc(book['title'])}</a>"
            f"<span class=\"tag {esc(book.get('state', 'done'))}\">{esc(book.get('state', 'done'))}</span>"
            f"<div class=\"meta\">{esc(book.get('updated', ''))} &middot; "
            f"{esc(book.get('summary', ''))}</div>"
            "</li>"
        )
    shelf_html = (
        f"<ul class=\"list\">{''.join(shelf)}</ul>" if shelf
        else "<p class=\"hint\">No books yet. Write a title on the left.</p>"
    )

    alert = ""
    if message:
        alert = f"<div class=\"alert {esc(message_kind)}\">{esc(message)}</div>"

    backend_pill = (
        f"<span class=\"pill\">writing model: {esc(backend)}</span>"
        if backend != "offline" else
        "<span class=\"pill\" style=\"background:#fbe9c8;color:#7a5a10\">"
        "no model answering &mdash; pin the source links and the book will be built "
        "from them alone</span>"
    )

    auto_label = ("auto &mdash; use a model if one answers"
                  if backend != "offline" else
                  "auto &mdash; none is answering, so use my links")
    model_choice = (
        "<label for=\"model\">Writing model</label>"
        "<select id=\"model\" name=\"model\">"
        f"<option value=\"auto\">{auto_label}</option>"
        "<option value=\"offline\">none &mdash; build only from my links</option>"
        "</select>"
        "<p class=\"hint\" style=\"margin:.2rem 0 .9rem\">Without a model the plan "
        "and the prose come from the links you pin, quoted as published. That is "
        "slower to read than a written book and far easier to check.</p>"
    )

    return page(
        "<header class=\"masthead\"><div class=\"inner\">"
        "<h1>Booksmith Studio</h1>"
        "<p>Give it a title and an introduction. The Architect plans the chapters, "
        "finds the sources, and the team writes, checks and draws the book.</p>"
        f"<p style=\"margin-top:.9rem\">{backend_pill}"
        "<span class=\"pill\">every figure verified from a live page</span></p>"
        "</div></header>"
        "<main><div class=\"grid\">"
        f"<section class=\"card\"><h2>New book</h2>"
        "<p class=\"hint\">Only the title and the introduction are required. "
        "Everything else the model plans for itself.</p>"
        f"{alert}"
        "<form method=\"post\" action=\"/books\">"
        "<label for=\"title\">Title</label>"
        "<input type=\"text\" id=\"title\" name=\"title\" required autofocus "
        "placeholder=\"How QR Codes Changed the Village Shop\">"
        "<label for=\"intro\">Introduction <span class=\"opt\">&mdash; what is this "
        "book about, and who is it for?</span></label>"
        "<textarea id=\"intro\" name=\"introduction\" required "
        "placeholder=\"A guide for the shop owners who now take payment by phone: how "
        "it started, what it costs, what to do when it goes wrong.\"></textarea>"
        "<label for=\"urls\">Source links <span class=\"opt\">&mdash; optional, one "
        "per line. Use these even if you have none.</span></label>"
        "<p class=\"hint\" style=\"margin:.2rem 0 .4rem\">A good link is a public "
        "page that states figures: a press release, an annual report, a bank "
        "explainer's FAQ. The Researcher reads each one and quotes it; the "
        "FactChecker reads them again before the book is finished.</p>"
        "<textarea id=\"urls\" name=\"urls\" style=\"min-height:5rem\" "
        "placeholder=\"https://... press release&#10;https://... annual report\"></textarea>"
        f"{EXAMPLE_BUTTON}"
        "<div class=\"row\">"
        "<div><label for=\"audience\">Reader <span class=\"opt\">optional</span></label>"
        "<input type=\"text\" id=\"audience\" name=\"audience\" "
        "placeholder=\"Shop owners in small towns\"></div>"
        "<div><label for=\"chapters\">Chapters</label>"
        "<input type=\"number\" id=\"chapters\" name=\"chapters\" value=\"3\" min=\"1\" "
        "max=\"12\"></div>"
        "</div>"
        "<div><label for=\"author\">Byline <span class=\"opt\">optional</span></label>"
        "<input type=\"text\" id=\"author\" name=\"author\" "
        "placeholder=\"Leave empty and the cover credits the agents\"></div>"
        "<div class=\"row\">"
        "<div><label for=\"min_words\">Min words</label>"
        "<input type=\"number\" id=\"min_words\" name=\"min_words\" value=\"600\" "
        "min=\"200\" step=\"50\"></div>"
        "<div><label for=\"max_words\">Max words</label>"
        "<input type=\"number\" id=\"max_words\" name=\"max_words\" value=\"900\" "
        "min=\"300\" step=\"50\"></div>"
        "<div><label for=\"voice\">Voice <span class=\"opt\">optional</span></label>"
        "<input type=\"text\" id=\"voice\" name=\"voice\" "
        "placeholder=\"plain, warm, practical\"></div>"
        "</div>"
        f"{model_choice}"
        "<button type=\"submit\">Plan and write this book</button>"
        "</form></section>"
        f"<section class=\"card\"><h2>Shelf</h2>{shelf_html}</section>"
        "</div></main>"
    )


def book_page(slug: str, title: str, state: str, log: str, files: list[dict],
              stats: dict, plan: list[dict], problem: str = "") -> str:
    """The working page for one book: live log, plan, stats, output files."""
    tags = {"running": "run", "done": "done", "failed": "fail", "planned": "run"}
    header = (
        f"<p><a href=\"/\">&larr; all books</a></p>"
        f"<h2>{esc(title)}</h2>"
        f"<span class=\"tag {esc(tags.get(state, state))}\">{esc(state)}</span>"
    )
    if problem:
        header += f"<div class=\"alert bad\">{esc(problem)}</div>"

    stat_html = ""
    if stats:
        cells = "".join(
            f"<div><b>{esc(value)}</b><span>{esc(key.replace('_', ' '))}</span></div>"
            for key, value in stats.items()
        )
        stat_html = f"<div class=\"stat\">{cells}</div>"

    plan_html = ""
    if plan:
        items = "".join(
            f"<li>{esc(chapter.get('title', ''))} "
            f"<span class=\"meta\">{esc(chapter.get('purpose', ''))}</span></li>"
            for chapter in plan
        )
        plan_html = f"<details open><summary>Plan</summary><ul class=\"list plan\">{items}</ul></details>"

    file_rows = "".join(
        f"<tr><td><a href=\"/files/{esc(slug)}/{esc(item['href'])}\" target=\"_blank\">"
        f"{esc(item['name'])}</a></td><td class=\"meta\">{esc(item.get('note', ''))}</td></tr>"
        for item in files
    )
    files_html = (
        f"<h2>Files</h2><table class=\"files\">{file_rows}</table>" if file_rows else ""
    )

    # One link that opens the finished book as a single page, for reading or
    # sending on, rather than a file list to work through.
    preview_html = ""
    if any(item["name"] == "preview.html" for item in files):
        preview_html = (
            f"<p><a class=\"preview\" href=\"/files/{esc(slug)}/output/preview.html\" "
            "target=\"_blank\">Preview the whole book &rarr;</a>"
            "<span class=\"hint\" style=\"display:block;margin:.35rem 0 0\">"
            "One self-contained file: every chapter, every figure, and the "
            "evidence behind it.</span></p>"
        )

    return page(
        "<header class=\"masthead\"><div class=\"inner\">"
        "<h1>Booksmith Studio</h1><p>Six agents, one ledger, every number "
        "checked against a live page.</p></div></header>"
        f"<main><section class=\"card\">{header}{preview_html}{stat_html}{plan_html}"
        f"{files_html}</section>"
        "<section class=\"card\" style=\"margin-top:1.6rem\">"
        "<h2>Run log</h2><p class=\"hint\">Planner, Researcher, Writer, Editor, "
        "FactChecker, Voicekeeper.</p>"
        f"<pre class=\"log\" id=\"log\">{esc(log)}</pre></section></main>"
        "<script>\n"
        "const log = document.getElementById('log');\n"
        "let state = '';\n"
        "async function poll() {\n"
        "  try {\n"
        "    const r = await fetch('/api/books/" + esc(slug) + "');\n"
        "    const d = await r.json();\n"
        "    if (d.log !== log.textContent) {\n"
        "      const atBottom = log.scrollTop + log.clientHeight > log.scrollHeight - 40;\n"
        "      log.textContent = d.log;\n"
        "      if (atBottom) log.scrollTop = log.scrollHeight;\n"
        "    }\n"
        "    const previous = state;\n"
        "    state = d.state;\n"
        "    // Reload only on a real change. The first poll always finds the state\n"
        "    // the server just rendered, so reloading on it would fetch the same\n"
        "    // page again for nothing - and on a running book it never settles.\n"
        "    if (previous && previous !== state) location.reload();\n"
        "    if (state === 'running') setTimeout(poll, 2000);\n"
        "  } catch (e) { setTimeout(poll, 5000); }\n"
        "}\n"
        "if (" + ("true" if state == "running" else "false") + ") poll();\n"
        "</script>"
    )


def error_page(message: str) -> str:
    return page(
        "<main><section class=\"card\"><h2>Something went wrong</h2>"
        f"<div class=\"alert bad\">{esc(message)}</div>"
        "<p><a href=\"/\">&larr; back to the index</a></p></section></main>"
    )