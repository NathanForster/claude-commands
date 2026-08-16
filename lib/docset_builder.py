"""Shared Markdown -> PDF engine: assembles a set of Markdown documents into one
consolidated, bookmarked PDF (cover + linked TOC + per-part covers), and also
renders a single Markdown file to a standalone PDF. Project-agnostic — every
project-specific detail (which documents, titles, cover text, paths) is supplied
by the caller, either as a JSON config or by importing this module.

This lives in the shared Claude commands repo so multiple projects share ONE copy
of the (hard-won) table/heading pagination logic. See `/build-docs`.

Requires: pymupdf, markdown-it-py, pypdf, beautifulsoup4
    pip install pymupdf markdown-it-py pypdf beautifulsoup4

Public API
----------
    build_docset(structure, docs_dir, out_path, *, title, subtitle=None,
                 cover_lines=(), base_css=None) -> int   # returns page count
    render_markdown_file(src_md, out_pdf, *, landscape=False,
                         base_css=None) -> int            # returns page count
    load_config(path) -> dict                             # parse a DOCSET json

`structure` is a list of parts: [(part_title, [leaf, ...]), ...] where each leaf
is (num, acronym, filename, full_title, landscape_bool). A filename ending in
`.pdf` is treated as a pre-rendered leaf (a generated section cover is prepended
and the PDF concatenated as-is); filenames are resolved relative to `docs_dir`
(".." is fine for a doc living outside it).

CLI
---
    python docset_builder.py <config.json>              # build a docset
    python docset_builder.py --single <in.md> <out.pdf> [--landscape]

Table engine (rewritten 2026-07-09; all rules below verified empirically against
the installed PyMuPDF Story engine before being relied on):
  * Column widths: Story ignores every percent width form (col/th/td, attribute
    or style) and lays such tables out with EQUAL columns. It honors absolute
    lengths in a STYLE property (width:Npt) on <col>, treating them as
    PROPORTIONAL WEIGHTS scaled to fill the table width -- an over/under-
    subscribed sum cannot overflow the page. Widths here are computed per table
    from content statistics (see compute_column_weights).
  * Long unbreakable tokens (paths, REQ lists) widen a cell's layout floor and
    can overpaint the neighboring column; Story honors U+200B (zero-width
    space) as a break opportunity, so soft breaks are injected into any long
    whitespace-free run inside table cells (inject_soft_breaks).
  * A row taller than one page is SILENTLY TRUNCATED under col-width layout
    (Story reports done with the remainder of the table unrendered -- worse
    than a build failure). Every cell is therefore budget-split into
    continuation rows sized to its own column width so no row can approach a
    page in height (split_overlong_cells), and every rendered part is verified
    against per-row canary needles afterwards (verify_no_lost_rows).
  * Repeating headers: Story does NOT repeat <thead> across page breaks, and
    page-break-before is honored on a wrapper <div> but NOT on a <table>.
    Story is also not allowed to paginate a continuation table itself (a
    chunk starting mid-page that must break entered an infinite placement
    loop): rows of any page-spanning table are greedy-packed by their
    MEASURED heights into chunks guaranteed to fit one page, each with a
    cloned <colgroup>+<thead>, pinned to a fresh page by a page-break div
    (repeat_headers_across_pages). Row page/height data comes from
    Story.element_positions during a measurement render; note the measurement
    loop MUST draw each placed page into a real DocumentWriter -- place()
    alone does not advance the story (this, not table layout per se, is what
    previously looked like a "no-progress oscillation"). The measurement hands
    Story a whole UNCHUNKED table, so it can still hit that same mid-page-break
    loop at unlucky vertical offsets (e.g. a doc's leading section cover shifts a
    long table down just enough); measure_rows detects the stall and falls back
    to a stall-proof tall-page measurement (_measure_tall) rather than looping.
"""
import copy
import sys
import tempfile
from pathlib import Path

import fitz
from bs4 import BeautifulSoup, NavigableString
from markdown_it import MarkdownIt
from pypdf import PdfWriter, PdfReader

# The document structure and paths are supplied by the caller (build_docset /
# load_config); this module holds no project-specific data.

md = MarkdownIt("commonmark").enable("table")

BASE_CSS = """
@page { size: {SIZE}; margin: 0; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5px; line-height: 1.35; color: #1a1a1a; }
h1 { font-size: 20px; margin: 0 0 10px 0; border-bottom: 2px solid #333; padding-bottom: 6px; }
h2 { font-size: 15px; margin: 18px 0 6px 0; color: #1a3d6d; }
h3 { font-size: 12.5px; margin: 14px 0 5px 0; color: #333; }
h4 { font-size: 11px; margin: 10px 0 4px 0; }
p { margin: 4px 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; table-layout: fixed; }
th, td { border: 0.75px solid #999; padding: 2px 4px; font-size: 7.5px; vertical-align: top; word-wrap: break-word; overflow-wrap: break-word; word-break: break-word; }
th { font-weight: bold; border-bottom: 1.5px solid #333; }
code { font-family: Consolas, monospace; font-size: 9px; }
pre { background-color: #f5f5f5; padding: 6px; font-size: 8.5px; overflow-wrap: break-word; }
ul, ol { margin: 4px 0; padding-left: 20px; }
li { margin: 2px 0; }
hr { border: none; border-top: 1px solid #ccc; margin: 10px 0; }
.cover-part { font-size: 13px; color: #555; margin-bottom: 2px; }
.cover-acronym { font-size: 26px; font-weight: bold; margin: 4px 0; }
.cover-full { font-size: 16px; color: #333; margin-bottom: 4px; }
"""

# ---------------------------------------------------------------------------
# Layout metrics (empirically measured against the rendered output; the table
# borders of a portrait page land at x 46.5..565.5 -> 519pt of table width
# inside the 36pt page margins plus Story's ~10.5pt body margin per side).
PAGE_MARGIN = 36
BODY_MARGIN = 10.5           # Story's built-in <body> margin per side
TABLE_FONT_SIZE = 7.5
LINE_H = 9.2                 # observed baseline-to-baseline at 7.5px/1.35
# A col's style width is its CONTENT width; the engine adds padding (4+4) and
# collapsed borders on top (measured ~8.9pt/col), and while an UNDER-subscribed
# width set is scaled up to fill the table, an OVER-subscribed one is NOT
# scaled down -- it overflows the page. Specified widths must therefore sum to
# table_width - ncols*COL_OVERHEAD - TABLE_SLACK.
COL_OVERHEAD = 8.9
TABLE_SLACK = 2.0
MAX_SOFT_RUN = 12            # longest whitespace-free run allowed in a cell
MAX_CHUNK_ITERS = 12
MAX_PAGINATE_ITERS = 8       # outer table/heading/widow convergence loop
BODY_LINE_H = 14.2           # body-text baseline step (10.5px * 1.35)
WIDOW_TAIL_MAX = 2.4 * BODY_LINE_H   # reflow a paragraph only if <= ~2 lines spill
CONTENT_TOP = PAGE_MARGIN + BODY_MARGIN   # y where page content begins (46.5)
BODY_FONT_SIZE = 10.5        # BASE_CSS body font-size (BODY_LINE_H / 1.35)
SPLIT_TARGET_LINES = 2.0     # a row-88(b) continuation must carry >= this many lines
SPLIT_MIN_KEPT_WORDS = 8     # never leave the source block a stub
SPLIT_MAX_MOVE_WORDS = 80    # runaway guard on the donated tail

ZWSP = "​"
# Preferred soft-break points inside long tokens (break AFTER these chars).
BREAK_AFTER = set("/\\-_.,;:=)]}|&+#?")

try:
    CHAR_W = fitz.get_text_length(
        "abcdefghijklmnopqrstuvwxyz0123456789_-./ABCDEFGHIJ",
        fontname="helv", fontsize=TABLE_FONT_SIZE) / 50.0
except Exception:
    CHAR_W = 3.4


def table_width_pt(landscape):
    page_w = 792 if landscape else 612
    return page_w - 2 * PAGE_MARGIN - 2 * BODY_MARGIN


def page_content_height(landscape):
    page_h = 612 if landscape else 792
    return page_h - 2 * PAGE_MARGIN - 2 * BODY_MARGIN


def text_width(s, bold=False):
    font = "hebo" if bold else "helv"
    try:
        return fitz.get_text_length(s, fontname=font, fontsize=TABLE_FONT_SIZE)
    except Exception:
        return len(s) * CHAR_W


def _node_font(tn):
    """Measurement font for a text node: table cells mix 7.5px Helvetica with
    9px monospace <code> spans — nearly half the width difference, which is
    enough to blow row-height estimates if ignored."""
    for p in tn.parents:
        if p.name in ("code", "pre"):
            return ("cour", 9.0)
        if p.name == "th":
            return ("hebo", TABLE_FONT_SIZE)
        if p.name == "td":
            break
    return ("helv", TABLE_FONT_SIZE)


def cell_px(cell):
    """Total rendered text width of a cell's content, font-aware, in points."""
    total = 0.0
    for tn in cell.find_all(string=True):
        font, size = _node_font(tn)
        try:
            total += fitz.get_text_length(str(tn).replace(ZWSP, ""), fontname=font, fontsize=size)
        except Exception:
            total += len(str(tn)) * CHAR_W
    return total


def frag_px(cell):
    """Widest single unbreakable fragment in a cell (its layout floor)."""
    worst = 0.0
    for tn in cell.find_all(string=True):
        font, size = _node_font(tn)
        for frag in str(tn).replace(ZWSP, " ").split():
            try:
                w = fitz.get_text_length(frag, fontname=font, fontsize=size)
            except Exception:
                w = len(frag) * CHAR_W
            worst = max(worst, w)
    return worst


def strip_frontmatter(text):
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def md_to_html(text):
    return md.render(strip_frontmatter(text))


# ---------------------------------------------------------------------------
# 1) Soft-break injection: bound the longest unbreakable run in every cell so
#    no token can force a column past its assigned width (Story would let it
#    overpaint the neighboring column, not wrap it).

