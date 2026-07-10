---
description: Session continuity helper — load context on start, update HANDOFF.md on end
argument-hint: start | end
---

# Handoff — Session Start / End Helper

Reads the project handoff document and either:
- **Session start**: surfaces all context needed to resume work immediately, or
- **Session end**: prompts for what changed and updates the handoff document.

## Detecting mode

Inspect `$ARGUMENTS`:

- `start` (or empty at the start of a new session): run **START mode**.
- `end` (or `update`): run **END mode**.
- Anything else / ambiguous: ask "Are you starting a new session or ending one?"

---

## START mode

1. Read `HANDOFF.md` in the project root in full.

   If the file does not exist (first session on this project), offer to create
   it from the template in the **HANDOFF.md template** section below, then skip
   to step 4.

2. **Verify freshness.** Run `git log -1 --format="%H %s"` and compare against the
   `Last commit` recorded in `HANDOFF.md`. If they differ, warn the user that the
   previous session likely ended without running `/handoff end`, so the handoff
   may be stale — recent commits may not be reflected below.

3. Print a concise "Ready to work" summary covering:
   - Last commit SHA and message
   - In-progress work and current status
   - Any known blockers or follow-up items
   - Next steps the user left off at

4. Confirm: "Handoff loaded. What would you like to work on?"

Do NOT re-read the handoff on every subsequent turn — it is loaded once.

---

## END mode

### Step 1 — Gather session delta

When the session's conversation is in context, **infer** these and confirm the
assembled delta once, rather than prompting for each item. Only fall back to
asking item-by-item if the conversation is unavailable or ambiguous:

- What was worked on this session?
- What was the last commit SHA and message?
- Were any new paths, patterns, or gotchas discovered?
- Were any known limitations resolved or added?

### Step 2 — Update HANDOFF.md

Read `HANDOFF.md` — if it does not exist, create it from the template in the
**HANDOFF.md template** section below first — then apply these specific updates:

| Section | What to update |
|---------|----------------|
| Header line | `Last updated`, `Last commit` |
| Recent commits | Prepend new commits (keep last ~8) |
| Known limitations | Add/remove items as appropriate |
| Any section | Add new paths, patterns, gotchas |

Write the updated file back to `HANDOFF.md`.

### Step 3 — Compose the session summary

Produce a compact Markdown summary suitable for pasting into the next session's
context. Include:

1. **Primary Request and Intent** — what the user asked for
2. **Key Technical Concepts** — algorithms, patterns, design decisions
3. **Files and Code Sections** — exact paths and key changes with snippets
4. **Errors and Fixes** — bugs hit and how they were resolved
5. **Problem Solving** — non-obvious decisions
6. **User Requests** — paraphrased list of what the user asked for (quote
   verbatim only where exact wording matters)
7. **Pending Tasks** — anything explicitly left incomplete
8. **Current Work** — last thing done before session end

### Step 4 — Commit the handoff file

> **When invoked from `/session-close`:** skip this step. Session-close makes a
> single commit that already includes `HANDOFF.md`. Only commit here when
> `/handoff end` was run on its own.

```
git add HANDOFF.md
git commit -m "docs: update HANDOFF.md for session end <date>"
```

Use `currentDate` from system context for `<date>`.

Ask the user whether to push the current branch: `git push origin HEAD`.

---

## HANDOFF.md template

When creating `HANDOFF.md` for the first time (either mode), seed it with:

````markdown
# HANDOFF

Last updated: <date> | Last commit: <SHA> — <message>

## Current state

<one paragraph on where the project stands and what is in progress>

## Recent commits

- <SHA> — <message>

## Known limitations

- <item, or "None known">

## Next steps

- <item>
````

Fill the placeholders from `git log` and the current session before writing —
do not leave literal `<...>` markers in the committed file.

---

## Notes

- `HANDOFF.md` is assumed to live at the project root.
- It should be **committed to the repo** (not gitignored) so it travels with the code.
- Never include actual credential values in the handoff document — reference
  config/env files by path only.
- The session summary (Step 3) is separate from HANDOFF.md — it is printed to
  the chat for the user to copy, not written to any file.
