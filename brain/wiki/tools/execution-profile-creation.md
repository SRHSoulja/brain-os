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

## Dispatch lifecycle boundary

Execution profiles summon sub-agents through `brain-subagent-dispatch`. The
framework separates two authorities:

- **Runtime authority (sub-agent layer)** — the sub-agent can read, reason,
  call tools, and produce output within the limits of its execution profile
  and the target runtime. Sub-agents execute; that is the whole point of
  dispatching them.
- **Lifecycle authority (operator-seat layer)** — bootstrap, seat claim,
  session-start / session-end commits, meditation closeouts, checkpoints, and
  handoffs belong to the main interactive operator session. These must never
  be triggered from inside a dispatched sub-agent.

`BRAIN_DISPATCH_ACTIVE=1` is the narrow separator. Dispatch exports it before
invoking the runtime; any lifecycle tool that checks this flag refuses to run
when it is set. `cwd` is unrelated to this boundary: it is task context.
A sub-agent may run from the main repo, a staging tree, or a neutral
directory; lifecycle suppression is independent of that choice.

### What is suppressed during dispatch, regardless of cwd

| Surface | Mechanism |
|---|---|
| bootstrap / agent-bootstrap hook | the adapter hook checks `BRAIN_DISPATCH_ACTIVE=1` and exits cleanly without claiming the seat |
| seat claim surface (`.brain-active-seat.json` equivalent) | bootstrap is the writer; skipped per above |
| session-start brief / resume / state-verdict regeneration | these are bootstrap's responsibility; not rewritten during dispatch |
| active-session marker | not created |
| session-end commit (Stop-style hook) | the adapter checks `BRAIN_DISPATCH_ACTIVE=1` and exits without committing sub-agent work |
| lifecycle CLIs (`brain-meditate`, `brain-checkpoint`, `brain-handoff`, `brain-session-end-commit`) | each self-guards on `BRAIN_DISPATCH_ACTIVE=1` and refuses execution |

### What is expected to change during dispatch

- The dispatch event log gains one `SUBAGENT_DISPATCH` entry per call. That
  is the authorized write; nothing else in the operator-seat state surface
  should mutate.

### Cwd policy in this context

Because lifecycle is gated by `BRAIN_DISPATCH_ACTIVE`, not by cwd, profile
authors pick `neutral_cwd` on task-discovery grounds alone:

- Repo-discovery profiles (whose `task_types` imply Glob/Grep/Read
  exploration) should keep the main repo cwd.
- Profiles that are fully context-fed (all needed files inlined via
  `--files`) or whose domain lives outside the main repo are appropriate
  candidates for `neutral_cwd`.

### Runtime-specific caveats (agent-agnostic ≠ identical behavior)

The framework contract is shared, but low-level enforcement differs per
runtime adapter. Profile authors should understand these when writing
profiles that target a specific runtime or that plan to promote permissions.

- **Codex-style runtimes** generally propagate environment variables from
  the parent process into tool/shell subprocesses. Shell-level
  `BRAIN_DISPATCH_ACTIVE=1` guards inside lifecycle CLIs fire correctly.
- **Claude-style runtimes** inherit `BRAIN_DISPATCH_ACTIVE` into the
  runtime's own process (so the runtime's SessionStart / Stop hooks see
  the flag and suppress bootstrap), but may strip environment variables
  before spawning their Bash/tool subprocesses. Today's boundary holds
  because dispatch runs Claude-style runtimes in a read-only
  permission/plan mode that already blocks state-mutating commands.
  **If a Claude-style profile is ever promoted to a write-capable
  permission mode, it MUST land an additional non-env lifecycle guard
  before shipping** — candidates include a lockfile created by dispatch
  on entry and removed on exit, an explicit argv flag that lifecycle
  scripts recognize, or a PID-based dispatch registry. Context-boundary
  (`neutral_cwd`) and lifecycle-boundary (`BRAIN_DISPATCH_ACTIVE` +
  permission mode) are separate concerns — tightening one does not
  substitute for weakening the other.
- **Gemini-style runtimes** frequently refuse shell execution at either
  the profile's `policy_file` layer or at the model's own safety stance
  when run non-interactively. This provides equivalent lifecycle
  protection even when the env-propagation path is untested — if the
  shell never executes, shell-level env guards cannot be reached.

"Agent-agnostic" means the control plane and lifecycle contract are shared
across runtimes. The specific mechanism that enforces the contract can
differ per adapter; profile authors should rely on the contract (subagent
executes, lifecycle does not) rather than on any one enforcement mechanism.

### Verification

To verify the boundary for any profile: snapshot the lifecycle surfaces
(hash + mtime) before dispatch, run the profile end-to-end, re-snapshot,
and diff. The only expected change is the dispatch event log entry.
Any other mutation is a leak to investigate.

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
