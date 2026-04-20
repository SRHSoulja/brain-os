---
title: "Standing Orders"
type: "governance"
status: "active"
version: "1"
date: "2026-03-18"
owner: "Arson"
---

# Standing Orders

> **Authority:** Categorical pre-authorizations for the Brain to act without per-instance human approval. Each order defines a trigger, a bounded action, and a stop condition. Governed by ADR-0003 (Control-First Architecture).

These are not tasks. They are permanent permissions for specific, narrow, deterministic maintenance actions. They exist so the Brain can keep itself healthy between human-directed sessions without expanding its own authority.

## Rules

- Standing orders are **maintenance only** — they do not create features, make business decisions, or touch production
- Each order has a **trigger** (what activates it), an **action** (what the Brain may do), and a **stop condition** (when it must halt and escalate)
- Actions must be **deterministic and reversible** — no LLM judgment, no destructive operations
- Standing orders **cannot modify governance, safety, or CLAUDE.md**
- Standing orders **cannot admit tasks to the queue** — they may propose candidates but not self-authorize work
- A standing order that fails or hits its stop condition **must log the failure and wait for the human**
- This file is the canonical authorization source. If an action is not listed here, it is not authorized.

---

## SO-001: Apply approved remedies for known service failures

**Trigger:** brain-remedy scan detects an active issue matching a pattern with `remedy_approved: true`

**Action:** Execute `brain-remedy --apply <remedy_id>` — runs the approved command and verifies the result

**Scope:** Only patterns in `work/inbox/diagnostics/patterns.json` with `remedy_approved: true` AND matching the hardcoded `APPROVED_REMEDY_WHITELIST` in `brain-remedy`. Currently approved: `strikes-stale-pm2` (pm2 restart), `strikes-timeout` (pm2 restart for timeout variant), and `count-drift` (brain-resume sync). Adding new approved remedies requires a code change to the whitelist in `brain-remedy`, not just a JSON edit.

