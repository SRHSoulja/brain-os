#!/bin/bash
# sync-task-counts.sh — Refresh system-state.md task counts from filesystem
# Source this file, then call sync_task_counts
#
# Usage:
#   . "$TOOLS/lib/sync-task-counts.sh"
#   sync_task_counts   # updates system-state.md in place

sync_task_counts() {
  local _tools="${TOOLS:-${BRAIN_DIR:-$HOME/brain}/scripts}"
  . "$_tools/lib/brain-paths.sh"
  local _brain="$_BRAIN"
  local _ops_dir="$_OPS_TASKS_DIR"
  local _sstate="$_SYSTEM_STATE_MD"

  [[ -f "$_sstate" ]] || return 0
  grep -q 'brain/ops/tasks/queue/' "$_sstate" 2>/dev/null || return 0

  # Count from filesystem
  local _q=0 _a=0 _c=0
  for f in "$_ops_dir"/queue/TASK-*.md; do [[ -f "$f" ]] && _q=$((_q+1)); done
  for f in "$_ops_dir"/active/TASK-*.md; do [[ -f "$f" ]] && _a=$((_a+1)); done
  for f in "$_ops_dir"/completed/TASK-*.md; do [[ -f "$f" ]] && _c=$((_c+1)); done

  # Atomic update
  local _tmp
  _tmp=$(mktemp "$_brain/brain/ops/.system-state.md.XXXXXX")
  python3 - "$_sstate" "$_tmp" "$_q" "$_a" "$_c" "$(date +%Y-%m-%d)" <<'PYEOF'
import re, sys
sstate, out, q, a, c, today = sys.argv[1:7]
with open(sstate, 'r') as f:
    content = f.read()
counts = {'queue': int(q), 'active': int(a), 'completed': int(c)}
labels = {'queue': 'queued', 'active': 'in progress', 'completed': 'completed'}
for key, count in counts.items():
    pattern = r'(\| `brain/ops/tasks/' + key + r'/`\s*\|)\s*\d+\s*(\|)[^\n]*'
    note = f'{count} {labels[key]}' if count > 0 else f'No tasks {labels[key]}'
    replacement = r'\1 ' + str(count) + r' \2 ' + note + ' |'
    content = re.sub(pattern, replacement, content)
content = re.sub(r'^last_updated:.*$', 'last_updated: "' + today + '"', content, flags=re.MULTILINE)
with open(out, 'w') as f:
    f.write(content)
PYEOF

  if [[ -s "$_tmp" ]]; then
    mv "$_tmp" "$_sstate"
  else
    rm -f "$_tmp"
  fi
}
