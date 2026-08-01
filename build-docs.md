---
description: Build a project's consolidated documentation-set PDF (or render a single Markdown file) using the shared docset engine, driven by a DOCSET.json config or the project's own build script.
argument-hint: "[empty = build the docset | single <in.md> <out.pdf> [landscape]]"
---

# Build Docs — consolidated documentation-set PDF

Assembles a project's Markdown documents into one bookmarked PDF (cover + linked
table of contents + per-part section covers), using the **shared docset engine**
so every project shares one copy of the (hard-won) table/heading pagination
logic. Can also render a **single** Markdown file to a standalone PDF.

The engine is loaded from **`~/.claude/commands/lib/docset_builder.py`** — the
user-level copy that the sync script keeps current. Its master lives in the
claude-commands repo (`lib/docset_builder.py`); fall back to that repo checkout
(e.g. `C:\.ai\.claude\commands\lib\`) only if the user-level copy is missing.
Its public API: `build_docset(...)`, `render_markdown_file(...)`, `load_config(...)`.

**Requires** (in the project's Python): `pymupdf`, `markdown-it-py`, `pypdf`,
`beautifulsoup4`. If an import fails, report the missing package — do not
hand-assemble a PDF.

---

## Procedure

### If `$ARGUMENTS` begins with `single`
Render one file: `single <in.md> <out.pdf> [landscape]`.

```
python <lib>/docset_builder.py --single <in.md> <out.pdf> [--landscape]
```

Report the output path and page count, then stop.

### Otherwise — build the whole documentation set

1. **Find the project's build definition**, in this precedence order:
   1. A **project build script** — e.g. `orchestrator/build_docset_pdf.py`,
      `scripts/build_docs*.py`, or `build/*.py`. Confirm by reading it: it should
      reference the shared engine or the documents. **Prefer running this** — it
      is the project's own source of truth for how the set is assembled.
   2. A **`DOCSET.json`** config (repo root, else `docs/`). This is the
      data-file form the shared engine reads directly (see *Config format*).
   - If both exist, prefer the build script (it may load the JSON anyway).
   - If neither exists, offer to create a `DOCSET.json` (see *Bootstrapping*) —
     do not invent a structure silently.

2. **Regenerate any derived documents first.** If a leaf is generated from another
   source by a script (its header says "generated", or the config's notes say so, or
   a `build_*_summary.py`-style script writes it), run that generator **before** the
   composite build — the set is assembled from what is on disk, so a stale generated
   leaf ships silently. Read each generator's output: drift tripwires warn rather
   than fail. If one errors, stop and report; never build from a stale copy. Full
   treatment in `/docs-review` Step 3.5.

3. **Run it** from the repo root, using the project's Python:
   - Build script: `python orchestrator/build_docset_pdf.py`
   - Bare config: `python <lib>/docset_builder.py DOCSET.json`

4. **Verify**: the script exited 0, the output PDF's timestamp advanced, and the
   printed page count is sane. If the engine printed any `WARNING:` lines
   (missing source doc, TOC page-count drift, non-convergent layout), surface
   them — they indicate a doc that didn't make it in or a layout that needs a
   look.

5. **Report**: output path, page count, TOC entry count, and any warnings.

---

## Config format (`DOCSET.json`)

Paths resolve relative to the config file's own directory.

```json
{
  "title": "MyProject",
  "subtitle": "Consolidated Documentation Set",
  "cover_lines": ["One-line description", "Organization"],
  "docs_dir": "docs",
  "output": "docs/MyProject-Documentation-Set.pdf",
  "structure": [
    {"part": "1. Requirements", "docs": [
      {"num": "1", "acr": "SRS", "file": "SRS.md", "title": "Software Requirements Specification", "landscape": false},
      {"num": "2", "acr": "RTVM", "file": "RTVM.md", "title": "Requirements Traceability Matrix", "landscape": true}
    ]}
  ]
}
```

- **`landscape: true`** for wide tables (more than ~6 columns); column widths
  are computed automatically, so this is the only per-doc layout knob.
- A **`file` ending in `.pdf`** is a pre-rendered leaf: a generated section cover
  is prepended and the PDF concatenated as-is (no Markdown processing).
- A `file` may use `../` to reach a doc outside `docs_dir`.
- Any key starting with `_` (e.g. `_notes`) is ignored by the engine — use it to
  record why docs are included/excluded.

A copy of this template lives beside the engine at `lib/DOCSET.example.json`.

---

## Bootstrapping a `DOCSET.json`

If the project has none and wants one, build it from what is actually in the docs
folder — never from assumption. List the `docs/*.md` files, group them into
logical parts, and confirm the order/titles with the user before writing. An
unverified structure is worse than none.

---

## Notes

- This command **builds PDFs only** — it does not edit documents. For a
  content review + rebuild, use `/docs-review` (its Step 4 runs this same build
  script).
- Prefer the project's build script / config over any manual PDF manipulation —
  the config is the source of truth for how the set is assembled.
- To change which documents are in the set, edit `DOCSET.json` (or the project's
  structure) — never hard-code documents into the shared engine.
