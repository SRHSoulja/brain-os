# Brain — Claude Code Instructions

> This file is a session-start stub. The full operator contract is in `brain/MANUAL.md`.
> Read `brain/MANUAL.md` sections tagged `applies_to: all` or `applies_to: claude-code` when you need them.

Canonical operator launcher: `brain-claude`
Canonical close command: `brain-meditate`

## Session start sequence

1. Read `brain/persona/persona.md` — who you are working for and how to behave
2. Read `brain/goals/goals.md` — what the operator is trying to accomplish
3. Read `brain/MANUAL.md` §1–2 — paths, truth, and state
4. Present a short briefing and wait for operator authorization before executing tasks

## Hot-path rules

- **Credentials:** Never store. Use `{{placeholder}}`. Never delete files without per-file confirmation.
- **Operational truth:** Check live state first. Never claim from memory alone.
- **No implicit execution:** No background processes without explicit operator invocation.
- **Ask before building:** When asked to "look for better solutions", stop and ask first.

## Key paths

- `brain/MANUAL.md` — full operator contract
- `brain/persona/persona.md` — identity and behavior
- `brain/goals/goals.md` — current priorities
- `brain/ops/tasks/queue/` — pending tasks
- `brain/ops/tasks/active/` — in-progress tasks
- `work/logs/` — session and operational logs

## Setup

If this is a fresh install, run `scripts/bin/brain-bootstrap-new-user` first.