def soft_break_text(s, run=0, max_run=MAX_SOFT_RUN):
    """Returns (text with U+200B soft breaks, run length at end). `run` is the
    length of the unbreakable run already in progress when this text starts —
    long runs frequently SPAN inline elements (<code>a</code>/<code>b</code>
    concatenates with no break opportunity between the nodes), so the counter
    must be carried across every text node of a cell, not reset per node."""
    out = []
    for ch in s:
        out.append(ch)
        if ch.isspace() or ch == ZWSP:
            run = 0
            continue
        run += 1
        if run >= max_run or (run >= max_run // 2 and ch in BREAK_AFTER):
            out.append(ZWSP)
            run = 0
    return "".join(out), run


def inject_soft_breaks(cell):
    run = 0
    for tn in list(cell.find_all(string=True)):
        s = str(tn)
        broken, run = soft_break_text(s, run)
        if broken != s:
            tn.replace_with(NavigableString(broken))


# ---------------------------------------------------------------------------
# 2) Content-measured column widths, emitted as <col style="width:Npt">
#    (proportional weights -- see module docstring).

def percentile(values, p):
    if not values:
        return 0
    vs = sorted(values)
    return vs[min(len(vs) - 1, int(round(p * (len(vs) - 1))))]


def compute_column_weights(table, landscape):
    """Optimum widths: each column gets its layout floor (widest unbreakable
    fragment) plus a share of the remaining width proportional to its
    90th-percentile rendered cell width. Proportional sharing (exponent 1.0)
    was chosen by simulating total table height on the register/LIVE/RTVM
    corpora against 0.6/0.8/1.0/1.2 — it equalizes wrapped line counts across
    the columns of the tall rows, which is what minimizes page count."""
    thead = table.find("thead")
    tbody = table.find("tbody")
    header_cells = thead.find_all("th") if thead else []
    ncols = len(header_cells)
    if ncols == 0:
        return None
    body_rows = tbody.find_all("tr", recursive=False) if tbody else []

    floors, scores = [], []
    for ci in range(ncols):
        cells = []
        for tr in body_rows:
            tds = tr.find_all("td", recursive=False)
            if ci < len(tds):
                cells.append(tds[ci])
        frag_w = max([frag_px(c) for c in cells] or [0.0])
        frag_w = max(frag_w, frag_px(header_cells[ci]))
        floors.append(frag_w + 2)
        p90 = percentile([cell_px(c) for c in cells], 0.90)
        scores.append(max(p90, 8.0))

    total_w = table_width_pt(landscape) - ncols * COL_OVERHEAD - TABLE_SLACK
    spare = total_w - sum(floors)
    if spare < 0:
        # Weights are proportional so the engine will scale everything down
        # uniformly; fragments may slightly overpaint. Flag it.
        print(f"WARNING: column floors exceed table width "
              f"({sum(floors):.0f}pt > {total_w:.0f}pt) for headers "
              f"{tuple(th.get_text(strip=True) for th in header_cells)}",
              file=sys.stderr)
        return floors
    ssum = sum(scores) or 1.0
    return [f + spare * s / ssum for f, s in zip(floors, scores)]


def set_colgroup(table, soup, widths):
    old = table.find("colgroup")
    if old:
        old.decompose()
    colgroup = soup.new_tag("colgroup")
    for w in widths:
        col = soup.new_tag("col")
        col["style"] = f"width:{w:.1f}pt"
        colgroup.append(col)
    table.insert(0, colgroup)


# ---------------------------------------------------------------------------
# 3) Cell budget-splitting: no row may approach one page in height, because a
#    row taller than a page is silently truncated (with the rest of its table)
#    under col-width layout. Height is estimated per cell from its measured
#    text width (font-aware) against its column's content width; PACKING
#    accounts for ragged line ends from soft-break wrapping.

PACKING = 0.82
ROW_PAGE_FRACTION = 0.5     # split any cell estimated taller than this


def cell_char_budget(cell, col_width, landscape):
    """Character budget for one cell, or None if it needs no split."""
    text_len = len(cell.get_text())
    if text_len < 300:
        return None
    content_w = max(col_width, 12.0)  # style width IS the content width
    est_lines = cell_px(cell) / (content_w * PACKING)
    allowed = ROW_PAGE_FRACTION * page_content_height(landscape) / LINE_H
    if est_lines <= allowed:
        return None
    return max(300, int(text_len * allowed / est_lines))


def _split_cell_into_chunks(cell, max_chars):
    """Splits a <td>'s contents into chunks of <= max_chars text length,
    breaking at child-node boundaries (and at '. ' inside any single text
    node that itself exceeds the budget). Returns a list of node-lists."""
    nodes = list(cell.contents)
    chunks, cur, cur_len = [], [], 0
    for node in nodes:
        text = node.get_text() if hasattr(node, "get_text") else str(node)
        if isinstance(node, NavigableString) and len(text) > max_chars:
            # Oversized bare text node: split on sentence boundaries.
            parts, buf = [], ""
            for piece in str(node).split(". "):
                piece = piece + ". "
                if buf and len(buf) + len(piece) > max_chars:
                    parts.append(buf)
                    buf = piece
                else:
                    buf += piece
            if buf:
                parts.append(buf if str(node).rstrip().endswith(".") else buf.rstrip(". "))
            for part in parts:
                if cur_len + len(part) > max_chars and cur:
                    chunks.append(cur)
                    cur, cur_len = [], 0
                cur.append(NavigableString(part))
                cur_len += len(part)
            continue
        if cur_len + len(text) > max_chars and cur:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(node)
        cur_len += len(text)
    if cur:
        chunks.append(cur)
    return chunks


def split_overlong_cells(table, soup, widths, landscape):
    """For each body row, if any cell is estimated taller than half a page,
    keep the first chunk in place and move the rest into inserted continuation
    rows (first column carries an italic 'ID (cont'd)' marker, other cells
    empty)."""
    body = table.find("tbody") or table
    for tr in list(body.find_all("tr", recursive=False)):
        cells = tr.find_all("td", recursive=False)
        if not cells:
            continue
        for ci, cell in enumerate(cells):
            col_w = widths[ci] if ci < len(widths) else widths[-1]
            budget = cell_char_budget(cell, col_w, landscape)
            if budget is None:
                continue
            chunks = _split_cell_into_chunks(cell, budget)
            if len(chunks) <= 1:
                continue
            row_id = cells[0].get_text(strip=True)[:40]
            cell.clear()
            for node in chunks[0]:
                cell.append(node)
            anchor = tr
            for chunk in chunks[1:]:
                new_tr = soup.new_tag("tr")
                for i in range(len(cells)):
                    new_td = soup.new_tag("td")
                    if i == 0:
                        em = soup.new_tag("em")
                        em.string = f"{row_id} (cont'd)"
                        new_td.append(em)
                    elif i == ci:
                        for node in chunk:
                            new_td.append(node)
                    new_tr.append(new_td)
                anchor.insert_after(new_tr)
                anchor = new_tr


# ---------------------------------------------------------------------------
# 4) Header repetition: Story neither repeats <thead> across page breaks nor
#    reliably paginates a mid-page continuation table (a chunk starting
#    mid-page that must itself break entered an infinite placement loop --
#    observed both with plain sibling chunks and with page-break wrappers).
#    So Story is never allowed to break a chunk: rows are greedy-packed by
#    their MEASURED heights into chunks guaranteed to fit one page, each
#    pinned to a fresh page by a page-break div (honored on a div; ignored on
#    a table). One measurement pass + one verification pass.

# No single document should come anywhere near this many pages (the whole
# session-21 docset was ~410 for all 19 parts combined). Fail loudly if a
# layout bug ever loops.
MAX_PAGES_PER_DOC = 500

CHUNK_SLACK = 30.0     # margins/borders headroom per pinned chunk, pt
HEADER_H_FALLBACK = 18.0


# Consecutive placed pages that add no new element (while Story still reports
# more content) before the measurement is judged stalled. Real flow lands at
# least one id-bearing block per page and every row/header is < half a page, so
# a run this long with no progress is Story's mid-page table-break loop, not a
# genuinely tall element. A false positive is harmless — the fallback yields the
# same heights and equally usable page numbers — so this can be generous.
STALL_PAGES = 5

# Height of a measurement "tall page", in real pages. Placing the whole document
# onto pages this tall means Story almost never has to break a table across a
# page (the operation it loops on), while staying well under any renderer page-
# size limit. Documents taller than this still measure correctly (content spills
# onto a second tall page; see _measure_tall).
TALL_PAGE_MULT = 64


def measure_rows(html, css, mediabox, tmpdir, doc_name):
    """Record each element id's first page and its rect height.

    Normally Story is left to paginate at the real page size (_measure_paginated).
    But PyMuPDF's Story cannot reliably break a table across a page at certain
    vertical offsets: it stops making forward progress and would emit blank pages
    up to the guard limit (the same mid-page-break loop the assembly path avoids
    by pre-chunking tables — it can still bite the *measurement*, which hands
    Story a whole unchunked table). When that stall is detected, fall back to a
    stall-proof tall-page measurement that never asks Story to break a table."""
    result = _measure_paginated(html, css, mediabox, tmpdir, doc_name)
    if result is not None:
        return result
    print(f"WARNING: {doc_name}: Story stalled paginating a table during "
          f"measurement; using tall-page fallback.", file=sys.stderr)
    return _measure_tall(html, css, mediabox, tmpdir)


def _measure_paginated(html, css, mediabox, tmpdir, doc_name):
    """Real-page-size measurement: render to a throwaway PDF and record each id's
    first page and height. The draw() into a real DocumentWriter is REQUIRED:
    place() alone never advances the story. Returns (page_of, height_of), or None
    if Story stalled (STALL_PAGES pages with no forward progress) so measure_rows
    can fall back."""
    story = fitz.Story(html=html, user_css=css)
    out = tmpdir / "_measure.pdf"
    writer = fitz.DocumentWriter(str(out))
    where = mediabox + (PAGE_MARGIN, PAGE_MARGIN, -PAGE_MARGIN, -PAGE_MARGIN)
    page_of, height_of = {}, {}

    def cb(pos):
        if pos.id and (pos.open_close & 1) and pos.id not in page_of:
            page_of[pos.id] = pos.page_num
            r = getattr(pos, "rect", None)
            if r is not None:
                height_of[pos.id] = r[3] - r[1]

    more, page, stalled = True, 0, 0
    while more:
        prev = len(page_of)
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.element_positions(cb, {"page_num": page})
        story.draw(dev)
        writer.end_page()
        page += 1
        # Forward-progress guard. Only after the first element has landed: a
        # leading id-less cover/title page legitimately places no id.
        if more and page_of and len(page_of) == prev:
            stalled += 1
            if stalled >= STALL_PAGES:
                writer.close()
                return None
        else:
            stalled = 0
        if page > MAX_PAGES_PER_DOC:
            writer.close()
            raise RuntimeError(f"{doc_name}: measurement pass exceeded "
                               f"{MAX_PAGES_PER_DOC} pages")
    writer.close()
    return page_of, height_of


def _measure_tall(html, css, mediabox, tmpdir):
    """Stall-proof measurement. Placing the document onto very tall pages means
    Story almost never has to break a table across a page (the operation it loops
    on), so every element lands with a real, position-independent height (column
    widths are fixed, so these heights match the real layout exactly). Per-element
    page numbers are then reconstructed by greedy row-quantized pagination over
    those heights using the same per-page capacity the packer uses. The result
    matches real pagination up to an occasional 1-page offset between tables,
    which preserves every within-table span/keep decision the packer reads from
    it — and the packing loop re-measures the chunked document at the real page
    size next pass, where it no longer stalls, to converge exactly."""
    capacity = mediabox.height - 2 * PAGE_MARGIN - 2 * BODY_MARGIN
    tall = fitz.Rect(mediabox.x0, mediabox.y0,
                     mediabox.x1, mediabox.y0 + mediabox.height * TALL_PAGE_MULT)
    per_tall = tall.height - 2 * PAGE_MARGIN - 2 * BODY_MARGIN  # content per tall page
    story = fitz.Story(html=html, user_css=css)
    writer = fitz.DocumentWriter(str(tmpdir / "_measure_tall.pdf"))
    where = tall + (PAGE_MARGIN, PAGE_MARGIN, -PAGE_MARGIN, -PAGE_MARGIN)
    rec = {}  # id -> (absolute top y, absolute bottom y) down the whole document

    def cb(pos):
        if pos.id and (pos.open_close & 1) and pos.id not in rec:
            r = getattr(pos, "rect", None)
            if r is not None:
                base = pos.page_num * per_tall
                rec[pos.id] = (base + r[1], base + r[3])

    more, page = True, 0
    while more:
        dev = writer.begin_page(tall)
        more, _ = story.place(where)
        story.element_positions(cb, {"page_num": page})
        story.draw(dev)
        writer.end_page()
        page += 1
        if page > MAX_PAGES_PER_DOC:  # each tall page ~= TALL_PAGE_MULT real pages
            writer.close()
            raise RuntimeError("tall-page measurement overran")
    writer.close()

    height_of = {eid: bot - top for eid, (top, bot) in rec.items()}
    # Walk real flow elements in document order, greedily quantizing to pages.
    # Exclude any element that geometrically ENCLOSES another (a table container
    # spans all its rows); counting it would double the height of its rows.
    ids = list(rec)
    enclosing = set()
    for a in ids:
        at, ab = rec[a]
        for b in ids:
            if a is b:
                continue
            bt, bb = rec[b]
            if at <= bt and ab >= bb and (at < bt or ab > bb):
                enclosing.add(a)
                break
    flow = sorted((e for e in ids if e not in enclosing), key=lambda e: rec[e][0])
    page_of = {}
    page_num, page_top = 0, None
    for eid in flow:
        top, bot = rec[eid]
        if page_top is None:
            page_top = top
        elif bot - page_top > capacity:
            page_num += 1
            page_top = top
        page_of[eid] = page_num
    # Enclosing containers were skipped above; give each the page where its own
    # span begins so any lookup still resolves sensibly.
    for eid in enclosing:
        top = rec[eid][0]
        page_of[eid] = next((page_of[f] for f in flow if rec[f][0] >= top - 0.5),
                            page_of.get(flow[-1], 0) if flow else 0)
    return page_of, height_of


def _header_page(table, page_of):
    htr = table.find("thead").find("tr")
    return page_of.get(htr.get("id")) if htr is not None else None


def _spanning_tables(soup, page_of):
    """Tables needing repair: rows spread over multiple pages, OR an orphaned
    header (thead stranded at a page bottom with every row on the next page —
    the rows' page shows no header even though the tbody doesn't span)."""
    out = []
    for table in soup.find_all("table"):
        tbody = table.find("tbody")
        if tbody is None or table.find("thead") is None:
            continue
        rows = tbody.find_all("tr", recursive=False)
        if not rows:
            continue
        pages = {page_of.get(tr.get("id")) for tr in rows} - {None}
        if len(pages) > 1:
            out.append(table)
            continue
        hpage = _header_page(table, page_of)
        fpage = page_of.get(rows[0].get("id"))
        if hpage is not None and fpage is not None and hpage != fpage:
            out.append(table)
    return out


def repeat_headers_across_pages(soup, css, mediabox, tmpdir, doc_name, landscape):
    # Assign a unique id to every body row and header row (the <thead> element
    # itself is not reported by element_positions; its inner <tr> is).
    ti = 0
    for table in soup.find_all("table"):
        tbody = table.find("tbody")
        thead = table.find("thead")
        table["id"] = f"tbl{ti}"
        if thead is not None and thead.find("tr") is not None:
            thead.find("tr")["id"] = f"t{ti}h"
        if tbody is not None:
            for ri, tr in enumerate(tbody.find_all("tr", recursive=False)):
                tr["id"] = f"t{ti}r{ri}"
        ti += 1

    capacity = page_content_height(landscape)
    changed = False

    # Packing one table shifts everything after it, which can invalidate the
    # keep-boundaries of downstream tables computed from the same measurement,
    # so measure+pack until no table spans a page. Pinned chunks are stable
    # anchors (they always start a fresh page), so this converges fast.
    for _pass in range(MAX_CHUNK_ITERS):
        page_of, height_of = measure_rows(str(soup), css, mediabox, tmpdir, doc_name)
        spanning = _spanning_tables(soup, page_of)
        if not spanning:
            return changed
        for table in spanning:
            tbody = table.find("tbody")
            thead = table.find("thead")
            rows = tbody.find_all("tr", recursive=False)
            htr = thead.find("tr")
            header_h = height_of.get(htr.get("id") if htr else None, HEADER_H_FALLBACK)
            avail = capacity - header_h - CHUNK_SLACK
            # Rows that measured on the table's first page keep their place
            # (they provably fit under the existing header today); the rest
            # are packed into fresh full-page chunks by measured height. An
            # orphaned header (thead alone at a page bottom) keeps nothing —
            # every row is packed and the stranded header stub is removed.
            first_page = page_of.get(rows[0].get("id"))
            orphan = (_header_page(table, page_of) is not None
                      and first_page is not None
                      and _header_page(table, page_of) != first_page)
            keep, rest = [], []
            for tr in rows:
                p = page_of.get(tr.get("id"))
                if not orphan and not rest and p is not None and p == first_page:
                    keep.append(tr)
                else:
                    rest.append(tr)
            if not rest:
                continue
            changed = True
            groups, cur, cur_h = [], [], 0.0
            for tr in rest:
                h = height_of.get(tr.get("id"), LINE_H) + 1.0
                if cur and cur_h + h > avail:
                    groups.append(cur)
                    cur, cur_h = [], 0.0
                cur.append(tr)
                cur_h += h
            if cur:
                groups.append(cur)
            colgroup = table.find("colgroup")
            anchor = table
            for g in groups:
                nt = soup.new_tag("table")
                if colgroup is not None:
                    nt.append(copy.copy(colgroup))
                nthead = copy.copy(thead)
                ntr = nthead.find("tr")
                if ntr is not None and ntr.has_attr("id"):
                    del ntr["id"]  # ids must stay unique
                nt.append(nthead)
                nb = soup.new_tag("tbody")
                for tr in g:
                    nb.append(tr.extract())
                nt.append(nb)
                wrapper = soup.new_tag("div", style="page-break-before: always")
                # Tag non-orphan chunks with their source table id so paginate can
                # merge them back and re-pack from whole tables next pass (the
                # source survives; an orphan's source is decomposed, so its chunks
                # are left final/untagged).
                if not orphan:
                    wrapper["data-chunk"] = table.get("id", "")
                wrapper.append(nt)
                anchor.insert_after(wrapper)
                anchor = wrapper
            if orphan and not keep:
                table.decompose()  # header-only stub left at the page bottom
    print(f"WARNING: {doc_name}: table packing did not converge in "
          f"{MAX_CHUNK_ITERS} passes; some table pages may lack a repeated "
          f"header.", file=sys.stderr)
    return changed


# ---------------------------------------------------------------------------
# 5) Keep a section heading with its content: Story paginates greedily and will
#    strand a heading alone at a page bottom when the block that follows it
#    (paragraph, list, or — most visibly — a table) spills to the next page.
#    This measures each heading's page vs. the START page of its immediate
#    following block and, when the heading is stranded earlier, wraps it in a
#    page-break-before div so it moves onto the page where its content begins.
#    (Story reports a heading/paragraph/list by its own id but NOT a <table>'s;
#    for a table the first BODY row's page is used as the content-start page.)
#    Runs AFTER repeat_headers_across_pages (so it sees final table pagination),
#    and verifies+reverts every move so a heading is never left worse off (alone
#    on its own page) when its content genuinely cannot share the page.

HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]


