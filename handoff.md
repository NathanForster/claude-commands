# Handoff — Session Start / End Helper

Reads the project handoff document and either:
- **Session start**: surfaces all context needed to resume work immediately, or
- **Session end**: prompts for what changed and updates the handoff document.

## Detecting mode

- If the user typed `/handoff start` (or just `/handoff` at the start of a new
  session): run **START mode**.
- If the user typed `/handoff end` (or `/handoff update`): run **END mode**.
- If ambiguous, ask: "Are you starting a new session or ending one?"

---

## START mode

1. Read `D:\.ai\staulks\.claude\HANDOFF.md` in full.

2. Print a concise "Ready to work" summary covering:
   - Last REQ ID and last commit SHA
   - Current test counts (regression / total)
   - Next available REQ ID
   - Any known limitations or follow-up items from Section 9
   - One-liner reminder of the ICM pipeline step sequence

3. Confirm: "Handoff loaded. What would you like to work on?"

Do NOT re-read the handoff on every subsequent turn — it is loaded once.

---

## END mode

Walk through these steps in order, pausing after each for the user's input:

### Step 1 — Gather session delta

Ask the user (or infer from context if the conversation is available):
- What REQ IDs were worked on this session?
- What was the last commit SHA and message?
- Were any new paths, patterns, or gotchas discovered?
- Were any known limitations resolved or added?

### Step 2 — Update HANDOFF.md

Read `D:\.ai\staulks\.claude\HANDOFF.md`, then apply these specific updates:

| Section | What to update |
|---------|----------------|
| Header line | `Last updated`, `Last REQ`, `Last commit` |
| §7 "Next available REQ ID" | Increment past the highest REQ used |
| §7 Register version | Update if register version changed |
| §7 Matrix version | Update if matrix version changed |
| §9 "Recent commits" | Prepend new commits (keep last ~8) |
| §9 "Known limitations" | Add/remove items as appropriate |
| Any section | Add new paths, patterns, gotchas |

Write the updated file back to `D:\.ai\staulks\.claude\HANDOFF.md`.

### Step 3 — Compose the session summary

Produce a compact Markdown summary suitable for pasting into the next session's
compact message (the format used at the start of this session). Include:

1. **Primary Request and Intent** — what the user asked for
2. **Key Technical Concepts** — algorithms, Qt patterns, design decisions
3. **Files and Code Sections** — exact paths and key changes with snippets
4. **Errors and Fixes** — bugs hit and how they were resolved
5. **Problem Solving** — non-obvious decisions
6. **All User Messages** — verbatim list
7. **Pending Tasks** — anything explicitly left incomplete
8. **Current Work** — last thing done before session end

### Step 4 — Commit the handoff file

```
git add D:\.ai\staulks\.claude\HANDOFF.md
git commit -m "docs: update HANDOFF.md for session end <date>"
```

Ask the user whether to push: `git push origin master`.

---

## Notes

- The handoff file lives at `D:\.ai\staulks\.claude\HANDOFF.md`.
- It is **committed to the repo** (not gitignored) so it travels with the code.
- Never include actual credential values in the handoff document — reference
  the `.env` file by path only.
- The session summary (Step 3) is separate from HANDOFF.md — it is printed to
  the chat for the user to copy, not written to any file.


