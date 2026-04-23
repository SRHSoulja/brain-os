# Brain — Codex / OpenAI Agents Instructions

> This file is a session-start stub. The full operator contract is in `brain/MANUAL.md`.

Canonical operator launcher: `brain-codex`
Canonical close command: `brain-meditate`

## Session start sequence

1. Read `brain/persona/persona.md` — who you are working for and how to behave
2. Read `brain/goals/goals.md` — what the operator is trying to accomplish
3. Read `brain/MANUAL.md` §1–2 — paths, truth, and state
4. Present a short briefing and wait for operator authorization before executing tasks

## Hot-path rules

- **Credentials:** Never store. Use `{{placeholder}}`.
- **No implicit execution:** No background processes without explicit operator invocation.
- **Ask before building:** Stop and confirm when asked to "find better solutions" or similar.
- **Prefer reversible actions.** Flag destructive operations before running them.
- **Session close is not optional.** Codex has no Stop/SessionEnd hook — always close with `brain-meditate --agent codex`. That's how Codex gets the same session-end commit sweep Claude and Gemini receive automatically.
- **Edit/Write hook coverage is ADVISORY on Codex.** Codex hooks only fire on Bash; file-write gates cannot physically block non-Bash writes. Follow the rules yourself.
- **Cross-seat hard rules apply.** Discord Reply Gate, 1M-model authorization, and Resolve-Before-Assuming tool lookup are the same across Claude/Codex/Gemini. See `brain/governance/multi_ai_rules.md §9`.

## Key paths

- `brain/MANUAL.md` — full operator contract
- `brain/persona/persona.md` — identity and behavior
- `brain/goals/goals.md` — current priorities
- `brain/ops/tasks/queue/` — pending tasks
- `work/logs/` — session and operational logs

## Setup

If this is a fresh install, run `scripts/bin/brain-bootstrap-new-user` first.
