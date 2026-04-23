# Brain — Gemini Instructions

> This file is a session-start stub. The full operator contract is in `brain/MANUAL.md`.

Canonical operator launcher: `brain-gemini`
Canonical close command: `brain-meditate`

## Session start sequence

1. Read `brain/persona/persona.md` — who you are working for and how to behave
2. Read `brain/goals/goals.md` — what the operator is trying to accomplish
3. Read `brain/MANUAL.md` §1–2 — paths, truth, and state
4. Present a short briefing and wait for operator authorization before executing tasks

## Hot-path rules

- **Credentials:** Never store. Use `{{placeholder}}`.
- **No implicit execution:** No background processes without explicit operator invocation.
- **Ask before building:** Stop and confirm when asked open-ended exploration questions.
- **Prefer reversible actions.** Flag destructive operations before running them.

## Key paths

- `brain/MANUAL.md` — full operator contract
- `brain/persona/persona.md` — identity and behavior
- `brain/goals/goals.md` — current priorities
- `brain/ops/tasks/queue/` — pending tasks
- `work/logs/` — session and operational logs

## Setup

If this is a fresh install, run `scripts/bin/brain-bootstrap-new-user` first.