**Stop condition:** Verify step fails, remedy_approved is false, ID not in hardcoded whitelist, or the same remedy has been applied 3+ times in 24 hours (indicates the fix isn't holding — escalate to human). The 3x/24h limit is enforced via `applied_timestamps` array in patterns.json with rolling window check.

**Write surfaces:** patterns.json (times_applied counter + applied_timestamps), events.log

**Why this is safe:** The approved set is human-curated and conservative. Each remedy has been manually applied and verified at least once before approval. The verify step catches failures. The repeat-limit prevents blind retry loops. The hardcoded whitelist prevents JSON injection of new approved remedies. Adding a new remedy requires modifying tool source code, which requires a human-approved commit.

---

## SO-002: Archive completed tasks older than 30 days

**Trigger:** `brain/ops/tasks/completed/` contains more than 75 task files

**Action:** Run `brain-task-archive --days 30`

**Scope:** Moves completed task markdown + completion JSON + run JSON to `completed/archive/YYYY-MM/`. Updates checksum manifest. Logs to events.log.

**Stop condition:** brain-task-archive reports an error, or brain-state-check shows DRIFT after archival

**Write surfaces:** brain/ops/tasks/completed/ (move files), brain/ops/tasks/completed/archive/ (destination), events.log

**Why this is safe:** Archival is a move, not a delete. The files are preserved in a dated subdirectory. brain-state-check continues to validate immutability. The threshold (75 files) prevents premature archival.

---

## SO-003: Fix devlog frontmatter before it breaks brain-export

**Trigger:** brain-state-check reports `STRUCTURAL_DRIFT` for devlogs with missing frontmatter

**Action:** Add minimal YAML frontmatter to the affected file: title derived from the first `# Heading`, date from the filename, type "devlog"

**Scope:** Only files in `work/logs/devlog/` that are missing frontmatter. Does not modify existing frontmatter. Does not change file content below the frontmatter block.

**Stop condition:** File has no `# Heading` to derive a title from, file is not a devlog (wrong directory somehow), or more than 3 files need fixing in one pass (suggests a systemic issue — escalate)

**Write surfaces:** work/logs/devlog/ (add frontmatter to existing files only)

**Why this is safe:** This is the exact fix we applied manually on 2026-03-17 when 3 devlogs without frontmatter broke brain-export. The fix is deterministic (title from heading, date from filename), non-destructive (prepends frontmatter, doesn't change body), and prevents a known pipeline break.

---

## SO-004: Write diagnostic brief for new unmatched service failures

**Trigger:** brain-monitor detects a service in `down-unexpected` state AND no existing pattern in patterns.json matches the alert text

**Action:** Create a new diagnostic brief in `work/inbox/diagnostics/` with: event type, subject (service name), the error detail from brain-monitor, timestamp, confidence "low", empty remedy fields, `resolved: false`

**Scope:** Creates one markdown file per new incident type. Does not write patterns.json (no auto-pattern-matching — that requires human review). Does not attempt diagnosis or remedy.

**Stop condition:** More than 3 new briefs created in 24 hours (suggests cascading failure — escalate instead of documenting), or the service is classified as `inactive-until-stream`

**Write surfaces:** work/inbox/diagnostics/ (new files only)

**Why this is safe:** This is pure capture, not action. The brief is a structured record of what happened, written to the diagnostic surface that brain-resume already reads. No remediation, no state mutation, no pattern promotion. The human decides what to do with it at next session start.

---

## SO-005: Verify PM2 process health after WSL restart

**Trigger:** brain-resume detects that the WSL cron daemon was not running (the cron health check fires), suggesting a WSL restart occurred

**Action:** Check that all expected WSL PM2 services are running (currently: strikes-engine, brain-export-webhook). For any missing service, log which service is missing and surface it in brain-resume's Pending Actions. Do NOT auto-restart — just detect and report.

**Scope:** Read-only check against `pm2 list`. Reports missing services. Does not start, stop, or restart any process.

**Stop condition:** N/A — this is detection only, never mutates

**Write surfaces:** None (detection result is surfaced in brain-resume's existing Pending Actions section)

**Why this is safe:** This is purely read-only detection. It caught the brain-export-webhook being silently dead on 2026-03-18. The action is reporting, not restarting — the human or an approved remedy handles the actual fix.

---

## SO-006: Restart VE core PM2 services on crash detection

**Trigger:** brain-health-sweep (with `--host=remote`) detects that brain-agent, brain-monitor, or brain-dashboard fail their HTTP health probe

**Action:** Execute `pm2 restart <service>` for each failed service, then verify PM2 reports the process as `online` (HTTP health is checked on the next sweep cycle, since services like brain-agent take 20s+ to warm up)

**Scope:** Only the three core VE PM2 services: brain-agent (port 8798), brain-monitor (port 8799), brain-dashboard (port 8800). Ollama is Windows-side and cannot be restarted from WSL -- it is reported but not acted on. The reverse-tunnel service is excluded (autossh manages its own reconnection).

**Stop condition:** The same service has been restarted 3+ times in 24 hours (fix not holding -- escalate to human via Discord alert). Verification failure after restart is logged but does not block subsequent services. Rate state tracked in `work/logs/.ve-restart-timestamps`.

**Write surfaces:** work/logs/.ve-restart-timestamps (rate tracking), work/logs/health-sweep.log (via --log), events.log (via existing remedy logging)

**Why this is safe:** PM2 restart is the standard recovery for Node.js service crashes. These services are stateless HTTP servers -- restart has no data loss risk. The 3x/24h rate limit prevents blind retry loops. Ollama (the only stateful service on VE) is explicitly excluded. The restart runs on the same machine where the services live, so there is no remote execution risk. Each restart is verified by re-probing the health endpoint.

---

## SO-007: Brain-to-Body remote command relay

**Trigger:** `brain-ve-run <command-name>` called from a laptop Brain tool or human operator during a Claude Code session

**Action:** Execute the fixed command string mapped to `<command-name>` on a remote seat via SSH. The relay script (`brain-remote-relay`) validates the name against a hardcoded whitelist, enforces a 60-second per-command rate limit, and executes the resolved command.

**Scope:** Only the following commands are authorized:

| Name | Resolves to | Effect |
|------|-------------|--------|
| `brain-sync` | `brain-sync` | Pull repos, commit agent outputs, auto-deploy |
| `health-sweep` | `brain-health-sweep --host=remote --heal --log` | Health check with SO-001/SO-006 healing |
| `spotcheck` | `brain-spotcheck` | Clip knowledge quality check |
| `export-deploy` | `brain-export --deploy` | Rebuild and deploy knowledge JSON to production |

**Explicitly excluded:** Task execution, PM2 control, arbitrary shell commands, any command not in the table above. No argument passthrough -- the command name is the only input. Adding a new command requires modifying `brain-remote-relay` source code AND updating this table.

**Stop condition:** Rate limit rejection (same command within 60s). SSH connection failure (tunnel down). Invalid or unrecognized command name.

**Write surfaces:** `~/.brain-remote-relay/` on the remote seat (rate timestamp files only). All other writes are performed by the whitelisted commands themselves within their own documented surfaces.

**Why this is safe:** The whitelist is hardcoded (not a config file that could be injected). No arguments are passed through — the relay resolves a fixed name to a fixed string. The rate limit prevents accidental loops. SSH key auth is the only access path. Each whitelisted command is already safe to run at any time (idempotent or additive). The relay cannot be expanded without a source code change, which requires a human-approved commit.

---

## Execution environment constraint

Standing orders execute via **WSL cron or WSL PM2** on an always-on remote seat (ethernet, auto-start). SO-001 through SO-007 fire 24/7 regardless of operator laptop state. The laptop is only required for human-supervised Claude Code sessions.

## Consuming systems

| Standing order | Consumer | Status |
|---------------|----------|--------|
| SO-001 | brain-health-sweep --heal | **Operationalized** — auto-applies approved remedies during unified health check |
| SO-002 | brain-task-archive + brain-meditate hook | **Operationalized** — threshold check runs at every meditate |
| SO-003 | brain-fix-frontmatter + brain-meditate hook | **Operationalized** — auto-fix runs at every meditate |
| SO-004 | brain-resume unmatched-failure capture | **Operationalized** — creates low-confidence briefs for unmatched down services |
| SO-005 | brain-resume PM2 check | **Operationalized** — checks expected services at every brain-resume |
| SO-006 | brain-health-sweep --host=remote --heal | **Operationalized** — restarts crashed remote-seat core PM2 services (3x/24h limit) |
| SO-007 | brain-remote-run (laptop) + brain-remote-relay (remote) | **Operationalized** — 4 whitelisted commands, 60s rate limit, SSH transport |

## Amendment process

Standing orders are added or modified only by human direction. The Brain may propose a new standing order (via a candidate in `work/inbox/candidates/`), but promotion to this file requires explicit human approval. No standing order may authorize its own expansion.
