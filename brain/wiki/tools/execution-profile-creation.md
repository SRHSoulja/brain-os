---
title: "Execution Profile Creation"
type: "system"
applies_to: "all"
---

# Execution Profile Creation

Execution profiles live in `brain/ops/execution-profiles.json`. Each profile
describes a reasoning stance or an isolated capability and is resolved by
`brain-subagent-dispatch --profile <id>`. Profiles carry routing hints
(`preferred_runtimes`, `preferred_models`), prompt scaffolding (`preamble_file`,
`context_tier`), timeouts, output limits, and — when the work needs a scoped
sub-agent — an `isolation_fields` block.

## Canonical invocation

```
brain-subagent-dispatch --profile <id> --question "<prompt>"
```

`brain-subagent-dispatch` is the single authoritative consumer of execution
profiles. It reads the profile via `brain-profile-meta`, resolves routing + model,
builds the prompt, and (for profiles with `isolation_fields`) applies every
isolation flag to the runtime invocation. Do not invoke agent CLIs directly for
profile-scoped work.

## Isolation fields (optional, profile-level tool/context scoping)

When a sub-agent should see only a minimal tool surface (e.g., to call a
specific MCP and nothing else), add these fields to the profile.
`brain-subagent-dispatch` is the canonical consumer. Runtime coverage differs
per field — see the rightmost column. Absent fields mean "no restriction."

| Field | Type | Purpose | Runtime coverage |
|---|---|---|---|
| `allowed_tools` | list[str] | Built-in tool names the sub-agent may call. Enforce via `policy_file`. | gemini only |
| `allowed_mcp_servers` | list[str] | MCP server names allowed. Passed as `--allowed-mcp-server-names` to gemini. | gemini only |
| `allowed_extensions` | list[str] | CLI extensions to load (reduces context). Passed as `-e` to gemini. | gemini only |
| `policy_file` | str | Path (relative to `$BRAIN` or absolute) to a Gemini Policy Engine TOML; denied tools are excluded from the model's registry. | gemini only |
| `neutral_cwd` | str | Directory to `cd` into before invoking the runtime. Suppresses the runtime CLI's cwd-based auto-loading of per-agent project files (`CLAUDE.md` / `AGENTS.md` / `GEMINI.md`) and seat memory folders. Context-boundary tool, not a universal token-saving default: appropriate for bounded/context-fed profiles or profiles whose domain lives outside the main repo; harmful for profiles whose `task_types` imply repo discovery (the subagent's Glob/Grep/Read resolve relative to cwd). | claude-code, codex, gemini |
| `lifecycle_blocked` | bool | When `true` (default when absent), consumer sets `BRAIN_DISPATCH_ACTIVE=1`, causing lifecycle scripts (`brain-meditate`, `brain-checkpoint`, `brain-handoff`, `brain-session-end-commit`) to refuse execution. Subagents themselves still execute within their profile + runtime limits; this field only blocks operator-seat lifecycle mutations from being triggered from inside a subagent context. Set `false` to opt out. | all runtimes |
| `approval_mode` | str | Passed as `--approval-mode` to gemini. `plan` (read-only, dispatch default when absent) / `yolo` (auto-approve — required for non-interactive MCP calls) / `default`. | gemini only |

**Rule:** tool/context isolation belongs in execution profiles. Do not create
one-off wrappers that bypass profile governance — add the isolation fields to
the profile and let dispatch apply them.

### Known isolation limitation

**HOME is inherited** by runtimes that keep extension binaries and auth
credentials under `~/.<runtime>/`. Overriding HOME to fully isolate the
sub-agent would break MCP authentication. The `allowed_mcp_servers` +
`allowed_extensions` + `policy_file` combo reduces the attack surface to the
target MCP itself without requiring HOME isolation.

## SOP — adding a new profile

**Prerequisites:** No existing profile covers the task type; work recurs or is substantial.

1. Write a preamble → `ai/prompts/core/<name>-system-preamble.md`
2. Add the profile object to `brain/ops/execution-profiles.json`. Minimum keys: `profile_id`, `description`, `preferred_runtimes`, `execution_mode`, `context_tier`, `preamble_file`, `timeout_seconds`.
3. If the profile should run as a scoped sub-agent, add an `isolation_fields`-compatible set: `allowed_mcp_servers`, `allowed_extensions`, `policy_file`, `neutral_cwd`, `approval_mode`, and any applicable `lifecycle_blocked` entries.
4. Dry-run: `brain-subagent-dispatch --profile <name> --question "test" --dry-run`. Confirm the preamble appears as the opening system instruction, routing picks the intended runtime, and (for isolated profiles) the `Isolation:` block surfaces every field you set.
5. If `allowed_mcp_servers` is set, also supply a matching `policy_file` — dispatch does not enforce `allowed_tools` without one.

**Expected dry-run output:** preamble as system instruction + the `Isolation:`
summary whenever `neutral_cwd` is set on any target, or any gemini-only field is set on a gemini-targeted profile.

**If dry-run shows a generic prompt:** verify `preamble_file` is set in the
profile and the file exists at `$BRAIN/<preamble_file>`.
