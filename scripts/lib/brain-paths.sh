#!/bin/bash
# brain-paths.sh — Single source of truth for all Brain surface paths
#
# Source this file in any tool that reads or writes Brain state surfaces.
# When a surface moves (e.g., to brain/ops/derived/), update HERE only.
#
# Usage: . "$TOOLS/lib/brain-paths.sh"   (requires $TOOLS or $HOME)
#
# ADR-0004 Phase 0a: Centralize path definitions so future migrations
# only need one-line changes instead of multi-tool surgery.

_BRAIN="${BRAIN:-$HOME/brain}"

# Local override: if scripts/lib exists in the current brain dir, use it for TOOLS
if [[ -d "$_BRAIN/scripts/lib" ]]; then
  _TOOLS="${TOOLS:-$_BRAIN/scripts}"
else
  _TOOLS="${TOOLS:-${BRAIN_DIR:-$HOME/brain}/scripts}"
fi

# ── Operational state surfaces ─────────────────────────────────────
_EVENTS_LOG="$_BRAIN/brain/ops/events.log"
_EVENTS_JSONL="$_BRAIN/brain/ops/events.jsonl"
_VERDICT_JSON="$_BRAIN/brain/ops/derived/state-verdict.json"
_VERDICT_MD="$_BRAIN/brain/ops/derived/state-verdict.md"
_SYSTEM_STATE_MD="$_BRAIN/brain/ops/derived/system-state.md"
_SYSTEM_STATE_JSON="$_BRAIN/brain/ops/derived/system-state.json"
_SESSION_RESUME="$_BRAIN/brain/index/session-resume.md"

# ── Directories ────────────────────────────────────────────────────
_OPS_TASKS_DIR="$_BRAIN/brain/ops/tasks"
_DIAGNOSTICS_DIR="$_BRAIN/work/inbox/diagnostics"
_DIAGNOSTICS_PATTERNS="$_DIAGNOSTICS_DIR/patterns.json"

# ── Instance identity ──────────────────────────────────────────────
_BRAIN_INSTANCE="${BRAIN_INSTANCE:-local}"

# Guard: call this in tools that write local-authority surfaces.
# Exits with error if running on cloud instance.
_require_local() {
  if [[ "$_BRAIN_INSTANCE" == "cloud" ]]; then
    echo "ERROR: $(basename "$0") writes to local-authority surfaces. Cannot run on cloud instance." >&2
    exit 1
  fi
}

# ── Well-known file paths ─────────────────────────────────────────
_PRIORITY_QUEUE="$_BRAIN/work/logs/priority-queue.md"

# pq_items <section>
#   Extract bullet items from a priority queue section (P1 or P2).
#   Returns one line per item (leading "- " preserved). Empty if none.
#   Filters out placeholders (_None_, _(none)_, _(None)_) and non-bullet lines.
#   Usage:
#     items=$(pq_items P1)       # get item text
#     count=$(pq_items P2 | grep -c . || echo 0)  # get count
pq_items() {
  local section="$1"
  [[ ! -f "$_PRIORITY_QUEUE" ]] && return 0
  sed -n "/^## ${section}/,/^## /p" "$_PRIORITY_QUEUE" | grep '^\- ' || true
}

# ── Active seat ───────────────────────────────────────────────────
_ACTIVE_SEAT_FILE="$_BRAIN/brain/ops/.brain-active-seat.json"

# canonical_agent <name>
#   Normalize agent identity strings to canonical form.
canonical_agent() {
  case "${1:-claude-code}" in
    claude|claude-code) echo "claude-code" ;;
    codex) echo "codex" ;;
    gemini|gemini-cli) echo "gemini" ;;
    *) echo "$1" ;;
  esac
}

# seat_agent_check <claimed_agent> <context>
#   Compare claimed agent identity against the active seat.
#   Returns 0 if match or seat file missing. Returns 1 on mismatch.
#   Prints warning to stderr on mismatch.
seat_agent_check() {
  local claimed="$1"
  local context="${2:-unknown}"
  [[ ! -f "$_ACTIVE_SEAT_FILE" ]] && return 0
  local seat_agent
  seat_agent=$(python3 -c "import json; print(json.load(open('$_ACTIVE_SEAT_FILE')).get('assistant',''))" 2>/dev/null) || return 0
  seat_agent="$(canonical_agent "$seat_agent")"
  claimed="$(canonical_agent "$claimed")"
  if [[ "$seat_agent" != "$claimed" ]]; then
    echo "WARNING: Agent identity mismatch in $context: claimed=$claimed but active seat=$seat_agent" >&2
    return 1
  fi
  return 0
}

# ── Tool paths ─────────────────────────────────────────────────────
_VERDICT_READER="$_TOOLS/lib/verdict-reader.py"
_STATE_CHECK="$_TOOLS/bin/brain-state-check"

# ── Runtime surface bootstrap ───────────────────────────────────────
# Ensure required runtime files/directories exist on fresh clones (e.g. VE)
# even when high-churn artifacts are intentionally untracked in git.
ensure_runtime_surfaces() {
  mkdir -p \
    "$_BRAIN/brain/ops" \
    "$_BRAIN/brain/wiki/pages" \
    "$_BRAIN/brain/wiki/systems" \
    "$_BRAIN/work/logs"

  # Append-only runtime logs (safe to touch)
  touch \
    "$_EVENTS_LOG" \
    "$_EVENTS_JSONL" \
    "$_BRAIN/work/logs/post-commit.log" \
    "$_BRAIN/work/logs/seat-usage-history.jsonl" \
    "$_BRAIN/work/logs/wiki-impact.log"

  # Rebuildable wiki index/manifest placeholders for first-run reliability.
  # Never overwrite real generated files.
  if [[ ! -s "$_BRAIN/brain/wiki/index.json" ]]; then
    cat > "$_BRAIN/brain/wiki/index.json" <<'EOF'
{"generated_at":"","indexed_pages":0,"pages":[],"tags":[],"links":[],"links_to":{}}
EOF
  fi

  if [[ ! -s "$_BRAIN/brain/wiki/pages/manifest.json" ]]; then
    cat > "$_BRAIN/brain/wiki/pages/manifest.json" <<'EOF'
{"generated_at":"","folder":"pages","total_pages":0,"hand_authored_pages":0,"auto_stub_pages":0,"topic_buckets":[],"pages":[]}
EOF
  fi

  if [[ ! -s "$_BRAIN/brain/wiki/systems/manifest.json" ]]; then
    cat > "$_BRAIN/brain/wiki/systems/manifest.json" <<'EOF'
{"generated_at":"","folder":"systems","total_pages":0,"hand_authored_pages":0,"auto_stub_pages":0,"topic_buckets":[],"pages":[]}
EOF
  fi
}
