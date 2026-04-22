#!/bin/bash
# task-lock.sh — per-task lifecycle locking via atomic directory rename
# Source this file: . "${BRAIN_DIR:-$HOME/brain}/scripts/lib/task-lock.sh"
#
# Functions:
#   task_lock_acquire <task_id> <operation> <agent>
#   task_lock_release <task_id>
#   task_lock_cleanup (called by trap — releases any held lock)
#
# Lock path: brain/ops/tasks/.locks/TASK-ID.lock/ (directory)
# Metadata:  brain/ops/tasks/.locks/TASK-ID.lock/meta.json
#
# Creation sequence (race-safe):
#   1. mkdir TASK-ID.lock.tmp.<pid>
#   2. Write meta.json inside temp dir
#   3. mv temp dir → TASK-ID.lock (atomic rename — fails if lock exists)
#
# Any visible .lock directory always contains valid metadata.
#
# Stale lock: same hostname + dead pid + age > 10 minutes → auto-cleared

_LOCK_BASE="${BRAIN_DIR:-$HOME/brain}/brain/ops/tasks/.locks"
_HELD_LOCK=""

# Ensure lock base directory exists
mkdir -p "$_LOCK_BASE" 2>/dev/null

# Internal: write metadata and attempt atomic rename
_lock_create_and_rename() {
  local task_id="$1" operation="$2" agent="$3"
  local lock_dir="$_LOCK_BASE/${task_id}.lock"
  local tmp_dir="$_LOCK_BASE/${task_id}.lock.tmp.$$"

  # Step 1: create temp dir (unique per PID, no contention)
  mkdir -p "$tmp_dir" 2>/dev/null || return 1

  # Step 2: write metadata inside temp dir
  python3 - "$tmp_dir/meta.json" "$task_id" "$operation" "$agent" "$$" "$(hostname)" <<'PYEOF'
import json, sys
from datetime import datetime, timezone
path, tid, op, agent, pid, host = sys.argv[1:7]
with open(path, 'w') as f:
    json.dump({"task_id": tid, "operation": op, "agent": agent,
               "pid": int(pid), "hostname": host,
               "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}, f)
PYEOF

  # Step 3: atomic rename — fails if lock_dir already exists
  if mv -T "$tmp_dir" "$lock_dir" 2>/dev/null; then
    _HELD_LOCK="$lock_dir"
    return 0
  else
    # Rename failed — another agent holds the lock. Clean up our temp.
    rm -rf "$tmp_dir" 2>/dev/null
    return 1
  fi
}

task_lock_acquire() {
  local task_id="$1" operation="$2" agent="$3"
  local lock_dir="$_LOCK_BASE/${task_id}.lock"

  # Try atomic create-and-rename
  if _lock_create_and_rename "$task_id" "$operation" "$agent"; then
    return 0
  fi

  # Lock exists — metadata is guaranteed present (atomic rename ensures this)
  local meta_file="$lock_dir/meta.json"
  if [[ ! -f "$meta_file" ]]; then
    # Defensive: shouldn't happen with atomic rename, but handle gracefully
    echo "Lock exists but metadata missing: $lock_dir"
    echo "Remove manually if safe: rm -rf $lock_dir"
    return 1
  fi

  # Read lock holder info (single python3 call)
  local lock_info
  lock_info=$(python3 - "$meta_file" <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(f"{d.get('pid',0)}\t{d.get('hostname','')}\t{d.get('operation','?')}\t{d.get('agent','?')}\t{d.get('started_at','?')}")
except:
    print("0\t\t?\t?\t?")
PYEOF
  ) || lock_info="0		?	?	?"

  local lock_pid lock_host lock_op lock_agent lock_started
  IFS=$'\t' read -r lock_pid lock_host lock_op lock_agent lock_started <<< "$lock_info"

  local my_host
  my_host=$(hostname)

  # Check if lock holder is dead (same host + PID not running + age > 10min)
  if [[ "$lock_host" == "$my_host" ]]; then
    if ! kill -0 "$lock_pid" 2>/dev/null; then
      local lock_mtime
      lock_mtime=$(stat -c %Y "$meta_file" 2>/dev/null || echo 0)
      local age=$(( $(date +%s) - lock_mtime ))
      if [[ $age -gt 600 ]]; then
        echo "Stale lock detected: $task_id (pid=$lock_pid dead, age=${age}s)"
        echo "  Operation: $lock_op by $lock_agent at $lock_started"
        echo "  Clearing stale lock."
        rm -rf "$lock_dir"
        # Retry with atomic create
        if _lock_create_and_rename "$task_id" "$operation" "$agent"; then
          return 0
        fi
      fi
    fi
  fi

  echo "Task $task_id is locked by another operation."
  echo "  Operation: $lock_op by $lock_agent (pid=$lock_pid on $lock_host)"
  echo "  Started: $lock_started"
  return 1
}

task_lock_release() {
  local task_id="$1"
  local lock_dir="$_LOCK_BASE/${task_id}.lock"
  rm -rf "$lock_dir" 2>/dev/null
  _HELD_LOCK=""
}

# Trap-safe cleanup — releases whatever lock is held + removes any temp dir
task_lock_cleanup() {
  if [[ -n "$_HELD_LOCK" ]]; then
    rm -rf "$_HELD_LOCK" 2>/dev/null
    _HELD_LOCK=""
  fi
  # Clean up any orphan temp dir from this PID
  rm -rf "$_LOCK_BASE"/*.lock.tmp.$$ 2>/dev/null
}