def _next_block_element(node):
    """First following-sibling Tag of a heading (skips blank text nodes). A
    non-blank bare text node returns None — it flows on the heading's own line
    box, so it can't strand the heading."""
    for sib in node.next_siblings:
        if isinstance(sib, NavigableString):
            if str(sib).strip() == "":
                continue
            return None
        return sib
    return None


def _content_start_target(el):
    """Element whose measured page marks where `el`'s content effectively STARTS.
    Story does not report a <table>'s (or bare <div>'s) own id, so those map to a
    reportable descendant. For a table prefer the first BODY row over the header
    row: when a header squeezes onto the bottom of a page but the body spills
    over, repeat_headers_across_pages pulls the whole table (header included) to
    the next page — so the body row, not the header, predicts where the table
    will actually begin. A <div> (e.g. a repeat_headers page-break wrapper) is
    drilled the same way."""
    if el.name in ("table", "div"):
        tbody = el.find("tbody")
        if tbody is not None and tbody.find("tr") is not None:
            return tbody.find("tr")
        tr = el.find("tr")
        if tr is not None:
            return tr
        for d in el.descendants:
            if getattr(d, "name", None) in ("p", "li", "pre", "blockquote",
                                            "h1", "h2", "h3", "h4", "h5", "h6"):
                return d
        return None
    return el


