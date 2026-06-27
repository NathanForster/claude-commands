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

Updates the `Status` column in both the requirements register and traceability matrix with one of: `Baselined`, `Implemented`, `Verified`, `Deferred`, or `Deleted`.

---

## License

MIT — see [LICENSE](LICENSE).
