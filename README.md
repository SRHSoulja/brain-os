# Multi-Agent Brain

A bootstrappable multi-agent operating system for Claude Code, Codex, and Gemini CLI. Clone it, fill in your goals and personality, and your agents share a task queue, governance model, and session lifecycle from day one.

## What's included

- **Task system** — create, claim, execute, complete tasks with proof-of-execution and immutable records
- **Session lifecycle** — bootstrap, meditate, handoff, checkpoint across Claude Code, Codex, and Gemini seats
- **Governance** — standing orders, capability profiles, dispatch routing, autonomous gate
- **Services** — brain-commands, brain-monitor, brain-clippy (Ollama-powered AI assistant), brain-agent
- **Dispatch** — route work to the right model/agent via execution profiles

## 5-minute setup

### Prerequisites

- bash 4+, python3, git
- One or more of: Claude Code CLI, Codex CLI, Gemini CLI
- (Optional) Ollama for local AI features (brain-clippy, brain-agent)

### Install

```bash
git clone <this-repo> ~/brain
cd ~/brain
bash scripts/bin/brain-bootstrap-new-user
```

The bootstrap script:
- Creates `~/bin/` symlinks for all brain commands
- Creates required ops directories
- Copies settings templates to `.claude/`, `.codex/`, `.gemini/`
- Prints a checklist of what to fill in next

### Configure your identity

```bash
# Fill in your name, role, and operating style
editor brain/persona/persona.md

# Fill in your current goals and projects
editor brain/goals/goals.md
```

### Start your first session

**Claude Code:**
```bash
cd ~/brain
claude
# Bootstrap runs automatically on session start
```

**Codex:**
```bash
cd ~/brain
brain-codex-enter
```

**Gemini:**
```bash
cd ~/brain
brain-agent-bootstrap --agent gemini
```

## First task

```bash
brain-task "Set up my first real task" --p2 --why "testing the system"
brain-task-claim <TASK-ID> claude-code 15
# ... do the work ...
brain-task-complete <TASK-ID> --by claude-code --output "done" --execution-note "first run"
brain-task-confirm <TASK-ID>
```

## Key commands

| Command | What it does |
|---|---|
| `brain-task "description"` | Create a new task |
| `brain-state-check` | Full system health check |
| `brain-checkpoint "reason"` | Save a recovery point |
| `brain-meditate` | Close a Claude Code session cleanly |
| `brain-task-claim <ID> <agent>` | Claim a task for execution |
| `brain-task-complete <ID> --by <agent> --output "..."` | Complete a task |
| `brain-resume` | Rebuild state after compaction or idle |
| `brain-subagent-dispatch --profile <name> --question "..."` | Dispatch work to a sub-agent |

## Multiple seats

This brain is designed to be shared across agents. Each seat has its own bootstrap and close sequence, but they share the same task queue, governance model, and state files.

- **Claude Code** — uses SessionStart hook for automatic bootstrap; `brain-meditate` to close
- **Codex** — `brain-codex-enter` to open, `brain-meditate --agent codex` to close
- **Gemini** — `brain-agent-bootstrap --agent gemini` to open, `brain-meditate --agent gemini` to close

## Project layout

```
brain/
  MANUAL.md          — full operator contract (read this)
  governance/        — standing orders, capability profiles, routing policy
  persona/           — your identity (fill this in)
  goals/             — your current goals (fill this in)
  services/          — brain-commands, brain-clippy, brain-monitor, brain-agent
  wiki/              — tool docs and system architecture notes
  ops/               — runtime state (gitignored except tasks/completed/)
scripts/
  bin/               — all brain-* commands
CLAUDE.md            — Claude Code session stub
AGENTS.md            — Codex session stub
GEMINI.md            — Gemini session stub
```

## License

MIT
