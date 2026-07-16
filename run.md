---
description: Launch this project's app in a requested run mode. RUN.md in the project root is the mode registry and defines the launch procedure.
argument-hint: "[mode - see RUN.md in the project root; empty = the documented default]"
---

# Run — launch this project's app in a given mode

**`RUN.md` in the project root is the source of truth.** It defines the available
modes, each mode's launcher and arguments, the launch procedure, and any rules that
govern it. This command carries no project knowledge of its own — read RUN.md and do
what it says.

## Procedure

1. **Read `RUN.md` in the project root.** If it does not exist, say so and stop — do
   not improvise a launch. Offer to create one (see *Bootstrapping* below).
2. **Resolve `$ARGUMENTS`** case-insensitively against RUN.md's mode table(s).
   - Empty → the default RUN.md documents.
   - No match → list the available modes from RUN.md and stop.
3. **Execute RUN.md's documented sequence in order**, honouring every rule and gate
   it states.
4. **Report**: the mode you resolved, the evidence RUN.md nominates as proof of a
   good launch (process/command line, window title, log lines), and anything that
   deviated.

## Rules

- **Never invent** a launcher path, argument, mode, or launch method that RUN.md does
  not document. If something needed is missing, say what is missing and stop.
- **Never skip a gate.** If RUN.md says do not proceed on a FAIL, do not proceed.
- **RUN.md outranks memory.** It is versioned with the code; recollections of how this
  project launched are not. If they conflict, RUN.md wins and the memory is stale —
  say so.
- **Report failures verbatim.** Quote the error rather than paraphrasing it; the exact
  text is usually what identifies the cause.

## Maintaining RUN.md

RUN.md is data, not narrative. When a launcher, mode, or argument changes, update the
table there — never hard-code project specifics into this command.

## Bootstrapping a RUN.md

If the project has none, offer to create one from what is actually in the repo (launch
scripts, README, CI config) — never from assumption. A workable shape:

```markdown
# RUN — <project> launch modes

## 1. LAUNCH RULE      # how to launch and what never to do, with the reason
## 2. MODES            # table: argument | launcher | resulting command line
## 3. SEQUENCE         # ordered steps: pre-clean, dependencies, launch, verify
## 4. GOTCHAS          # environment traps worth their own line
```

Verify each mode before writing it down. An unverified table is worse than none — it
reads as authoritative.
