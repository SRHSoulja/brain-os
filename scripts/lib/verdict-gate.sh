#!/bin/bash
# verdict-gate.sh — shared verdict reading + freshness + gate logic
# Source this file: . "${BRAIN_DIR:-$HOME/brain}/scripts/lib/verdict-gate.sh"
#
# Functions:
#   verdict_read          — read verdict JSON, refresh if stale (>5min for gates)
#   verdict_status        — print current status (OK|DRIFT|STALE|CONFLICT)
#   verdict_summary       — print summary string
#   verdict_issue_count   — print issue count
#   verdict_gate_allow    — exit 0 if OK/STALE, exit 1 if DRIFT/CONFLICT
#   verdict_gate_strict   — exit 0 if OK only, exit 1 otherwise
#   verdict_gate_message  — print gate result message for terminal
#
# All functions read fresh state — no caching across calls.

TOOLS="${TOOLS:-${BRAIN_DIR:-$HOME/brain}/scripts}"
. "$TOOLS/lib/brain-paths.sh"
_VERDICT_FRESHNESS=300  # 5 minutes for gate checks (stricter than display)

# Read verdict, refreshing if stale or missing. Sets _V_* variables.
# Single python3 invocation via verdict-reader.py — no cross-read risk.
verdict_read() {
  # Refresh if missing, older than freshness window, or currently blocking.
  # A DRIFT/CONFLICT verdict that's "fresh" by age is still stale by intent:
  # the operator may have fixed the issue since the last check.
  local _needs_refresh=false
  if [[ ! -f "$_VERDICT_JSON" ]]; then
    _needs_refresh=true
  else
    local age=$(( $(date +%s) - $(stat -c %Y "$_VERDICT_JSON") ))
    if [[ $age -gt $_VERDICT_FRESHNESS ]]; then
      _needs_refresh=true
    else
      # If the on-disk verdict is a blocking status, always re-check
      local _peek_status
      _peek_status=$(python3 -c "import json; print(json.load(open('$_VERDICT_JSON')).get('status','UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")
      if [[ "$_peek_status" == "DRIFT" || "$_peek_status" == "CONFLICT" ]]; then
        _needs_refresh=true
      fi
    fi
  fi
  if $_needs_refresh; then
    "$_STATE_CHECK" --quiet > /dev/null 2>&1 || true
  fi

  if [[ ! -f "$_VERDICT_JSON" ]]; then
    _V_STATUS="DRIFT"
    _V_SUMMARY="Verdict file missing after refresh attempt"
    _V_ISSUE_COUNT=1
    return 1
  fi

  # Single parse: verdict-reader.py outputs tab-separated:
  # status \t summary \t issue_count \t timestamp \t queued \t active \t completed
  local _vr_output
  _vr_output=$(python3 "$_VERDICT_READER" "$_VERDICT_JSON" 2>/dev/null) || true

  if [[ -n "$_vr_output" ]]; then
    IFS=$'\t' read -r _V_STATUS _V_SUMMARY _V_ISSUE_COUNT _V_TIMESTAMP _V_QUEUED _V_ACTIVE _V_COMPLETED <<< "$_vr_output"
  else
    _V_STATUS="DRIFT"
    _V_SUMMARY="Unable to read verdict"
    _V_ISSUE_COUNT=0
  fi

  _V_STATUS="${_V_STATUS:-DRIFT}"
  _V_SUMMARY="${_V_SUMMARY:-Unable to read verdict}"
  _V_ISSUE_COUNT="${_V_ISSUE_COUNT:-0}"
}

verdict_status() {
  verdict_read
  echo "$_V_STATUS"
}

verdict_summary() {
  verdict_read
  echo "$_V_SUMMARY"
}

verdict_issue_count() {
  verdict_read
  echo "$_V_ISSUE_COUNT"
}

# Gate: allow OK and STALE (with warning), block DRIFT and CONFLICT
# Returns 0=allow, 1=block
verdict_gate_allow() {
  verdict_read
  case "$_V_STATUS" in
    OK) return 0 ;;
    STALE) return 0 ;;
    DRIFT|CONFLICT) return 1 ;;
    *) return 1 ;;
  esac
}

# Gate: allow OK only, block everything else
# Returns 0=allow, 1=block
verdict_gate_strict() {
  verdict_read
  case "$_V_STATUS" in
    OK) return 0 ;;
    *) return 1 ;;
  esac
}

# Print gate message. Call after verdict_read.
# Usage: verdict_gate_message "action description"
verdict_gate_message() {
  local action="${1:-operation}"
  case "$_V_STATUS" in
    OK)
      # Silent on OK
      ;;
    STALE)
      echo "Warning: brain verdict is STALE — proceeding with $action with caution."
      [[ "$_V_ISSUE_COUNT" != "0" ]] && echo "  $_V_ISSUE_COUNT issue(s): $_V_SUMMARY"
      ;;
    DRIFT)
      echo "Blocked by brain verdict: DRIFT — $action halted."
      echo "  $_V_ISSUE_COUNT issue(s): $_V_SUMMARY"
      echo "  Run brain-state-check to diagnose, then fix issues before retrying."
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) | verdict | state-check | DRIFT $_V_SUMMARY | blocked $action" >> "${BRAIN_DIR:-$HOME/brain}/work/logs/healing-events.log" 2>/dev/null || true
      ;;
    CONFLICT)
      echo "Blocked by brain verdict: CONFLICT — $action halted immediately."
      echo "  $_V_ISSUE_COUNT issue(s): $_V_SUMMARY"
      echo "  Resolve conflicts before any mutations. Run brain-state-check for details."
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) | verdict | state-check | CONFLICT $_V_SUMMARY | blocked $action" >> "${BRAIN_DIR:-$HOME/brain}/work/logs/healing-events.log" 2>/dev/null || true
      ;;
    *)
      echo "Blocked by brain verdict: UNKNOWN status '$_V_STATUS' — treating as DRIFT."
      echo "  Run brain-state-check to refresh verdict."
      ;;
  esac
}
