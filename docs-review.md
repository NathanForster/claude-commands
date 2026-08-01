---
description: Deep review, cross-reference, and backfill of every document in docs/ (or documentation/), then rebuild the composite PDF
argument-hint: [folder]
---

# Docs Review & Update

Performs a **detailed review and detailed update** of every document in the
project's documentation folder — checking each document for completeness and
accuracy, cross-referencing documents against each other and against the code,
backfilling missing content where it can now be accurately stated, and finally
rebuilding the composite PDF (if one exists) from its build script.

This is a thorough, whole-suite pass — not a quick lint. Read documents in full;
do not skim.

---

## Step 0 — Locate the documentation folder

If `$ARGUMENTS` names a folder, use it directly and skip detection (if it does
not exist, stop and report). Otherwise find the docs folder, in this precedence
order:

1. `docs/`
2. `documentation/`

If both exist, ask the user which to use (or whether to process both). If neither
exists, stop and report — there is nothing to review.

Take an inventory:

- List every document in the folder (recursively). Note the format of each
  (`.md`, `.rst`, `.adoc`, `.tex`, `.docx`, etc.).
- If an index/guide/manifest exists (e.g. `GUIDE.md`, `README.md`, `index.md`,
  `SUMMARY.md`, `_toc.yml`), read it first — it is the source of truth for which
  documents exist and how they relate. Prefer it over any hardcoded assumptions.
- Note any composite/combined PDF (see Step 4) and any `.py` build scripts.

---

## Step 1 — Detailed per-document review

Read **every** document in full. For each, assess:

- **Completeness** — empty sections, `TBD`, `TODO`, `[PLACEHOLDER]`, `<...>`,
  stub headings with no body, tables with missing cells.
- **Accuracy vs. the codebase** — does what the document describes still match the
  actual source (module/class/function names, signatures, data flow, config keys,
  CLI flags, endpoints, file paths)? Flag anything that has drifted.
- **Staleness** — dates, version numbers, "as of" statements, deprecated
  references, screenshots/diagrams that no longer match.
- **Internal consistency** — does the document contradict itself?

Use the codebase and, if present, the requirements register / traceability
material as ground truth (e.g. `requirements/`, `source-development/`). Do not
treat the existing prose as authoritative when it conflicts with the code.

---

## Step 2 — Cross-reference checks

Check consistency **across** the documents (and against the code), collecting a
list of discrepancies:

- **Identifiers** — requirement IDs, ticket numbers, section numbers, figure/table
  numbers, and defined terms are used consistently and every referenced ID exists.
- **Cross-document links** — "see Section X of DOC-Y" style references resolve to
  a real target; no dangling or renamed references.
- **Terminology & naming** — the same concept is named the same way everywhere;
  acronyms are defined once and used consistently.
- **Duplicated facts** — the same fact stated in two documents agrees (versions,
  counts, statuses, dates, owners).
- **Bidirectional traceability** — if a doc claims something is covered elsewhere,
  the target actually covers it, and vice versa.

---

## Step 3 — Present findings, then update & backfill

1. **Present a findings table before writing anything** and get user confirmation:

   | Document | Issue type | Location | Finding | Proposed fix |
   |----------|-----------|----------|---------|--------------|
   | DOC-A    | Stale     | §3.2     | Names old `Foo` class | Update to `Bar` |
   | DOC-B    | Backfill  | §5 (TBD) | Test results now knowable | Fill from test run |
   | DOC-A→B  | Cross-ref | §7 link  | Points to renamed section | Repoint |

2. **On confirmation, apply the updates:**
   - Fix stale/inaccurate content to match the current code and requirements.
   - **Backfill** sections that were previously empty or `TBD` but are now
     knowable from the code, requirements, git history, or build/test results.
   - Repair cross-references and align terminology/identifiers across documents.
   - Update `Updated:` / `Date:` / version fields on each modified document
     (use `currentDate` from system context).

3. **Do not fabricate.** If a section needs information that genuinely does not
   exist yet (formal sign-offs, external results, contract numbers, real
   screenshots), leave a scoped `[TBD — requires <specific missing input>]` and
   list it in the final report. A well-scoped TBD beats a plausible invention.

---

## Step 3.5 — Regenerate derived documents

Some documentation folders contain **derived documents**: files that are generated
from another source (a longer working document, a database, a config) by a script,
rather than written by hand. A condensed summary of a large table, a one-row-per-item
index, an auto-built inventory — all common.

These create two traps, and both are silent:

1. **Editing a derived document instead of its source.** Step 3 will happily "fix" a
   stale figure in a generated file, and the next regeneration will discard the fix
   while the underlying source stays wrong.
2. **Editing a source and not regenerating.** Step 3 corrects the working document,
   but the composite PDF (Step 4) still carries the *old* generated copy — so the
   deliverable silently contradicts the repository.

