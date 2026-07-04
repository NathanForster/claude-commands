---
description: Audit ICM requirements against code and pipeline artifacts, update statuses
---

# ICM: Validate Implementation

Checks every requirement in the register against the actual source code AND the
source-development pipeline artifacts, then updates the `Status` column in both
the requirements register and the traceability matrix.

## Files

- Register:  `requirements/workflows/03-baseline/requirements-register.md`
- Matrix:    `requirements/workflows/04-trace/traceability-matrix.md`
- Source:    `src/`
- Artifacts: `source-development/workflows/03-implementation/`
             `source-development/workflows/04-validation/`

## Status values (from the register's Status Key)

| Value | Meaning |
|-------|---------|
| Baselined | Approved and frozen — not yet checked for implementation |
| Implemented | Code exists in `src/` |
| Verified | Tested or validated (tests pass, or manually confirmed working) |
| Superseded | Replaced by a newer requirement — leave as-is |

## Process

1. **Read the register** in full. Identify every row whose Status is `Baselined` or
   `Implemented` (i.e. not yet `Verified` or `Superseded`).

2. **For each such requirement**, perform two checks:

   ### 2a. Code check
   - Use the Trace column as the starting point for where to look.
   - Read the relevant source file(s) and grep for key symbols if needed.
   - Determine: fully implemented / partially implemented / not implemented.

   ### 2b. Artifact check
   - Look for `input_<req_id>_implementation.md` in
     `source-development/workflows/03-implementation/`.
   - Look for `input_<req_id>_validation.md` in
     `source-development/workflows/04-validation/`.
   - Flag any `Implemented` row that is **missing either artifact** — this means
     the source-development pipeline was skipped and must be backfilled.

3. **Produce a findings table** before touching any files:

   | REQ ID | Title | Current Status | Code | Impl artifact | Val artifact | New Status |
   |--------|-------|----------------|------|---------------|--------------|------------|
   | REQ-XX | ...   | Baselined | ✅ present | ✅ present | ✅ present | Implemented |
   | REQ-YY | ...   | Implemented | ✅ present | ❌ missing | ❌ missing | Implemented (backfill needed) |

   Present this to the user and confirm before writing anything.

4. **On confirmation**, update both documents:
   - In the **register**: change the `Status` cell for each affected row.
     Append `(backfill needed)` to the Trace cell for any row missing artifacts.
   - In the **matrix**: add or update the `Source File(s)` cell for any row that
     was missing or stale trace information.
   - Update the `Updated:` datestamp in the header comment of both files.
   - Do not change any other content — titles, priorities, ADR references, etc.

5. **Report** a summary:
   - How many moved to Implemented
   - How many moved to Verified
   - How many remain Baselined (with reason)
   - How many are missing ICM artifacts (backfill needed)
   - How many gaps were found in code

## Notes

- Check the current date from the system context (`currentDate`) for the `Updated:` stamp.
- If a requirement is partially implemented, set Status to `Implemented` but append
  `(partial — <gap description>)` in the Trace column so the gap is visible.
- Do not mark anything `Verified` unless there is an explicit test in the
  project's test suite (e.g. `testing-validation/`, `src/tests/`, or the project's
  dedicated test project) that covers it, or the user explicitly confirms manual
  verification.
- `Superseded` rows: skip entirely.
- If a new requirement has been added to `src/` that has no register entry, flag it
  for the user — do not silently create new REQ IDs.
- Canonical artifact naming: `input_<REQ-ID>_implementation.md` and
  `input_<REQ-ID>_validation.md`, where `<REQ-ID>` is the register's requirement
  ID (e.g. `input_REQ-42_implementation.md`). This is the form `/session-close`
  also expects. Treat the older `input_req<NN>_*` spelling as legacy — accept it
  when scanning, but write any new artifacts with the canonical form.