def _is_pagebreak_div(el):
    return (getattr(el, "name", None) == "div"
            and "page-break-before" in (el.get("style") or ""))


def _sole_wrapped(h):
    """True when `h` is the only content of a page-break wrapper this pass
    created earlier (optionally alongside its carried <hr>). Such a heading's
    effective position in the flow is its WRAPPER's, so sibling walks must use
    the wrapper as the anchor."""
    p = h.parent
    if p is None or not _is_pagebreak_div(p):
        return False
    tags = [c for c in p.children if not isinstance(c, NavigableString)
            or str(c).strip() != ""]
    tags = [c for c in tags if getattr(c, "name", None) is not None]
    return all(c is h or c.name == "hr" for c in tags)


def _preceding_hr(h, anchor):
    """The <hr> separator immediately before the heading (skipping blank text) —
    inside its wrapper first, else before the anchor. It should travel with the
    heading when it moves; left behind it strands ALONE on an otherwise-empty
    page (observed: FRIS docset STR §4.4, a full blank-but-for-the-rule page)."""
    for node in ((h, anchor) if anchor is not h else (h,)):
        for sib in node.previous_siblings:
            if isinstance(sib, NavigableString):
                if str(sib).strip() == "":
                    continue
                return None
            return sib if sib.name == "hr" else None
    return None


def keep_headings_with_next(soup, css, mediabox, tmpdir, doc_name, landscape):
    """Move each stranded section heading onto the page where its content starts.
    Run this AFTER repeat_headers_across_pages so it sees the final table
    pagination (that pass's inserted page breaks are themselves a common cause of
    freshly-stranded headings).

    Every candidate move is applied, RE-MEASURED, and kept only if the heading
    now shares a page with its content — otherwise reverted. This is essential:
    when the following block is a table whose first row needs most of a page, a
    plain page-break can never co-locate them and would only strand the heading
    ALONE on its own page (worse than the original bottom-of-page orphan). Two
    move shapes: if the content is a force-broken chunk (a page-break-before div
    from repeat_headers), the heading is moved INSIDE it to ride the same break;
    otherwise the heading is wrapped in its own page-break-before div."""
    heads = soup.find_all(HEADING_TAGS)
    for i, h in enumerate(heads):
        if not h.get("id"):
            h["id"] = f"kh{i}"
    # `handled` = headings we've acted on (moved, or tried-and-reverted). A
    # heading is added ONLY when acted on — never merely for being un-stranded in
    # some pass — because a later move can strand a heading that was previously
    # fine (moving a sub-heading down strands its parent). Those must stay
    # eligible so the cascade is caught on a subsequent pass.
    handled = set()
    retried = set()
    changed = False
    tc = 0

    def _map_target(h):
        """(anchor, next-block, content-start-id) for a heading, or None.
        Assigns the content-start element a measurable id on demand."""
        nonlocal tc
        anchor = h.parent if _sole_wrapped(h) else h
        nxt = _next_block_element(anchor)
        if nxt is None:
            return None
        tgt = _content_start_target(nxt)
        if tgt is None:
            return None
        if not tgt.get("id"):
            tgt["id"] = f"kht{tc}"
            tc += 1
        return anchor, nxt, tgt["id"]

    def _requeue_restranded():
        """Second chance for already-handled headings: a LATER move can re-strand
        an earlier one (observed: FRIS docset STR §4.4 left heading-only on a
        page). Un-handle each currently-stranded handled heading ONCE — the
        `retried` set bounds this, so the pass still terminates."""
        stale = [h for h in soup.find_all(HEADING_TAGS)
                 if h.get("id") in handled and h.get("id") not in retried
                 and _map_target(h) is not None]
        if not stale:
            return False
        page_of, _ = measure_rows(str(soup), css, mediabox, tmpdir, doc_name)
        requeued = False
        for h in stale:
            mapped = _map_target(h)
            if mapped is None:
                continue
            anchor, _nxt, tid = mapped
            aid = anchor.get("id") or h.get("id")
            hp = page_of.get(aid, page_of.get(h.get("id")))
            tp = page_of.get(tid)
            if hp is not None and tp is not None and hp < tp:
                handled.discard(h["id"])
                retried.add(h["id"])
                requeued = True
        return requeued

    for _pass in range(3 * len(heads) + 5):
        # (Re)map each still-eligible heading to the element that marks where its
        # content starts, tagging that element with a measurable id.
        targets = {}  # heading id -> (anchor, next-block element, content-start id)
        for h in soup.find_all(HEADING_TAGS):
            hid = h.get("id")
            if hid in handled:
                continue
            mapped = _map_target(h)
            if mapped is None:
                handled.add(hid)           # nothing follows — nothing to do
                continue
            targets[hid] = mapped
        if not targets:
            if _requeue_restranded():
                continue
            return changed
        page_of, _ = measure_rows(str(soup), css, mediabox, tmpdir, doc_name)

        # First eligible heading that is stranded before its content. Un-stranded
        # headings are skipped (NOT marked handled) so a later move can revisit.
        cand = None
        for h in soup.find_all(HEADING_TAGS):
            hid = h.get("id")
            if hid not in targets:
                continue
            anchor, nxt, tid = targets[hid]
            hp, tp = page_of.get(hid), page_of.get(tid)
            if hp is not None and tp is not None and hp < tp:
                cand = (h, anchor, nxt, tid)
                break
        if cand is None:
            if _requeue_restranded():
                continue
            return changed

        h, anchor, nxt, tid = cand
        hr = _preceding_hr(h, anchor)
        old_wrapper = anchor if anchor is not h else None
        if _is_pagebreak_div(nxt):
            # Content is force-broken to a fresh page; ride along inside it so
            # the heading sits at that page's top. This co-locates by
            # construction (a heading is far shorter than a page), so keep it.
            # The preceding <hr> separator travels too — left behind it strands
            # alone on an otherwise-empty page.
            nxt.insert(0, h.extract())
            if hr is not None:
                nxt.insert(0, hr.extract())
            if old_wrapper is not None and old_wrapper.find(True) is None:
                old_wrapper.decompose()    # drop the emptied earlier wrapper
            handled.add(h["id"])
            changed = True
            continue

        if old_wrapper is not None:
            # Already on its own page break yet still ahead of its content — a
            # second break cannot help; leave it (each id is retried at most
            # once via `retried`).
            handled.add(h["id"])
            continue

        # Otherwise give the heading its own page break (separator riding
        # along), then verify it worked.
        wrapper = soup.new_tag("div")
        wrapper["style"] = "page-break-before: always"
        h.wrap(wrapper)
        if hr is not None:
            wrapper.insert(0, hr.extract())
        page_of2, _ = measure_rows(str(soup), css, mediabox, tmpdir, doc_name)
        if page_of2.get(h["id"]) != page_of2.get(tid):
            if hr is not None:
                wrapper.insert_before(hr.extract())   # restore the separator
            wrapper.unwrap()               # futile (content can't share the
            #                                page, e.g. a page-tall first row) —
            #                                leave the heading where it was.
        else:
            changed = True
        handled.add(h["id"])               # acted on either way; don't retry
    print(f"WARNING: {doc_name}: heading keep-with-next did not converge.",
          file=sys.stderr)
    return changed


# ---------------------------------------------------------------------------
# 6) Widow control for body paragraphs: Story splits a paragraph greedily and can
#    leave its final line or two alone at the top of the next page (a widow). The
#    last word of each paragraph is wrapped in a measurable <span>; if a paragraph
#    spills only a short tail (<= ~2 lines) AND the whole paragraph would then fit
#    on one page, it is pushed onto the next page so it stays intact. Every push is
#    re-measured and reverted if it fails to un-split the paragraph.

def _measure_pos(html, css, mediabox, tmpdir, doc_name):
    """Like measure_rows but also records each id's top (r[1]) and bottom (r[3]) y
    on the page it first opens. Returns (page_of, top_of, bot_of)."""
    story = fitz.Story(html=html, user_css=css)
    out = tmpdir / "_measure.pdf"
    writer = fitz.DocumentWriter(str(out))
    where = mediabox + (PAGE_MARGIN, PAGE_MARGIN, -PAGE_MARGIN, -PAGE_MARGIN)
    page_of, top_of, bot_of = {}, {}, {}

    def cb(pos):
        if pos.id and (pos.open_close & 1) and pos.id not in page_of:
            page_of[pos.id] = pos.page_num
            r = getattr(pos, "rect", None)
            if r is not None:
                top_of[pos.id] = r[1]
                bot_of[pos.id] = r[3]

    more, page = True, 0
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.element_positions(cb, {"page_num": page})
        story.draw(dev)
        writer.end_page()
        page += 1
        if page > MAX_PAGES_PER_DOC:
            writer.close()
            raise RuntimeError(f"{doc_name}: widow measurement exceeded "
                               f"{MAX_PAGES_PER_DOC} pages")
    writer.close()
    return page_of, top_of, bot_of