**Identify derived documents during Step 0's inventory.** Signals, strongest first —
prefer the structural ones, which are exact, over scanning prose, which is not:

- **A script's output path is that document.** Look for `build_*_summary.py`, `gen_*.py`,
  `make_*` and similar, typically alongside the composite's build script, and read what
  each one writes. This is definitive: a file something writes IS generated.
- **A build/config manifest marks it** (e.g. a docset config's notes for a leaf).
- **The document's own header says so** — "generated", "generated from `X`", "do not edit
  by hand", "run `<script>` to refresh". Useful, but the weakest of the three and not
  sufficient alone. It fails in both directions: a generated file whose marker sits below
  the header block (or that says "condensed" rather than "generated") is missed, and a
  hand-written document that *mentions* a generated one — a changelog noting "replaced the
  appendix with a generated summary" — matches when it should not. Both were observed on a
  real suite. Use it to corroborate, then confirm against a script or the manifest.

Cross-check the signals against each other. Where they disagree, the script's output path
wins, and a generated document whose header does not announce itself is worth fixing at
the generator — a reader who opens that file has no way to know their edit is doomed.

**Then:**

1. **Treat every derived document as read-only in Steps 1–3.** Review it for accuracy
   as normal, but route every fix to its *source*, and note in the findings table
   which source you are editing and which derived file it feeds.
2. **Regenerate each derived document** whose source you touched — and, when cheap,
   regenerate all of them regardless, since a source may have changed outside this
   review:

   ```powershell
   python <path-to-generator>.py
   ```

3. **Regenerate before Step 4, never after** — the composite is assembled from the
   files on disk, so a generator run after the PDF build has no effect on the PDF.
4. **Read the generator's output.** These scripts often carry drift tripwires (row
   counts, expected totals) that warn instead of failing. A warning here usually means
   the source gained or lost rows — confirm that was intended before moving on, and
   report it either way.
5. If a generator **fails**, stop and report. Do not hand-edit the derived file to
   work around it, and do not build the composite from a stale copy.

If the folder has no derived documents, skip this step.

---

## Step 4 — Rebuild the composite PDF (if present)

If the documentation folder contains a **composite/combined PDF** (a single PDF
assembled from the individual documents — e.g. `*-combined.pdf`, `*-composite.pdf`,
`full-<suite>.pdf`, or whatever the folder uses):

1. **Find its associated build script.** Look for a `.py` script that generates
   the PDF — check the docs folder, a `build/`, `scripts/`, or `tools/`
   subfolder, and the repo root. Confirm it is the right one by reading it: it
   should reference the source documents and/or the output PDF name (common
   libraries: `reportlab`, `pypdf`/`PyPDF2`, `weasyprint`, `md2pdf`, or a
   `pandoc` subprocess call).

2. **Run it** from the directory it expects, using the project's Python:

   ```powershell
   python <path-to-build-script>.py
   ```

   (Use `py`, a virtualenv interpreter, or `python3` if that is what the project
   uses. If the script documents required arguments, pass them.)

3. **Verify** the PDF was regenerated: confirm its modified timestamp advanced and
   the script exited 0. Report the new page count if the script prints it.

If you find a composite PDF but **no** build script, do not hand-assemble the PDF —
report that the script is missing so the user can point you to it. If there is no
composite PDF at all, skip this step.

---

## Step 5 — Report

Summarize:

- Documents reviewed (count) and folder used.
- Findings by type: stale/inaccurate fixed, backfilled sections, cross-reference
  repairs, terminology alignments.
- Remaining `[TBD]` items, each with the specific input it is waiting on.
- Derived documents: which were regenerated, and any tripwire warnings their
  generators emitted.
- Composite PDF: rebuilt / skipped (no PDF) / blocked (no script found).
- Anything that looked wrong but you left unchanged, and why.

---

## Notes

- This command **reads and writes documentation only** plus running the PDF build
  script — it does not modify source code. If a doc is wrong because the *code*
  changed, update the doc to match the code; if the code itself looks buggy, flag
  it for the user rather than editing it here.
- Respect the folder's existing conventions — heading style, front-matter,
  numbering, file naming. Match, don't reinvent.
- Do not create or delete documents unless the index/guide explicitly calls for a
  document that is missing (a genuine backfill); flag additions for the user first.
- Prefer running the PDF build script over any manual PDF manipulation — the
  script is the source of truth for how the composite is assembled.
- Never hand-edit a generated document (Step 3.5). Edit its source and regenerate.
  An edit to a derived file looks correct right up until the next build erases it.
- If the review surfaces contradictions the code can't resolve (two documents
  disagree and neither matches the code), stop and ask rather than guessing which
  is correct.
