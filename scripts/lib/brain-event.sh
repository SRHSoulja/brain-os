#!/bin/bash
# brain-event.sh — Append events to both events.log (legacy) and events.jsonl (structured)
# Source this file or call brain_event directly.
#
# Usage: brain_event EVENT_TYPE "metadata..."
# Example: brain_event TASK_CLAIM "TASK-011 claude-code"
#
# ADR-0004 Phase 0c: Dual-write. Old plain-text format preserved for backward
# compatibility. New JSONL format adds event_id, source, source_host, and
# structured metadata. events.log remains canonical for legacy consumers.

TOOLS="${TOOLS:-${BRAIN_DIR:-$HOME/brain}/scripts}"
. "$TOOLS/lib/brain-paths.sh"

# Cache hostname once per shell session
_BRAIN_EVENT_HOST="${_BRAIN_EVENT_HOST:-$(hostname 2>/dev/null || echo "unknown")}"

brain_event() {
  local event_type="$1"
  shift
  local metadata="$*"
  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  # ── Legacy write (unchanged) ──
  echo "$ts $event_type $metadata" >> "$_EVENTS_LOG"

  # ── JSONL write ──
  # event_id: evt-YYYYMMDD-HHMMSS-6hexchars
  local date_part=${ts:0:4}${ts:5:2}${ts:8:2}
  local time_part=${ts:11:2}${ts:14:2}${ts:17:2}
  local rand_hex
  rand_hex=$(head -c3 /dev/urandom | xxd -p 2>/dev/null || printf '%06x' $RANDOM)
  local event_id="evt-${date_part}-${time_part}-${rand_hex}"

  # Parse entity_id and structured meta from metadata string per event type
  python3 -c "
import json, sys
op = sys.argv[1]
meta_str = sys.argv[2]
event_id = sys.argv[3]
ts = sys.argv[4]
host = sys.argv[5]
jsonl_path = sys.argv[6]

entity_id = None
surface = None
meta = {}
parts = meta_str.split()

if op == 'VERDICT':
    # Format: STATUS Nq/Na/Nc
    meta['status'] = parts[0] if parts else ''
    meta['queue_state'] = parts[1] if len(parts) > 1 else ''
    surface = 'brain/ops/state-verdict.json'
elif op in ('TASK_CLAIM', 'TASK_EXECUTE'):
    # Format: TASK-ID agent
    entity_id = parts[0] if parts else None
    meta['agent'] = parts[1] if len(parts) > 1 else ''
    surface = 'brain/ops/tasks/'
elif op == 'TASK_COMPLETE':
    # Format: TASK-ID agent [impact=...]
    entity_id = parts[0] if parts else None
    meta['agent'] = parts[1] if len(parts) > 1 else ''
    for p in parts[2:]:
        if p.startswith('impact='):
            meta['impact'] = p[7:]
    surface = 'brain/ops/tasks/'
elif op == 'TASK_ESCALATION':
    # Format: TASK-ID escalation_signal
    entity_id = parts[0] if parts else None
    meta['signal'] = parts[1] if len(parts) > 1 else ''
    surface = 'brain/ops/tasks/'
elif op == 'TASK_ARCHIVE':
    # Format: TASK-ID archive/YYYY-MM
    entity_id = parts[0] if parts else None
    meta['destination'] = parts[1] if len(parts) > 1 else ''
    surface = 'brain/ops/tasks/'
elif op == 'TASK_RELEASE':
    # Format: TASK-ID agent reason
    # Used to return a stale/mis-claimed task back to queue without marking it completed.
    entity_id = parts[0] if parts else None
    meta['agent'] = parts[1] if len(parts) > 1 else ''
    meta['reason'] = '_'.join(parts[2:]) if len(parts) > 2 else ''
    surface = 'brain/ops/tasks/'
elif op == 'TASK_CANCEL':
    # Format: TASK-ID agent reason
    # Used to cancel a queued/active task that will not be executed.
    entity_id = parts[0] if parts else None
    meta['agent'] = parts[1] if len(parts) > 1 else ''
    meta['reason'] = '_'.join(parts[2:]) if len(parts) > 2 else ''
    surface = 'brain/ops/tasks/'
else:
    # Unknown event type — preserve raw metadata
    meta['raw'] = meta_str

record = {
    'event_id': event_id,
    'ts': ts,
    'source': 'local',
    'source_host': host,
    'op': op,
    'entity_id': entity_id,
    'surface': surface,
    'meta': meta
}

with open(jsonl_path, 'a') as f:
    f.write(json.dumps(record, separators=(',', ':')) + '\n')
" "$event_type" "$metadata" "$event_id" "$ts" "$_BRAIN_EVENT_HOST" "$_EVENTS_JSONL" 2>/dev/null
  if [[ $? -ne 0 ]]; then
    echo "[brain-event] WARNING: JSONL write failed for $event_type at $ts" >&2
  fi
}