def _wrap_last_word(el, soup, span_id):
    """Wrap the last word of a block in <span id=span_id> so where it ENDS can be
    measured. Returns span_id, or None if there is nothing to wrap."""
    texts = [t for t in el.descendants
             if isinstance(t, NavigableString) and t.strip()]
    if not texts:
        return None
    last = texts[-1]
    s = str(last)
    stripped = s.rstrip()
    trail = s[len(stripped):]
    head, _, word = stripped.rpartition(" ")
    span = soup.new_tag("span", id=span_id)
    span.string = word + trail
    if head:
        new_head = NavigableString(head + " ")
        last.replace_with(new_head)
        new_head.insert_after(span)
    else:
        last.replace_with(span)
    return span_id


def _tag_widow_blocks(soup):
    """Tag every non-empty <p> and <li> with an id and wrap its last word in a
    <span id>. Done once, before the pagination loop.

    Returns (push_blocks, split_blocks):
      * push_blocks  -- <p> only, for fix_paragraph_widows' push-the-whole-block
        pass. Deliberately excludes <li>: pushing a list item onto the next page
        would strand it from its list, and that pass's behaviour is long-settled.
      * split_blocks -- <p> AND <li>, for the row-88(b) tail split, which does not
        move the block and so is safe on list items (the real-world (b) instances
        were page-tall bullets)."""
    push_blocks, split_blocks = [], []
    wi = 0
    for el in soup.find_all(["p", "li"]):
        if not el.get_text(strip=True):
            continue
        wid = _wrap_last_word(el, soup, f"ww{wi}")
        if wid is None:
            continue
        if not el.get("id"):
            el["id"] = f"wp{wi}"
        entry = (el["id"], wid)
        split_blocks.append(entry)
        if el.name == "p":
            push_blocks.append(entry)
        wi += 1
    return push_blocks, split_blocks


def fix_paragraph_widows(soup, blocks, css, mediabox, tmpdir, doc_name, landscape):
    if not blocks:
        return False
    capacity = page_content_height(landscape)
    changed = False
    handled = set()
    for _pass in range(len(blocks) + 5):
        page_of, top_of, bot_of = _measure_pos(
            str(soup), css, mediabox, tmpdir, doc_name)
        cand = None
        for pid, wid in blocks:
            if pid in handled:
                continue
            pp, wp = page_of.get(pid), page_of.get(wid)
            if pp is None or wp is None or wp <= pp:
                continue                       # doesn't span a page
            tail = bot_of.get(wid, CONTENT_TOP) - CONTENT_TOP
            first_portion = bot_of.get(pid, 0.0) - top_of.get(pid, 0.0)
            if tail > WIDOW_TAIL_MAX or first_portion + tail > capacity - CHUNK_SLACK:
                handled.add(pid)               # real multi-line split, or too tall
                continue
            cand = (pid, wid)
            break
        if cand is None:
            break
        pid, wid = cand
        el = soup.find(id=pid)
        if el is None:
            handled.add(pid)
            continue
        wrapper = soup.new_tag("div", style="page-break-before: always")
        el.wrap(wrapper)
        page_of2, _, _ = _measure_pos(str(soup), css, mediabox, tmpdir, doc_name)
        if page_of2.get(pid) != page_of2.get(wid):
            wrapper.unwrap()                   # still split — revert
        else:
            changed = True
        handled.add(pid)
    return changed


def body_text_width(s):
    """Width of a string at BODY font size (text_width() measures at table size)."""
    try:
        return fitz.get_text_length(s, fontname="helv", fontsize=BODY_FONT_SIZE)
    except Exception:
        return len(s) * CHAR_W * (BODY_FONT_SIZE / TABLE_FONT_SIZE)


def _tail_words_for_lines(words, content_w, lines=SPLIT_TARGET_LINES):
    """How many trailing words are needed to occupy >= `lines` lines. Accumulates
    from the end until the measured width exceeds the target, so the continuation
    is guaranteed to wrap rather than sit as another lone line."""
    target = lines * content_w * 0.98      # 2% slack: wrapping is never perfect
    used, n = 0.0, 0
    for w in reversed(words):
        used += body_text_width(w + " ")
        n += 1
        if used >= target or n >= SPLIT_MAX_MOVE_WORDS:
            break
    return n


def _split_block_tail(root, pid, wid, n_words, cont_id, src_wid):
    """In the tree `root`, move the last `n_words` words of block `pid` into a
    continuation pinned to the next page, then re-wrap the SOURCE block's new last
    word in <span id=src_wid> so the remainder stays widow-measurable. Returns the
    continuation tag, or None when the tail is not plain text or is too short.

    Re-tagging the source is not cosmetic: the original last-word span travels into
    the continuation, so without it the shortened source becomes invisible to widow
    detection — which is how the first cut of this pass silently relocated a widow
    instead of removing it (n=312 in the synthetic sweep).

    Shape depends on the block: a <p> gets a SIBLING <p>; an <li> gets a NESTED
    <div> (a sibling <li> would draw a second bullet). ZWSP-safe by construction:
    split points come from str.split(), and U+200B is not Python whitespace, so a
    soft-broken token can never be cut at its invisible break — the s57 attempt's
    mangled joins came from splitting without that guarantee."""
    el, span = root.find(id=pid), root.find(id=wid)
    if el is None or span is None:
        return None
    prev = span.previous_sibling
    if not isinstance(prev, NavigableString):
        return None                       # inline markup at the tail -- leave alone
    words = str(prev).split()
    if len(words) < n_words + SPLIT_MIN_KEPT_WORDS:
        return None
    keep, move = words[:len(words) - n_words], words[len(words) - n_words:]

    prev.replace_with(NavigableString(" ".join(keep) + " "))
    cont = root.new_tag("div" if el.name == "li" else "p", id=cont_id)
    cont["style"] = "page-break-before: always; margin-top: 0"
    cont.append(NavigableString(" ".join(move) + " "))
    cont.append(span.extract())
    # Re-tag the source BEFORE attaching the continuation. For an <li> the
    # continuation nests INSIDE the block, so doing this afterwards would wrap a
    # word of the continuation and make the source look like it still spans.
    _wrap_last_word(el, root, src_wid)
    if el.name == "li":
        el.append(cont)                   # nested: stays inside the bullet
    else:
        el.insert_after(cont)
    return cont


def split_tall_paragraph_widows(soup, blocks, css, mediabox, tmpdir, doc_name,
                                landscape, handled):
    """Row-88(b): a block TALLER than one page cannot be pushed whole -- so
    fix_paragraph_widows correctly declines it -- and Story's greedy split can then
    leave its final line alone at the top of the next page. Donate ~2 lines' worth
    of trailing words to a continuation pinned to that page, so it opens with two
    lines instead of one.

    Runs as a convergence operation INSIDE paginate's settle loop. That is the whole
    difference from the reverted s57 attempt, which ran once after the layout had
    settled: a split shifts everything downstream, and only a pass that is followed
    by another global re-measure can catch the widow it may itself create. Here the
    loop re-runs chunking, heading-keep and both widow passes afterwards.

    Each split is measured and reverted unless the continuation really carries >= 2
    lines. `handled` is shared with the caller so a block is attempted only once per
    document -- splits cannot oscillate."""
    if not blocks:
        return False
    capacity = page_content_height(landscape)
    content_w = table_width_pt(landscape)
    page_of, top_of, bot_of = _measure_pos(str(soup), css, mediabox, tmpdir, doc_name)

    for pid, wid in list(blocks):
        if pid in handled:
            continue
        pp, wp = page_of.get(pid), page_of.get(wid)
        if pp is None or wp is None or wp <= pp:
            continue                                   # doesn't span a page
        tail = bot_of.get(wid, CONTENT_TOP) - CONTENT_TOP
        first_portion = bot_of.get(pid, 0.0) - top_of.get(pid, 0.0)
        if tail > WIDOW_TAIL_MAX:
            continue                                   # real multi-line spill, fine
        el, span = soup.find(id=pid), soup.find(id=wid)
        if el is None or span is None:
            handled.add(pid)
            continue
        # Only blocks TALLER than a page are ours: a block that fits could be moved
        # whole, and splitting one that fits is both uglier and — measured — a net
        # loss. Splitting every short-tailed <li> regardless of height was tried
        # (2026-08-01) to reach a pushable <li> widow that no pass owns; it fired on
        # many list items, grew the composite 269 -> 271 pages and took its
        # lone-line pages from 1 to 3, so it is deliberately NOT done. That
        # remaining case is recorded as row 88(d), not fixed here.
        if first_portion + tail <= capacity - CHUNK_SLACK:
            continue                                   # pushable: not our case
        prev = span.previous_sibling
        if not isinstance(prev, NavigableString):
            handled.add(pid)
            continue

        n = _tail_words_for_lines(str(prev).split(), content_w)
        cont_id, src_wid = f"wc{pid}", f"wr{pid}"
        handled.add(pid)                               # one attempt per block

        # Try it on a COPY first. Accept/revert on a text split is not a wrap/unwrap
        # like the other passes, and the acceptance test has to see the WHOLE
        # re-measured document, so the trial tree is both simpler and safer.
        trial = copy.copy(soup)
        if _split_block_tail(trial, pid, wid, n, cont_id, src_wid) is None:
            continue
        page2, top2, bot2 = _measure_pos(str(trial), css, mediabox, tmpdir, doc_name)

        cont_h = bot2.get(cont_id, 0.0) - top2.get(cont_id, 0.0)
        if cont_h < (SPLIT_TARGET_LINES - 0.2) * BODY_LINE_H:
            continue                                   # didn't buy a second line
        # ... and the shortened source must not have inherited the widow.
        sp, sw = page2.get(pid), page2.get(src_wid)
        if sp is not None and sw is not None and sw > sp:
            if bot2.get(src_wid, CONTENT_TOP) - CONTENT_TOP <= WIDOW_TAIL_MAX:
                continue                               # widow merely relocated
        if _split_block_tail(soup, pid, wid, n, cont_id, src_wid) is None:
            continue
        blocks.append((cont_id, wid))                  # continuation stays managed
        blocks.append((pid, src_wid))                  # so does the shortened source
        return True                                    # re-settle before the next
    return False


