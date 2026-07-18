# claude-commands

A collection of reusable [Claude Code](https://claude.ai/code) slash commands for software development workflows.

These commands are designed to be dropped into any project and used across sessions, teams, or machines.

## Commands at a glance

| Command | What it does |
|---------|--------------|
| [`/handoff`](handoff.md) | Session continuity — load context at start, update `HANDOFF.md` at end |
| [`/icm-validate`](icm-validate.md) | Audit ICM requirement statuses against code and pipeline artifacts |
| [`/session-close`](session-close.md) | Full end-of-session checklist — validate, test, document, commit |
| [`/docs-review`](docs-review.md) | Deep review, cross-reference, and backfill of the docs folder, plus composite PDF rebuild |
| [`/build-docs`](build-docs.md) | Build the consolidated documentation-set PDF (or render a single Markdown file) via the shared docset engine |
| [`/run`](run.md) | Launch the project's app in a named mode, driven by a `RUN.md` mode registry |

## Installation

1. Clone the repo:
   ```bash
   git clone https://github.com/NathanForster/claude-commands.git
   ```

2. Copy the command files you want into your Claude Code user commands directory:
   ```
   # macOS / Linux
   ~/.claude/commands/

   # Windows
   C:\Users\<you>\.claude\commands\
   ```

   Or, to scope them to a single project, copy them into that repo's `.claude/commands/` directory instead — they travel with the project and are available to anyone who clones it.

3. The commands are immediately available as `/command-name` in any Claude Code session.

## Commands

### `/handoff`

A session continuity helper that keeps long-running projects moving across Claude Code context resets.

- `/handoff start` — Reads the project's `HANDOFF.md` and surfaces everything needed to resume work immediately: in-progress tasks, recent decisions, blockers, and next steps.
- `/handoff end` — Prompts for what changed this session and updates `HANDOFF.md` so the next session starts clean.

Pairs well with a `HANDOFF.md` file checked into your project root — if the file doesn't exist yet, the command offers to create it from a built-in template.

---

### `/icm-validate`

Validates implementation status for projects using the [Interpretable Context Methodology (ICM)](https://github.com/NathanForster/ICM) requirements framework.

Checks every requirement in the register against:
- Source code in `src/`
- Implementation briefs in `source-development/workflows/03-implementation/`
- Validation briefs in `source-development/workflows/04-validation/`

Updates the `Status` column in both the requirements register and traceability matrix with one of: `Baselined`, `Implemented`, `Verified`, or `Superseded`.

Pass a requirement ID — `/icm-validate REQ-42` — to validate a single requirement instead of the full register.

---

### `/session-close`

An end-of-session checklist for ICM-governed projects that runs the whole close-out in order:

1. **ICM validation** — runs `/icm-validate` (with its confirmation gate) to advance requirement statuses.
2. **Additional tests** — adds coverage for untested pure functions.
3. **Build & test** — builds and tests with the project's standard commands, fixing failures before continuing.
4. **Docs audit** — runs `/docs-review` over the documentation folder, assuming full backfill of every section now knowable, with DID-specific priority ordering for DoD projects. Skipped when there's no docs folder.
5. **Handoff** — runs `/handoff end` to update `HANDOFF.md` and produce the session summary.
6. **Commit & push** — a single commit covering everything (including `HANDOFF.md`), pushed to the current branch.

---

### `/docs-review`

A deep review-and-update pass over every document in a project's `docs/` (or `documentation/`) folder.

- **Per-document review** — reads each document in full, flagging incomplete sections, `TBD`/placeholder content, and anything that has drifted from the current code or requirements.
- **Cross-reference checks** — verifies identifiers, cross-document links, terminology, and duplicated facts agree across the whole suite.
- **Update & backfill** — after a findings-table confirmation, fixes stale content, backfills sections now knowable from the code/requirements/tests, and repairs cross-references (scoped `[TBD]`s where information genuinely doesn't exist yet).
- **Composite PDF** — if the folder contains a combined PDF, locates its `.py` build script and re-runs it to regenerate the PDF.

Pass a folder — `/docs-review documentation` — to target a specific directory and skip auto-detection.

---

### `/build-docs`

Builds a project's **consolidated documentation-set PDF** — a single bookmarked file assembled from many Markdown docs, with a cover, a clickable table of contents, and per-part section covers. It can also render a **single** Markdown file to a standalone PDF (`/build-docs single <in.md> <out.pdf> [landscape]`).

All the layout logic lives in one shared engine — [`lib/docset_builder.py`](lib/docset_builder.py) — so every project shares the same (heavily battle-tested) table pagination, column-width fitting, cross-page header repetition, keep-heading-with-content, and silent-truncation verification. Projects supply only *which* documents to include:

- **Data-file form** — a `DOCSET.json` at the repo root (see [`lib/DOCSET.example.json`](lib/DOCSET.example.json)) listing the parts, documents, titles, and per-doc landscape flags. Run directly: `python lib/docset_builder.py DOCSET.json`.
- **Build-script form** — a tiny `orchestrator/build_docset_pdf.py` (or similar) that imports the engine and loads the project's config. Keeping a `.py` entry point means `/docs-review` finds and runs it automatically.

Requires `pymupdf`, `markdown-it-py`, `pypdf`, `beautifulsoup4` in the project's Python.

#### Adopting the docset builder in another project

Paste the prompt below into a fresh Claude session **in the target project**. It is
self-contained — it tells Claude to reference the shared engine (never copy it),
propose a `DOCSET.json` from the project's own `docs/`, add a thin build script, and
verify the result.

````text
Set this project up to build a consolidated documentation-set PDF using the shared
docset engine (not a per-project copy).

BACKGROUND
- The shared engine lives in my Claude commands repo:
  https://github.com/NathanForster/claude-commands  ->  lib/docset_builder.py
- On this machine it should be at:  C:\.ai\.claude\commands\lib\docset_builder.py
  If that file is missing, tell me and stop (I may need to `git pull` that repo).
- It renders Markdown -> PDF with automatic table column-fitting, cross-page header
  repetition, keep-heading-with-its-content, and silent-truncation verification.
- Python deps (must be importable by the python you run): pymupdf, markdown-it-py,
  pypdf, beautifulsoup4. If an import fails, report the missing package -- do NOT
  hand-assemble a PDF.

DO THIS
1. Confirm the engine exists at one of: the CLAUDE_COMMANDS_LIB env var,
   C:\.ai\.claude\commands\lib, or ~/.claude/commands/lib. Read its module
   docstring for the current API/CLI.
2. Inventory this project's docs/ folder. Propose a DOCSET.json structure --
   grouped into logical "parts", each doc with num/acr/file/title and a
   landscape flag (true only for wide tables, >~6 columns). SHOW me the proposed
   structure and wait for my confirmation before writing anything. Don't guess
   the order or invent documents.
3. On my OK, write DOCSET.json at the repo root. Format:
     {
       "title": "...", "subtitle": "...", "cover_lines": ["...", "..."],
       "docs_dir": "docs",
       "output": "docs/<Project>-Documentation-Set.pdf",
       "structure": [
         {"part": "1. Requirements", "docs": [
           {"num":"1","acr":"SRS","file":"SRS.md","title":"...","landscape":false}
         ]}
       ]
     }
   (A `file` ending in .pdf is concatenated as a pre-rendered leaf; `../` may reach
   outside docs_dir; any key starting with `_` is ignored -- use `_notes` for
   rationale. Template: C:\.ai\.claude\commands\lib\DOCSET.example.json)
4. Add a thin build script at orchestrator/build_docset_pdf.py that locates the
   shared engine (env CLAUDE_COMMANDS_LIB -> C:\.ai\.claude\commands\lib ->
   ~/.claude/commands/lib), then calls
   db.load_config('DOCSET.json') + db.build_docset(...). Keeping a .py entry point
   means /docs-review and /build-docs find and run it. (Model it on FRIS_NET's
   orchestrator/build_docset_pdf.py.)
5. Build it, then VERIFY: exit 0, output PDF timestamp advanced, sane page count,
   TOC entries present, and no `WARNING:` lines from the engine. Report those.

Do not copy the engine into this repo -- reference the shared one only.
````

Notes:
- If the project **already** has a combined PDF and its own build script, just run
  `/build-docs` (or `/docs-review`) — it finds and runs the existing script instead
  of duplicating setup.
- For a **one-off single file**:
  `python C:\.ai\.claude\commands\lib\docset_builder.py --single <in.md> <out.pdf> [--landscape]`

---

### `/run`

Launches the project's app in a requested run mode — `/run <mode>`, or bare `/run` for the documented default.

The command carries no project knowledge of its own: a `RUN.md` in the project root is the source of truth, defining the available modes, each mode's launcher and arguments, the launch sequence, and any gates. If the project has no `RUN.md`, the command offers to bootstrap one from what's actually in the repo (launch scripts, README, CI config) — verifying each mode before writing it down.

Pairs with `RUN.md` the same way `/handoff` pairs with `HANDOFF.md`.

---

## License

MIT — see [LICENSE](LICENSE).
