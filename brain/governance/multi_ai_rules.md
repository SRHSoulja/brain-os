---
title: "Multi-AI Governance Rules"
type: "governance"
status: "active"
last_updated: "2026-04-09"
---

# Multi-AI Governance Rules

These rules govern how multiple AI systems interact with this brain repository.

## 1. Truth Protection

Truth files contain durable system knowledge. They are the canonical reference for all downstream consumers.

**Protected paths:**
- `brain/core-knowledge/*`
- `brain/governance/*`
- `brain/ai_context.md`
- `nodes/*/docs/**` (canonical node documentation)
- `ai/prompts/*` (system prompts)
- `ai/registry/*` (configuration files)
- `CLAUDE.md`

**Rules:**
- Only Claude Code may modify truth files, and only with human approval
- Codex and other non-human agents must never modify these protected truth paths directly
- Schema changes to truth files require explicit human approval before implementation
- Every truth modification should be accompanied by a commit message explaining the change

## 2. Suggestion Routing

All AI-generated analysis, suggestions, and insights must land in inbox areas.

**Allowed write targets for suggestions:**
- `work/inbox/` and subdirectories
- `work/logs/` (for tool output only)
- `brain/reports/` (for generated reports only)

**Rules:**
- Suggestions must never directly mutate truth documents
- No suggestion is auto-promoted to truth — human triage is required
- Suggestions should include reasoning and confidence level where applicable
- Duplicate suggestions should be deduplicated before filing

## 3. Promotion Pipeline

The path from suggestion to truth:

```
1. ANALYSIS    — AI identifies insight, gap, or improvement
2. INBOX       — Written to work/inbox/ with clear context
3. TRIAGE      — Human reviews, classifies as accept/reject/defer
4. CANDIDATE   — Accepted items staged for implementation
5. TRUTH       — Claude Code applies the change with human approval
6. DECISION    — Change logged in commit history
```

**Rules:**
- Steps 3 and 5 require human involvement — they cannot be automated
- Rejected suggestions should be archived, not deleted
- Deferred suggestions stay in inbox for future review

## 4. Agent-Specific Rules

### Codex Helm Boundaries (Hard)

- Codex execution authority is bounded to operational state and inbox surfaces.
- Codex cannot write truth layer files unless a human explicitly authorizes and routes through Claude-managed truth update flow.
- Any attempt to widen Codex write scope requires governance update first.

### Claude Code
- Primary builder and system operator
- May read and write all files
- Must follow CLAUDE.md operational rules
- Must get human approval before modifying truth files
- Must run post-task checklist after significant work
- Must update `brain/index/active-context.md` after changes

### Codex
- Bounded task-system operator when explicitly authorized by the human operator
- May inspect any file for analysis and execution context
- May mutate only state/inbox surfaces defined in `brain/governance/codex-helm-contract.md`
- Must never modify protected truth paths directly
- Must execute through gated flows (`VERDICT_GATE`, approval class, proof/core-memory gates)
- Should reference `brain/ai_context.md` and `brain/governance/codex-helm-contract.md` before execution

### Gemini CLI
- Bounded task-system operator (same tier as Codex)
- May inspect any file for analysis and execution context
- May mutate only state/inbox surfaces (same as Codex)
- Must never modify protected truth paths directly
- Must execute through gated flows (`VERDICT_GATE`, seat claim, proof-of-execution)
- Should reference `brain/ai_context.md` and `brain/governance/multi_ai_rules.md` before execution

### ChatGPT (External)
- Architecture advisor and strategic thinker
- Has no direct repository access
- Receives context through human copy/paste or exported documents
- Suggestions relayed by human into inbox or directly to Claude Code
- Should not be given raw credentials, paths, or infrastructure details

### Future AI Agents
- Must be classified in the authority model before gaining access
- Default access level: read-only analyst. This is narrower than Codex helm authority.
- Write access to truth requires explicit governance update
- Any bounded execution authority must be documented explicitly, with allowed mutation surfaces and mandatory gates.
- All new agents must be documented in `brain/ai_context.md`

## 5. Prompt Safety

- AI tools must not automatically mutate system prompts
- Prompt changes follow the same truth protection rules
- Prompt analysis results go to inbox, not directly to prompt files
- A/B testing of prompts requires human approval and rollback plan

## 6. Schema Safety

- Schema changes to brain-export JSON format require explicit approval
- Downstream consumers depend on stable schema — breaking changes must be coordinated
- Schema validation suggestions are welcome but must not auto-apply

## 7. Decision Logging

Truth changes should be traceable. The primary decision log is git history:

- Commit messages should explain why a change was made, not just what changed
- Significant governance or architecture changes should be noted in `brain/index/active-context.md`
- Controversial or reversible decisions should be documented in `work/open-questions.md`

## 8. Failure Modes

If an AI system violates these rules:
- Revert the change immediately
- Log the incident in `work/logs/`
- Review whether access controls need tightening
- Update these rules if a gap is identified

These rules are living documentation. Update them as the multi-AI architecture evolves.

## 9. Cross-Seat Hard Rules (applies_to: all)

These apply identically to Claude, Codex, and Gemini operating as the top-level agent.

- **Discord Reply Gate.** Every response to a Discord-sourced message must use the Discord reply surface — never terminal-text a Discord user. The transcript does not reach the user; only a reply-tool call does.
- **1M context model authorization.** Never auto-select, suggest as default, or dispatch to any 1M context model variant. The operator must explicitly authorize 1M use (extra billing, confirmation required).
- **Tool resolution ("Resolve Before Assuming").** Before invoking a tool by description, search `brain/wiki/tools/MAP.md`, the tool registry, and completed task titles. One exact match → use it. Multiple matches → ask. Never invent a tool name from memory.
- **Codex session close.** Codex has no native SessionStart or Stop/SessionEnd hook event. Bootstrap must run through `brain-codex` (which invokes `brain-agent-bootstrap --agent codex`). Close must run through `brain-meditate --agent codex` — that is the only deterministic way Codex sessions receive the session-end commit sweep that Claude and Gemini get automatically via Stop/AfterAgent hooks.
- **Codex Edit/Write hook coverage is ADVISORY.** Codex hooks fire on Bash tool execution only; non-Bash file writes cannot be physically blocked by PreToolUse gates. Do not treat gate presence as gate enforcement on Codex.

<!-- sovereign-agent-sig: gemini -->