def _merge_chunks(soup):
    """Undo non-orphan table chunking from a prior repeat_headers pass: move each
    chunk's rows back into its source table's tbody and drop the wrapper, so the
    next pass re-packs from whole tables. (Re-chunking an already-chunked table is
    what strands rows one-per-page: each pass peels a single-row chunk that never
    recombines with the earlier ones.) A heading that keep_headings tucked into a
    chunk is lifted out but kept on its forced page via its own page-break div, so
    its placement survives the round-trip. Returns whether anything was merged."""
    merged = False
    for wrap in soup.find_all("div", attrs={"data-chunk": True}):
        src = soup.find("table", id=wrap.get("data-chunk"))
        chunk = wrap.find("table")
        if src is None or chunk is None:
            continue
        for child in list(wrap.children):
            if getattr(child, "name", None) == "table":
                continue
            if getattr(child, "name", None) is None and not str(child).strip():
                continue
            pb = soup.new_tag("div", style="page-break-before: always")
            pb.append(child.extract())
            wrap.insert_before(pb)
        src_body, cbody = src.find("tbody"), chunk.find("tbody")
        if src_body is not None and cbody is not None:
            for tr in cbody.find_all("tr", recursive=False):
                src_body.append(tr.extract())
        wrap.decompose()
        merged = True
    return merged


# ---------------------------------------------------------------------------
# 7) Sparse-page packing: repeat_headers pins every table-continuation chunk (and
#    a short section table forced fresh by a neighbour's pin) to a NEW page with
#    `page-break-before: always`, so a small chunk can sit nearly alone on its
#    page. This pulls such a chunk back onto the previous page when it PROVABLY
#    fits there: drop the forced break, re-measure, and keep the change only if no
#    table row then spans a page (else revert). The repeated header rides with the
#    chunk, so it simply reappears mid-page. Verification-based like the widow
#    pass, and safe against Story's mid-page-break placement loop — a runaway
#    re-measure is caught and treated as "does not fit". Runs LAST, after the
#    chunk/heading/widow layout has settled, so it only tightens whitespace.

def pack_sparse_pages(soup, css, mediabox, tmpdir, doc_name, landscape):
    capacity = page_content_height(landscape)
    changed = False
    wrappers = [w for w in soup.find_all("div")
                if "page-break-before" in (w.get("style") or "")
                and w.find("table") is not None]
    for w in wrappers:
        ids = [tr.get("id") for tr in w.find_all("tr") if tr.get("id")]
        if not ids:
            continue
        page_of, top_of, bot_of = _measure_pos(str(soup), css, mediabox, tmpdir, doc_name)
        if any(i not in page_of for i in ids):
            continue
        my_page = min(page_of[i] for i in ids)
        if my_page == 0:
            continue
        prev_bottoms = [bot_of[i] for i, pg in page_of.items()
                        if pg == my_page - 1 and i in bot_of]
        if not prev_bottoms:
            continue
        used = max(prev_bottoms) - CONTENT_TOP
        have_top = [top_of[i] for i in ids if i in top_of]
        have_bot = [bot_of[i] for i in ids if i in bot_of]
        if not have_top or not have_bot:
            continue
        chunk_h = max(have_bot) - min(have_top)
        # the cloned header carries no id, so pad for it plus the pin slack
        need = chunk_h + HEADER_H_FALLBACK + CHUNK_SLACK
        if used + need > capacity:
            continue                       # won't fit on the previous page
        orig = w["style"]
        rest = "; ".join(s.strip() for s in orig.split(";")
                         if s.strip() and "page-break-before" not in s)
        if rest:
            w["style"] = rest
        else:
            del w["style"]
        try:
            pg2, _ = measure_rows(str(soup), css, mediabox, tmpdir, doc_name)
            bad = bool(_spanning_tables(soup, pg2))
        except RuntimeError:
            bad = True                     # mid-page break loop -> it did not fit
        if bad:
            w["style"] = orig              # revert
        else:
            changed = True
    return changed


# ---------------------------------------------------------------------------
# 8) Tail-pull: a near-empty page arises when a section's LAST short block(s)
#    land alone on a page because everything after them is force-broken to a
#    fresh page (observed in the FRIS docset: an SRS page holding one
#    "Qualification:" line; an STR page holding just "None."). For each
#    SECTION-START page-break wrapper (first child a heading, or a separator
#    then a heading — never a table-continuation chunk, which would interleave
#    text into a split table), move up to two short immediately-preceding
#    blocks INSIDE the wrapper, before its content, so they open the next page
#    instead. Any heading this re-strands is pulled along by the
#    keep-headings requeue on the next paginate iteration. Verification-based:
#    each move is kept only if the document's rendered page count DECREASES.

TAIL_TAGS = ("p", "ul", "ol", "pre", "blockquote")
TAIL_MAX_CHARS = 300


def _render_page_count(html, css, mediabox, tmpdir):
    story = fitz.Story(html=html, user_css=css)
    out = tmpdir / "_measure_pages.pdf"
    writer = fitz.DocumentWriter(str(out))
    where = mediabox + (PAGE_MARGIN, PAGE_MARGIN, -PAGE_MARGIN, -PAGE_MARGIN)
    more, pages = True, 0
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
        pages += 1
        if pages > 2000:                   # runaway guard
            break
    writer.close()
    return pages


def _first_content_child(w):
    for c in w.children:
        if isinstance(c, NavigableString):
            if str(c).strip() == "":
                continue
            return None
        return c
    return None


def _is_section_start_wrapper(w):
    first = _first_content_child(w)
    if first is None:
        return False
    if first.name == "hr":
        nxt = _next_block_element(first)
        return getattr(nxt, "name", None) in HEADING_TAGS
    return first.name in HEADING_TAGS


def _prev_content_sibling(node):
    for sib in node.previous_siblings:
        if isinstance(sib, NavigableString):
            if str(sib).strip() == "":
                continue
            return None
        return sib
    return None


def pull_short_tails(soup, css, mediabox, tmpdir, doc_name, landscape):
    changed = False
    wrappers = [w for w in soup.find_all("div")
                if "page-break-before" in (w.get("style") or "")
                and _is_section_start_wrapper(w)]
    for w in wrappers:
        # Collect up to 2 short blocks sitting immediately before the wrapper.
        tail = []
        node = w
        while len(tail) < 2:
            prev = _prev_content_sibling(node)
            if prev is None or prev.name not in TAIL_TAGS:
                break
            if len(prev.get_text(strip=True)) > TAIL_MAX_CHARS:
                break
            tail.insert(0, prev)
            node = prev
        if not tail:
            continue
        if _prev_content_sibling(tail[0]) is None:
            continue                       # the "tail" IS the whole section
        # Smallest move first: pulling more blocks than needed can overflow the
        # target page (net zero pages -> futile). Try just the last block, then
        # the pair.
        n_before = _render_page_count(str(soup), css, mediabox, tmpdir)
        moved = False
        for k in range(1, len(tail) + 1):
            attempt = tail[-k:]
            for el in reversed(attempt):
                w.insert(0, el.extract())
            n_after = _render_page_count(str(soup), css, mediabox, tmpdir)
            if n_after < n_before:
                moved = True
                break
            for el in attempt:             # no page saved — put them back
                w.insert_before(el.extract())
        if moved:
            changed = True
    return changed


def paginate(soup, css, mediabox, tmpdir, doc_name, landscape):
    """Settle table chunking, heading-keep, and widow reflow together. Each pass
    can invalidate the others' measurements (a heading/widow page break shifts a
    table so its rows re-span; table chunks shift a heading or paragraph so it
    strands), so iterate: reset table chunking, re-pack every spanning table whole
    (repeated header on each continuation), then re-place stranded headings and
    widowed paragraphs. Converges when neither headings nor widows move — at which
    point the (deterministic) table packing is stable too."""
    push_blocks, split_blocks = _tag_widow_blocks(soup)
    split_handled = set()
    for _ in range(MAX_PAGINATE_ITERS):
        _merge_chunks(soup)
        repeat_headers_across_pages(soup, css, mediabox, tmpdir, doc_name, landscape)
        c2 = keep_headings_with_next(soup, css, mediabox, tmpdir, doc_name, landscape)
        c3 = fix_paragraph_widows(soup, push_blocks, css, mediabox, tmpdir, doc_name, landscape)
        # Row-88(b): only once the pushable widows have settled, so a block is
        # split only when pushing genuinely cannot fix it.
        c4 = split_tall_paragraph_widows(soup, split_blocks, css, mediabox, tmpdir,
                                         doc_name, landscape, split_handled)
        if not (c2 or c3 or c4):
            _pack_and_settle(soup, css, mediabox, tmpdir, doc_name, landscape,
                             push_blocks, split_blocks, split_handled)
            return
    print(f"WARNING: {doc_name}: pagination did not converge in "
          f"{MAX_PAGINATE_ITERS} passes", file=sys.stderr)
    _pack_and_settle(soup, css, mediabox, tmpdir, doc_name, landscape,
                     push_blocks, split_blocks, split_handled)


def _pack_and_settle(soup, css, mediabox, tmpdir, doc_name, landscape,
                     push_blocks=(), split_blocks=(), split_handled=None):
    """pack_sparse_pages tightens whitespace by pulling pinned chunks back up —
    which shifts everything after them and can strand a section tail (or a
    heading) that the settled layout had placed safely. Run the tail-pull and a
    heading re-check AFTER packing, in a short bounded settle loop.

    Row-88(d): the WIDOW passes belong in that loop too. Packing and tail-pulling
    move content after the main loop has converged, so they can re-widow a
    paragraph the widow pass had already fixed — and with no widow pass afterwards
    it survived into the final render (CTR §6.6 was widowed this way at p140 for
    several builds). Both widow passes are re-run here for the same reason the
    heading check is."""
    if split_handled is None:
        split_handled = set()
    pack_sparse_pages(soup, css, mediabox, tmpdir, doc_name, landscape)
    for _ in range(3):
        t = pull_short_tails(soup, css, mediabox, tmpdir, doc_name, landscape)
        k = keep_headings_with_next(soup, css, mediabox, tmpdir, doc_name, landscape)
        # Row-88(d): the table-tail balancer belongs INSIDE this loop, ahead of the
        # widow passes. Its own docstring reasoned only about the donor SHRINKING,
        # but the tail chunk GROWS by the stolen row, so everything after the table
        # shifts down — which is what re-widowed the CTR §6.6 paragraph after the
        # widow passes had already settled it. It converges on its own (a tail with
        # two rows is no longer a candidate).
        b = balance_table_tail_widows(soup, css, mediabox, tmpdir, doc_name, landscape)
        w = fix_paragraph_widows(soup, push_blocks, css, mediabox, tmpdir,
                                 doc_name, landscape)
        s = split_tall_paragraph_widows(soup, split_blocks, css, mediabox, tmpdir,
                                        doc_name, landscape, split_handled)
        if not (t or k or b or w or s):
            break
    # Row-88(b) is handled by split_tall_paragraph_widows INSIDE the paginate
    # settle loop, not here — a post-settle bolt-on cannot re-verify globally,
    # which is exactly why the s57 attempt created widows downstream.


