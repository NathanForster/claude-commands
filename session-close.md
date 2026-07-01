# Session Close

Runs the standard end-of-session checklist for FRIS_NET (and any ICM-governed
DoD project):

1. **ICM validation** — audit every requirement against source code and pipeline
   artifacts, advance statuses, fill gaps where possible.
2. **Additional tests** — identify untested pure functions and add xUnit coverage.
3. **Build & test** — `dotnet build` + `dotnet test`; fix any failures before
   continuing.
4. **DID audit** — review the DoD Data Item Description documents in `DIDs/` and
   fill in sections that can now be accurately completed given the current
   state of the code and requirements.
5. **Commit & push** — stage everything, commit with a descriptive message, push
   to remote.
6. **Handoff** — run `/handoff end` to update `HANDOFF.md` and print the session
   summary.

---

## Step 1 — ICM Validation

Follow the full process defined in `/icm-validate`:

- Read `requirements/workflows/03-baseline/requirements-register.md` in full.
- For every `Baselined` or `Implemented` row:
  - Check whether code exists in `src/` (Data/, Forms/, Modules/).
  - Check whether `source-development/workflows/03-implementation/input_<REQ-ID>_implementation.md` exists.
  - Check whether `source-development/workflows/04-validation/input_<REQ-ID>_validation.md` exists.
- Produce a findings table (REQ ID | Title | Current Status | Code | Impl artifact | Val artifact | New Status).
- Update the register and `requirements/workflows/04-trace/traceability-matrix.md`:
  - Advance `Baselined` → `Implemented` where code is confirmed present.
  - Append `(backfill needed)` to Trace cells that are missing ICM artifacts.
  - Do NOT mark anything `Verified` without an explicit passing test or explicit user confirmation.
- Update the `Updated:` datestamp in both files (use `currentDate` from system context).

---

## Step 2 — Additional Tests

- Read every `.vb` file under `Modules/` that contains public pure functions
  (functions whose output depends only on arguments, not DB or UI state).
- Compare against existing test files in `FRIS.Tests/` to find gaps.
- Add new `<Fact>` test methods (or new test classes) for any untested functions
  that can be tested without a live DB or running form.
- Naming: one test class per source module, file `FRIS.Tests/<ModuleName>Tests.vb`.
- New tests must satisfy: no live SQL connection, no running form, no real
  filesystem beyond `Path.GetTempFileName()` (cleaned up in `Finally`).
- If a function cannot be tested without infrastructure (DB, serial port, network),
  add a comment `' [deferred — needs integration test harness]` and move on.

---

## Step 3 — Build & Test

```powershell
dotnet build FRIS.sln
dotnet test FRIS.sln
```

- Fix every build error before proceeding.
- Fix every test failure before proceeding.
- Report: errors fixed, warnings noted, tests passed / failed.

---

## Step 4 — DID Audit (DoD Data Item Descriptions)

**DID = Data Item Description** — the formal DoD documentation artifacts defined
by MIL-STD-498 and subsequent DIDs. This project's DID suite lives in `DIDs/`.

Read `DIDs/GUIDE.md` first to understand the dependency order and which documents
feed which others. The current DID suite includes:

| File | Document |
|------|----------|
| `CI-DI-SESS-82007B.md` | CI Documentation Recommendation |
| `CMP-DI-SESS-80858D.md` | Configuration Management Plan |
| `SRS-DI-IPSC-81433A.md` | Software Requirements Specification |
| `IRS-DI-IPSC-81434A.md` | Interface Requirements Specification |
| `SDD-DI-IPSC-81435B.md` | Software Design Description |
| `SDP-DI-IPSC-81427B.md` | Software Development Plan |
| `STP-DI-IPSC-81438A.md` | Software Test Plan |
| `STPr-Combined.md` | Software Test Procedures (combined) |
| `STR-DI-IPSC-81440A.md` | Software Test Report |
| `RTVM-DI-MGMT-82133A.md` | Requirements Traceability/Verification Matrix |
| `SSS-DI-IPSC-81431A.md` | System/Subsystem Specification |
| `SPS-DI-IPSC-81441A.md` | Software Product Specification |
| `SVD-DI-IPSC-81442A.md` | Software Version Description |
| `CTP-DI-SCRE-82140A.md` | Cybersecurity Test Plan |
| `CTPr-DI-MGMT-82141A.md` | Cybersecurity Test Procedures |
| `CTR-DI-MGMT-82142A.md` | Cybersecurity Test Report |

### Audit process

For each DID:

1. **Read the document.** Identify every section or placeholder that is still
   empty, marked `TBD`, `[PLACEHOLDER]`, or is clearly incomplete relative to
   what can now be known from the codebase and requirements register.

2. **Fill in what is reasonable and possible now.** Use the following sources:
   - `requirements/workflows/03-baseline/requirements-register.md` — for
     requirement text, status, and traceability.
   - `requirements/workflows/04-trace/traceability-matrix.md` — for
     verification mappings.
   - `src/` (Data/, Forms/, Modules/) — for actual design and implementation
     facts (module names, class names, method signatures, data flow).
   - `source-development/workflows/03-implementation/` and
     `source-development/workflows/04-validation/` — for design decisions and
     validation outcomes.
   - Build and test results from Step 3 — for STR and RTVM verification status.

3. **Do not fabricate.** If a section requires information that does not yet
   exist (e.g., formal acceptance test results, CDRL submission dates, contract
   numbers), leave it as `[TBD — requires <specific missing input>]` and note
   it in the session summary.

4. **Priority order** — fill the highest-leverage documents first:
   - RTVM (feeds STR and is the spine of all traceability)
   - STR (test results are now knowable from `dotnet test`)
   - SDD (design is now largely knowable from the source)
   - SRS (requirements are baselined and stable)
   - SVD (version info is knowable from git log)
   - Remaining documents as time permits.

5. **Update the `Updated:` or `Date:` field** in each modified DID to the
   current date (use `currentDate` from system context).

---

## Step 5 — Commit & Push

Stage all modified files:

```powershell
git add -A
```

Commit with a message that summarises what changed (req statuses, test count,
DID sections filled):

```
feat/docs: session-close — <short summary>

- ICM: <N> reqs advanced, <M> artifacts backfilled
- Tests: <K> new tests added, <total> total passing
- DIDs: <list of documents updated and sections filled>
- Build: 0 errors
```

Then push:

```powershell
git push origin master
```

---

## Step 6 — Handoff

Invoke `/handoff end` — follow all steps in that skill to update `HANDOFF.md`
and print the session summary.

---

## Notes

- Run steps in order. Do not push (Step 5) until build and tests pass (Step 3).
- `Superseded` requirements: skip in all steps.
- If any source file has no register entry, flag it for the user — do not
  silently create REQ IDs.
- The DID audit is "best effort" — fill only what can be accurately stated.
  A well-scoped `[TBD]` is better than a plausible fabrication.
- The RTVM is the spine: all requirement UIDs must match those in the SRS/IRS.
  Cross-check identifiers before writing verification status into the RTVM or STR.
