---
description: End-of-session checklist — validate requirements, add tests, build, document, commit
---

# Session Close

Runs the standard end-of-session checklist for any ICM-governed project (and
DoD projects that also maintain a DID documentation suite):

1. **ICM validation** — audit every requirement against source code and pipeline
   artifacts, advance statuses, fill gaps where possible.
2. **Additional tests** — identify untested pure functions and add coverage.
3. **Build & test** — build and test with the project's standard commands; fix
   any failures before continuing.
4. **Docs audit** — run `/docs-review` over the documentation folder (detailed
   review, cross-reference checks, backfill, composite PDF rebuild). Skip this
   step entirely for projects without a `docs/` or `documentation/` folder.
5. **Handoff** — run `/handoff end` to update `HANDOFF.md` and produce the
   session summary (without its own commit — Step 6 handles that).
6. **Commit & push** — stage everything, commit once with a descriptive message,
   push the current branch.

---

## Step 1 — ICM Validation

Follow the full process defined in `/icm-validate`, including its **findings-table
confirmation gate**: present the findings table and get user confirmation before
writing to the register or matrix.

- Read `requirements/workflows/03-baseline/requirements-register.md` in full.
- For every `Baselined` or `Implemented` row:
  - Check whether code exists in `src/`.
  - Check whether `source-development/workflows/03-implementation/input_<REQ-ID>_implementation.md` exists.
  - Check whether `source-development/workflows/04-validation/input_<REQ-ID>_validation.md` exists.
- Produce a findings table (REQ ID | Title | Current Status | Code | Impl artifact | Val artifact | New Status).
- On confirmation, update the register and `requirements/workflows/04-trace/traceability-matrix.md`:
  - Advance `Baselined` → `Implemented` where code is confirmed present.
  - Append `(backfill needed)` to Trace cells that are missing ICM artifacts.
  - Do NOT mark anything `Verified` without an explicit passing test or explicit user confirmation.
- Update the `Updated:` datestamp in both files (use `currentDate` from system context).

---

## Step 2 — Additional Tests

- Read every source file that contains public pure functions (functions whose
  output depends only on arguments, not DB or UI state).
- Compare against the project's existing test suite to find gaps.
- Add new test methods (or new test classes) for any untested functions that can
  be tested without a live DB or running UI. Place them in the project's existing
  test project/directory, following its existing naming convention (typically one
  test class per source module).
- New tests must satisfy: no live SQL connection, no running UI, no real
  filesystem beyond a temp file that is cleaned up afterward.
- If a function cannot be tested without infrastructure (DB, serial port, network),
  add a comment `// [deferred — needs integration test harness]` (or the language's
  comment syntax) and move on.

---

## Step 3 — Build & Test

Use the project's standard build and test commands (e.g. `dotnet build` /
`dotnet test`, `npm run build` / `npm test`, `make`, etc. — detect from the repo).

- Fix every build error before proceeding.
- Fix every test failure before proceeding.
- Report: errors fixed, warnings noted, tests passed / failed.

---

## Step 4 — Docs Audit

**Skip this step if the project has no `docs/` (or `documentation/`) folder.**

Run `/docs-review` — it performs the detailed per-document review,
cross-reference checks, update and backfill (behind its own findings-table
confirmation gate), and rebuilds the composite PDF if one exists.

When the suite is a DoD **Data Item Description (DID)** set — the MIL-STD-498
documentation artifacts, indicated by a `docs/GUIDE.md` listing them — apply
this DID-specific guidance on top of `/docs-review`:

- Read `docs/GUIDE.md` first — it is the single source of truth for which
  documents exist, their dependency order, and which documents feed which others.
- Feed the review two extra sources beyond the codebase: the requirements
  register and traceability matrix (from Step 1), and the build/test results
  from Step 3 (for STR and RTVM verification status).
- Backfill in priority order — highest leverage first:
  - RTVM (feeds STR and is the spine of all traceability)
  - STR (test results are now knowable from the test run)
  - SDD (design is now largely knowable from the source)
  - SRS (requirements are baselined and stable)
  - SVD (version info is knowable from git log)
  - Remaining documents as time permits.
- The RTVM is the spine: all requirement UIDs must match those in the SRS/IRS.
  Cross-check identifiers before writing verification status into the RTVM or STR.

---

## Step 5 — Handoff

Invoke `/handoff end` to update `HANDOFF.md` and produce the session summary.
Do **not** let handoff run its own commit/push — Step 6 makes a single commit
that includes `HANDOFF.md` along with everything else.

---

## Step 6 — Commit & Push

Review the working tree first and flag anything unexpected — files unrelated to
this session's work should be surfaced to the user before staging, not swept in
silently:

```sh
git status --short
```

Then stage all modified files (including `HANDOFF.md` from Step 5):

```sh
git add -A
```

Commit once with a message that summarises what changed (req statuses, test count,
DID sections filled):

```
docs: session-close — <short summary>

- ICM: <N> reqs advanced, <M> artifacts backfilled
- Tests: <K> new tests added, <total> total passing
- DIDs: <list of documents updated and sections filled>
- Build: 0 errors
```

Then push the current branch:

```sh
git push origin HEAD
```

---

## Notes

- Run steps in order. Do not commit/push (Step 6) until build and tests pass (Step 3).
- `Superseded` requirements: skip in all steps.
- If any source file has no register entry, flag it for the user — do not
  silently create REQ IDs.
- The docs audit is "best effort" — fill only what can be accurately stated.
  A well-scoped `[TBD]` is better than a plausible fabrication.