def balance_table_tail_widows(soup, css, mediabox, tmpdir, doc_name, landscape):
    """Row-88(a): a table whose FINAL chunk carries a single body row renders as
    one lonely row under a dutifully-repeated header. Steal the DONOR (previous)
    fragment's last row so the tail page carries two rows; measure and revert if
    the tail chunk then spans pages (a near-page-tall stolen row).

    Row-88(d) correction: an earlier version of this docstring claimed nothing
    downstream could be invalidated, reasoning only about the donor SHRINKING. The
    tail chunk also GROWS by the stolen row, so content following the table shifts
    down by a row — enough to re-widow the next paragraph. It therefore runs INSIDE
    _pack_and_settle's loop, ahead of the widow passes, rather than after them."""
    changed = False
    families = {}
    for wrapper in soup.find_all("div", attrs={"data-chunk": True}):
        families.setdefault(wrapper["data-chunk"], []).append(wrapper)
    for src_id, wrappers in families.items():
        last_tbody = wrappers[-1].find("tbody")
        if last_tbody is None:
            continue
        last_rows = last_tbody.find_all("tr", recursive=False)
        if len(last_rows) != 1:
            continue
        if len(wrappers) >= 2:
            donor_tbody = wrappers[-2].find("tbody")
        else:
            src = soup.find("table", id=src_id)
            donor_tbody = src.find("tbody") if src else None
        if donor_tbody is None:
            continue
        donor_rows = donor_tbody.find_all("tr", recursive=False)
        if len(donor_rows) < 3:
            continue  # stealing would just move the widow to the donor
        moved = donor_rows[-1].extract()
        last_tbody.insert(0, moved)
        page_of, _ = measure_rows(str(soup), css, mediabox, tmpdir, doc_name)
        p_moved = page_of.get(moved.get("id"))
        p_widow = page_of.get(last_rows[0].get("id"))
        if p_moved is None or p_widow is None or p_moved != p_widow:
            donor_tbody.append(moved.extract())  # revert: tail no longer one page
        else:
            changed = True
    return changed


# ---------------------------------------------------------------------------
# Verification: silent row truncation is the failure mode of this layout
# engine, so every rendered part is checked against canary needles (the first
# cell of every body row).

_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
              "ﬃ": "ffi", "ﬄ": "ffl"}


def _normalize(s):
    # Whitespace-free comparison form: a ZWSP soft break that actually wraps
    # comes back from text extraction as a line break, so any whitespace
    # difference between source and rendered text is layout, not loss.
    for k, v in _LIGATURES.items():
        s = s.replace(k, v)
    return "".join(s.replace(ZWSP, "").split())


def collect_row_needles(soup):
    """Canaries against silent truncation: the head of every row's first cell
    (a lost row loses it) and the tail of every long cell (a clipped over-tall
    cell loses its tail but keeps the row's first cell)."""
    needles = []
    for table in soup.find_all("table"):
        tbody = table.find("tbody")
        if not tbody:
            continue
        for tr in tbody.find_all("tr", recursive=False):
            tds = tr.find_all("td", recursive=False)
            if not tds:
                continue
            t = _normalize(tds[0].get_text())[:24].strip()
            if len(t) >= 4:
                needles.append(t)
            for td in tds:
                full = _normalize(td.get_text())
                if len(full) >= 120:
                    needles.append(full[-24:])
    return needles


def verify_no_lost_rows(pdf_path, needles, doc_name):
    doc = fitz.open(str(pdf_path))
    text = _normalize(" ".join(page.get_text() for page in doc))
    doc.close()
    missing = [n for n in needles if n not in text]
    if missing:
        raise RuntimeError(
            f"{doc_name}: {len(missing)} table row(s) missing from the "
            f"rendered PDF (silent truncation?): {missing[:5]!r}...")


def verify_margins(pdf_path, doc_name, tolerance=8):
    doc = fitz.open(str(pdf_path))
    worst = 0.0
    for page in doc:
        limit = page.rect.width - PAGE_MARGIN + tolerance
        for w in page.get_text("words"):
            if w[2] > limit:
                worst = max(worst, w[2] - (page.rect.width - PAGE_MARGIN))
    doc.close()
    if worst:
        print(f"WARNING: {doc_name}: text extends {worst:.1f}pt past the "
              f"right margin", file=sys.stderr)


# ---------------------------------------------------------------------------

def prepare_tables(soup, landscape):
    for table in soup.find_all("table"):
        for cell in table.find_all(["td", "th"]):
            inject_soft_breaks(cell)
        widths = compute_column_weights(table, landscape)
        if widths is None:
            continue
        set_colgroup(table, soup, widths)
        split_overlong_cells(table, soup, widths, landscape)


def render_story_to_pdf(html, css, mediabox, out_path, doc_name="?"):
    story = fitz.Story(html=html, user_css=css)
    writer = fitz.DocumentWriter(str(out_path))
    where = mediabox + (PAGE_MARGIN, PAGE_MARGIN, -PAGE_MARGIN, -PAGE_MARGIN)
    more = True
    pages = 0
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
        pages += 1
        if pages > MAX_PAGES_PER_DOC:
            writer.close()
            raise RuntimeError(
                f"{doc_name}: exceeded {MAX_PAGES_PER_DOC} pages — layout loop?")
    writer.close()


def toc_line(entry):
    # Must match exactly what's rendered in the TOC <li> (single spaces only --
    # HTML collapses repeated whitespace, so search_for() on the rendered PDF
    # text would miss a line built with double spaces/em dashes).
    line = f"{entry['num']}. {entry['full']} ({entry['acr']})"
    if entry.get("page") is not None:
        line += f" - p. {entry['page']}"
    return line


def toc_search_snippet(entry):
    # search_for() does exact text matching against the PDF's extracted text,
    # which uses ligature glyphs (e.g. "fi" -> single U+FB01 character) for
    # titles like "Specification"/"Configuration" -- a plain "fi" substring
    # never matches those. Acronyms never contain "fi", so anchor the link on
    # the ligature-free "(ACR) - p. N" tail instead of the full title line.
    return f"({entry['acr']}) - p. {entry['page']}"


def build_toc_html(leaf_entries, break_before_parts=()):
    """break_before_parts: part titles that must start a fresh TOC page — fed by
    the front-matter orphan pass (a part <h3> last on its page with its entries
    overleaf; backlog row 88 class (c))."""
    rows = []
    last_part = None
    for entry in leaf_entries:
        if entry["part_title"] != last_part:
            if last_part is not None:
                rows.append("</ul>")
            brk = (' style="page-break-before: always;"'
                   if entry["part_title"] in break_before_parts else "")
            # list-style none: every entry already carries its section number
            # ("1. Title (ACR)"), so a bullet glyph in front is redundant.
            rows.append(f"<h3{brk}>{entry['part_title']}</h3>"
                        f'<ul style="list-style-type: none;">')
            last_part = entry["part_title"]
        rows.append(f"<li>{toc_line(entry)}</li>")
    if last_part is not None:
        rows.append("</ul>")
    return "".join(rows)


def _toc_part_orphan_titles(pdf_path, part_titles):
    """Part headings that render as the LAST text line of a non-final
    front-matter page — their entries sit overleaf, the row-88(c) orphan.
    The cover/TOC html never runs the body keep-heading pass, so this is its
    own verification-based equivalent."""
    doc = fitz.open(str(pdf_path))
    orphans = []
    for pno in range(doc.page_count):
        lines = [ln.strip() for ln in doc[pno].get_text().splitlines() if ln.strip()]
        if lines and pno < doc.page_count - 1 and lines[-1] in part_titles:
            orphans.append(lines[-1])
    doc.close()
    return orphans


def build_cover_html(toc_html, title, subtitle=None, cover_lines=()):
    import html as _html
    sub = f"<h2>{_html.escape(subtitle)}</h2>" if subtitle else ""
    lines = "".join(f"<p>{_html.escape(str(l))}</p>" for l in (cover_lines or ()))
    return f"""
    <html><body>
    <div>
    <h1>{_html.escape(title)}</h1>
    {sub}
    {lines}
    </div>
    <div style="page-break-before: always;">
    <h2>Table of Contents</h2>
    {toc_html}
    </div>
    </body></html>
    """


def add_toc_links(pdf_path, leaf_entries, front_matter_pages):
    """Adds clickable GoTo link annotations over each TOC line, plus a PDF
    bookmark outline per entry, so the TOC is navigable both inline and via
    the viewer's sidebar."""
    doc = fitz.open(str(pdf_path))
    toc_outline = []
    for entry in leaf_entries:
        target_index = entry["page"] - 1
        # Prefer matching the full line (bigger clickable area); some titles
        # contain an "fi"/"fl" ligature glyph that breaks exact-text matching,
        # so fall back to the ligature-free "(ACR) - p. N" tail.
        candidates = [toc_line(entry), toc_search_snippet(entry)]
        found = False
        for pno in range(front_matter_pages):
            page = doc[pno]
            for candidate in candidates:
                rects = page.search_for(candidate)
                if rects:
                    for rect in rects:
                        page.insert_link({
                            "kind": fitz.LINK_GOTO,
                            "page": target_index,
                            "to": fitz.Point(0, 0),
                            "from": rect,
                        })
                        found = True
                    break
        if not found:
            print(f"WARNING: could not locate TOC line for link: {toc_line(entry)!r}", file=sys.stderr)
        toc_outline.append([1, f"{entry['num']}. {entry['full']} ({entry['acr']})", entry["page"]])
    doc.set_toc(toc_outline)
    tmp_out = pdf_path.with_suffix(".linked.pdf")
    doc.save(str(tmp_out), garbage=3, deflate=True)
    doc.close()
    tmp_out.replace(pdf_path)


