---
description: Deep review, cross-reference, and backfill of every document in docs/ (or documentation/), then rebuild the composite PDF
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

Find the docs folder, in this precedence order:

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
- If the review surfaces contradictions the code can't resolve (two documents
  disagree and neither matches the code), stop and ask rather than guessing which
  is correct.
