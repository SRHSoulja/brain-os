#!/usr/bin/env bash
# scripts/hooks/adapters/claude-pretooluse.sh
# Adapter: Claude Code PreToolUse → normalized payload (v1) → canonical hook.
#
# Usage: claude-pretooluse.sh <hook-name>
#   hook-name: name of script in scripts/hooks/brain/ (without .sh)
#
# Input: Claude native PreToolUse JSON on stdin:
#   { "tool_name": "Edit", "tool_input": { "file_path": "/abs/path" } }
#
# Output: passes through canonical hook's exit code and stderr unchanged.

set -euo pipefail

HOOK_NAME="${1:?Usage: claude-pretooluse.sh <hook-name>}"
BRAIN="${BRAIN_DIR:-$HOME/brain}"
CANONICAL="$BRAIN/scripts/hooks/brain/${HOOK_NAME}.sh"

if [[ ! -x "$CANONICAL" ]]; then
  echo "adapter error: canonical hook not found or not executable: $CANONICAL" >&2
  exit 1
fi

payload=$(cat)

# Translate Claude native → normalized payload v1
normalized=$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    tn = (d.get("tool_name") or "")
    ti = (d.get("tool_input") or {})
    fp = (ti.get("file_path") or "")
    url = (ti.get("url") or "")

    # Classify tool category
    if tn in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        cat = "file_edit"
    elif tn in ("WebFetch", "WebSearch"):
        cat = "web_fetch"
    elif tn in ("Bash",):
        cat = "exec"
    elif tn in ("Read", "Glob", "Grep"):
        cat = "read"
    else:
        cat = "other"

    out = {
        "payload_version": "1",
        "seat": "claude-code",
        "event": "PreToolUse",
        "tool_category": cat,
        "tool_name": tn,
        "file_path": fp,
        "url": url,
        "raw": d
    }
    print(json.dumps(out))
except Exception as e:
    print(json.dumps({
        "payload_version": "1",
        "seat": "claude-code",
        "event": "PreToolUse",
        "tool_category": "other",
        "tool_name": "",
        "file_path": "",
        "url": "",
        "raw": {}
    }))
' 2>/dev/null) || {
  echo "adapter error: failed to normalize payload" >&2
  exit 1
}

printf '%s' "$normalized" | "$CANONICAL"