# ===========================================================================
# Public API
# ===========================================================================

def render_markdown_file(src_md, out_pdf, *, landscape=False, base_css=None):
    """Render ONE Markdown file to a standalone PDF (same table/heading engine,
    no cover/TOC). Returns the page count."""
    src_md, out_pdf = Path(src_md), Path(out_pdf)
    css = (base_css or BASE_CSS).replace(
        "{SIZE}", "Letter landscape" if landscape else "Letter")
    mediabox = fitz.paper_rect("letter-l" if landscape else "letter")
    raw = src_md.read_text(encoding="utf-8")
    full_html = f"<html><body><div>{md_to_html(raw)}</div></body></html>"
    name = src_md.name
    with tempfile.TemporaryDirectory(prefix="mdpdf_",
                                     ignore_cleanup_errors=True) as tmp:
        tmpdir = Path(tmp)
        soup = BeautifulSoup(full_html, "html.parser")
        prepare_tables(soup, landscape)
        needles = collect_row_needles(soup)
        paginate(soup, css, mediabox, tmpdir, name, landscape)
        render_story_to_pdf(str(soup), css, mediabox, out_pdf, doc_name=name)
        verify_no_lost_rows(out_pdf, needles, name)
        verify_margins(out_pdf, name)
    return len(PdfReader(str(out_pdf)).pages)


def build_docset(structure, docs_dir, out_path, *, title,
                 subtitle=None, cover_lines=(), base_css=None):
    """Assemble `structure` (list of (part_title, [leaf, ...])) into one PDF at
    `out_path`, with a cover, a linked TOC, and per-part section covers.
    `docs_dir` is the base directory leaf filenames resolve against. Returns the
    total page count."""
    docs_dir, out_path = Path(docs_dir), Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # ignore_cleanup_errors: on Windows a raised layout error can leave
    # _measure.pdf briefly locked; don't mask the real error with the cleanup.
    with tempfile.TemporaryDirectory(prefix="docset_",
                                     ignore_cleanup_errors=True) as tmp:
        return _build(Path(tmp), structure, docs_dir, out_path,
                      title, subtitle, cover_lines, base_css or BASE_CSS)


def _build(tmpdir, structure, docs_dir, out_path, title, subtitle,
           cover_lines, css_base):
    portrait_box = fitz.paper_rect("letter")
    landscape_box = fitz.paper_rect("letter-l")
    css_portrait = css_base.replace("{SIZE}", "Letter")

    def cover_pdf_for(part_title, acr, full):
        return f"""<div>
              <div class="cover-part">{part_title}</div>
              <div class="cover-acronym">{acr}</div>
              <div class="cover-full">{full}</div>
              <hr/>
            </div>"""

    # Render every body part first so each one's page count is known before
    # the Table of Contents (which needs real page numbers) is built.
    leaf_entries = []
    idx = 1
    for part_title, docs in structure:
        for num, acr, fname, full, landscape in docs:
            fpath = docs_dir / fname
            if not fpath.exists():
                print(f"WARNING: missing {fpath}", file=sys.stderr)
                continue
            mediabox = landscape_box if landscape else portrait_box
            leaf_out = tmpdir / f"{idx:02d}_{acr}.pdf"
            css = css_base.replace(
                "{SIZE}", "Letter landscape" if landscape else "Letter")

            if fname.lower().endswith(".pdf"):
                # Pre-rendered PDF leaf: render a cover page (section header +
                # acronym + title, so it gets a TOC entry) and concatenate it
                # in front of the supplied PDF. No markdown/table processing.
                cover_html = f"<html><body>{cover_pdf_for(part_title, acr, full)}</body></html>"
                cover_only = tmpdir / f"{idx:02d}_{acr}_cover.pdf"
                render_story_to_pdf(cover_html, css, mediabox, cover_only, doc_name=acr)
                w = PdfWriter()
                for pf in (cover_only, fpath):
                    for page in PdfReader(str(pf)).pages:
                        w.add_page(page)
                with open(leaf_out, "wb") as f:
                    w.write(f)
                leaf_entries.append({
                    "part_title": part_title, "num": num, "acr": acr, "full": full,
                    "path": leaf_out, "page": None,
                })
                idx += 1
                continue

            raw = fpath.read_text(encoding="utf-8")
            cover = cover_pdf_for(part_title, acr, full)
            full_html = f"<html><body>{cover}<div>{md_to_html(raw)}</div></body></html>"

            soup = BeautifulSoup(full_html, "html.parser")
            prepare_tables(soup, landscape)
            needles = collect_row_needles(soup)
            paginate(soup, css, mediabox, tmpdir, acr, landscape)

            render_story_to_pdf(str(soup), css, mediabox, leaf_out, doc_name=acr)
            verify_no_lost_rows(leaf_out, needles, acr)
            verify_margins(leaf_out, acr)
            leaf_entries.append({
                "part_title": part_title, "num": num, "acr": acr, "full": full,
                "path": leaf_out, "page": None,
            })
            idx += 1

    def render_front_matter(cover_pdf):
        # Row-88(c): keep part headings with their first entries. Render,
        # detect orphaned part <h3>s (last line of their page), push each onto
        # the next page, repeat until none remain (bounded by the part count).
        part_titles = {e["part_title"] for e in leaf_entries}
        breaks = set()
        for _ in range(len(part_titles) + 1):
            render_story_to_pdf(
                build_cover_html(build_toc_html(leaf_entries, breaks),
                                 title, subtitle, cover_lines),
                css_portrait, portrait_box, cover_pdf, doc_name="cover/TOC")
            new = [t for t in _toc_part_orphan_titles(cover_pdf, part_titles)
                   if t not in breaks]
            if not new:
                break
            breaks.update(new)

    # First pass: render the cover+TOC without page numbers just to learn how
    # many pages the front matter itself takes up.
    cover_pdf = tmpdir / "00_cover.pdf"
    render_front_matter(cover_pdf)
    front_matter_pages = len(PdfReader(str(cover_pdf)).pages)

    # Now that the front-matter length is known, compute each entry's real
    # starting page number in the final merged document.
    page_num = front_matter_pages + 1
    for entry in leaf_entries:
        entry["page"] = page_num
        page_num += len(PdfReader(str(entry["path"])).pages)

    # Second pass: re-render cover+TOC with the real page numbers appended to
    # each line. Sanity-check the front matter didn't grow/shrink a page --
    # appending "- p. N" to existing lines shouldn't change line count, but
    # warn rather than silently emit wrong link targets if it ever does.
    render_front_matter(cover_pdf)
    front_matter_pages2 = len(PdfReader(str(cover_pdf)).pages)
    if front_matter_pages2 != front_matter_pages:
        print(f"WARNING: TOC page count changed after adding page numbers "
              f"({front_matter_pages} -> {front_matter_pages2}); TOC links may target the wrong page.",
              file=sys.stderr)
        front_matter_pages = front_matter_pages2

    # Merge
    writer = PdfWriter()
    for pf in [cover_pdf] + [e["path"] for e in leaf_entries]:
        reader = PdfReader(str(pf))
        for page in reader.pages:
            writer.add_page(page)
    with open(out_path, "wb") as f:
        writer.write(f)

    # Add clickable TOC links + PDF bookmarks on the merged file.
    add_toc_links(out_path, leaf_entries, front_matter_pages)

    total_pages = len(PdfReader(str(out_path)).pages)
    print(f"Wrote {out_path} ({total_pages} pages)")
    return total_pages


# ===========================================================================
# Config loading + CLI
# ===========================================================================

def load_config(path):
    """Parse a DOCSET JSON config. Paths (docs_dir, output, leaf files) resolve
    relative to the config file's own directory unless absolute. Returns a dict:
    {structure, docs_dir, out, title, subtitle, cover_lines}."""
    import json
    path = Path(path).resolve()
    base = path.parent
    cfg = json.loads(path.read_text(encoding="utf-8"))
    docs_dir = base / cfg.get("docs_dir", "docs")
    out = cfg.get("output") or cfg.get("out")
    if not out:
        raise ValueError(f"{path}: config needs an 'output' path")
    out = Path(out)
    if not out.is_absolute():
        out = base / out
    structure = []
    for part in cfg["structure"]:
        leaves = []
        for d in part["docs"]:
            leaves.append((str(d.get("num", "")), d["acr"], d["file"],
                           d.get("title", d["acr"]), bool(d.get("landscape", False))))
        structure.append((part["part"], leaves))
    return {
        "structure": structure, "docs_dir": docs_dir, "out": out,
        "title": cfg.get("title", out.stem), "subtitle": cfg.get("subtitle"),
        "cover_lines": cfg.get("cover_lines", []),
    }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("usage:\n"
              "  python docset_builder.py <config.json>\n"
              "  python docset_builder.py --single <in.md> <out.pdf> [--landscape]",
              file=sys.stderr)
        return 0 if argv[:1] in ([], ["--help"], ["-h"]) else 2

    if argv[0] == "--single":
        landscape = "--landscape" in argv
        rest = [a for a in argv[1:] if a != "--landscape"]
        if len(rest) != 2:
            print("usage: --single <in.md> <out.pdf> [--landscape]", file=sys.stderr)
            return 2
        n = render_markdown_file(rest[0], rest[1], landscape=landscape)
        print(f"Wrote {rest[1]} ({n} pages)")
        return 0

    cfg = load_config(argv[0])
    build_docset(cfg["structure"], cfg["docs_dir"], cfg["out"],
                 title=cfg["title"], subtitle=cfg["subtitle"],
                 cover_lines=cfg["cover_lines"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
