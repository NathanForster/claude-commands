# claude-commands

A collection of reusable [Claude Code](https://claude.ai/code) slash commands for software development workflows.

These commands are designed to be dropped into any project and used across sessions, teams, or machines.

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

3. The commands are immediately available as `/command-name` in any Claude Code session.

## Commands

### `/handoff`

A session continuity helper that keeps long-running projects moving across Claude Code context resets.

- `/handoff start` — Reads the project's `HANDOFF.md` and surfaces everything needed to resume work immediately: in-progress tasks, recent decisions, blockers, and next steps.
- `/handoff end` — Prompts for what changed this session and updates `HANDOFF.md` so the next session starts clean.

Pairs well with a `HANDOFF.md` file checked into your project root.

---

### `/icm-validate`

Validates implementation status for projects using the [Interpretable Context Methodology (ICM)](https://github.com/NathanForster/ICM) requirements framework.

Checks every requirement in the register against:
- Source code in `src/`
- Implementation briefs in `source-development/workflows/03-implementation/`
- Validation briefs in `source-development/workflows/04-validation/`

Updates the `Status` column in both the requirements register and traceability matrix with one of: `Baselined`, `Implemented`, `Verified`, or `Superseded`.

---

### `/session-close`

An end-of-session checklist for ICM-governed projects that runs the whole close-out in order:

1. **ICM validation** — runs `/icm-validate` (with its confirmation gate) to advance requirement statuses.
2. **Additional tests** — adds coverage for untested pure functions.
3. **Build & test** — builds and tests with the project's standard commands, fixing failures before continuing.
4. **DID audit** — for DoD projects with a Data Item Description suite in `docs/`, fills in sections now knowable from the code and requirements. Skipped automatically when there's no `docs/GUIDE.md`.
5. **Handoff** — runs `/handoff end` to update `HANDOFF.md` and produce the session summary.
6. **Commit & push** — a single commit covering everything (including `HANDOFF.md`), pushed to the current branch.

---

### `/docs-review`

A deep review-and-update pass over every document in a project's `docs/` (or `documentation/`) folder.

- **Per-document review** — reads each document in full, flagging incomplete sections, `TBD`/placeholder content, and anything that has drifted from the current code or requirements.
- **Cross-reference checks** — verifies identifiers, cross-document links, terminology, and duplicated facts agree across the whole suite.
- **Update & backfill** — after a findings-table confirmation, fixes stale content, backfills sections now knowable from the code/requirements/tests, and repairs cross-references (scoped `[TBD]`s where information genuinely doesn't exist yet).
- **Composite PDF** — if the folder contains a combined PDF, locates its `.py` build script and re-runs it to regenerate the PDF.

---

## License

MIT — see [LICENSE](LICENSE).
