#!/usr/bin/env bash
# approval-class.sh -- Approval class enforcement library
# Source this in tools that need class gating.
#
# Usage:
#   . "$TOOLS/lib/approval-class.sh"
#   approval_class_check "brain-task-execute"
#   # Returns 0 if allowed, non-zero if blocked
#   # Sets APPROVAL_CLASS to the resolved class

BRAIN="${BRAIN_DIR:-$HOME/brain}"
TOOLS="${TOOLS:-${BRAIN_DIR:-$HOME/brain}/scripts}"

# Class mappings (deterministic)
_READONLY_LOW_RISK="brain-resume brain-state-check brain-search brain-wiki brain-core-memory-status brain-token-budget-check brain-token-report brain-context brain-clip-drift brain-spotcheck brain-proof-status brain-discord-bridge-status brain-discord-bridge-next brain-closeout-gate brain-codex-resume"
_STATE_WRITE_CONTROLLED="brain-task-admit brain-task-execute brain-task-complete brain-task-quick brain-checkpoint brain-memory-promote-core brain-core-memory-capture brain-core-memory-resolve brain-seat-claim brain-heartbeat brain-content-brief brain-discord-bridge-enqueue brain-discord-bridge-done brain-discord-bridge-reply brain-proof-start brain-proof-log brain-proof-verify brain-codex-meditate"
_EXEC_EXTERNAL="brain-ve-activate brain-ve-deactivate brain-sync brain-export"
_CONTROL_CRITICAL="brain-meditate brain-cron-update safe-rm"

APPROVAL_CLASS=""

approval_class_resolve() {
  local tool="$1"
  local base_tool
  base_tool=$(basename "$tool" 2>/dev/null || echo "$tool")

  for t in $_READONLY_LOW_RISK; do
    [[ "$base_tool" == "$t" ]] && APPROVAL_CLASS="readonly_low_risk" && return 0
  done
  for t in $_STATE_WRITE_CONTROLLED; do
    [[ "$base_tool" == "$t" ]] && APPROVAL_CLASS="state_write_controlled" && return 0
  done
  for t in $_EXEC_EXTERNAL; do
    [[ "$base_tool" == "$t" ]] && APPROVAL_CLASS="exec_or_external_side_effect" && return 0
  done
  for t in $_CONTROL_CRITICAL; do
    [[ "$base_tool" == "$t" ]] && APPROVAL_CLASS="control_plane_critical" && return 0
  done

  # Unknown = fail-closed
  APPROVAL_CLASS="control_plane_critical"
  return 0
}

approval_class_check() {
  local tool="$1"
  local agent="${2:-claude-code}"
  local autonomous="${3:-false}"

  approval_class_resolve "$tool"

  # Autonomous mode restrictions
  if [[ "$autonomous" == "true" ]]; then
    case "$APPROVAL_CLASS" in
      readonly_low_risk|state_write_controlled)
        _approval_log "APPROVAL_GRANTED" "$tool" "$APPROVAL_CLASS" "$agent" ""
        return 0
        ;;
      *)
        _approval_log "APPROVAL_DENIED" "$tool" "$APPROVAL_CLASS" "$agent" "autonomous mode restricted to low-risk/state-write"
        return 1
        ;;
    esac
  fi

  # Interactive mode: all classes allowed (human is present)
  _approval_log "APPROVAL_GRANTED" "$tool" "$APPROVAL_CLASS" "$agent" ""
  return 0
}

_approval_log() {
  local verdict="$1" tool="$2" class="$3" agent="$4" reason="$5"
  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  local events_log="$BRAIN/brain/ops/events.log"

  if [[ -f "$events_log" ]]; then
    . "$TOOLS/lib/brain-event.sh" 2>/dev/null || true
    if type brain_event >/dev/null 2>&1; then
      brain_event "$verdict" "tool=$tool class=$class agent=$agent${reason:+ reason=$reason}" 2>/dev/null || true
    else
      echo "$ts $verdict tool=$tool class=$class agent=$agent${reason:+ reason=$reason}" >> "$events_log" 2>/dev/null || true
    fi
  fi
}
