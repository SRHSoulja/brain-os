#!/usr/bin/env bash
# scripts/hooks/brain/agent-agnostic-gate.sh
# Canonical agent-agnostic-first pre-edit gate (normalized payload input).
#
# Receives normalized payload (v1) on stdin. Blocks Edit/Write/MultiEdit on
# seat-local paths unless canonical brain content has been modified in the
# working tree this session.
#
# Exit 0 = allow. Exit 2 = block (stderr message fed to model). Exit 1 = error (allow-through).
#
# See: brain/MANUAL.md §6.0 (agent-agnostic-first rule)

set -euo pipefail

BRAIN="${BRAIN_DIR:-$HOME/brain}"

# Allow explicit operator/automation bypass.
if [[ "${BRAIN_AGNOSTIC_BYPASS:-0}" == "1" ]]; then
  exit 0
fi

payload=$(cat)

# Parse normalized payload
read -r payload_version tool_category tool_name file_path < <(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    pv = d.get("payload_version", "")
    tc = d.get("tool_category", "")
    tn = d.get("tool_name", "")
    fp = d.get("file_path", "")
    print(pv, tc, tn, fp)
except Exception:
    print("", "", "", "")
' 2>/dev/null) || { exit 1; }

# Reject mismatched payload version
if [[ "$payload_version" != "1" ]]; then
  echo "hook error: expected payload_version=1, got '${payload_version}'" >&2
  exit 1
fi

# Only act on file-editing tool category
if [[ "$tool_category" != "file_edit" ]]; then
  exit 0
fi

[[ -z "$file_path" ]] && exit 0

# Normalize: determine if path is inside the brain repo
abs_file_path="$file_path"
[[ "$abs_file_path" != /* ]] && abs_file_path="$(pwd)/$file_path"

case "$abs_file_path" in
  "$BRAIN"/*) rel="${abs_file_path#$BRAIN/}" ;;
  *) exit 0 ;;  # outside the brain repo; not our concern
esac

# Detect seat-local targets
is_seat_local=0
case "$rel" in
  .claude/*|.codex/*|.gemini/*) is_seat_local=1 ;;
  CLAUDE.md|AGENTS.md|GEMINI.md) is_seat_local=1 ;;
esac

[[ "$is_seat_local" -eq 0 ]] && exit 0

# Seat-local edit detected. Require concurrent agnostic change in working tree.
if ! command -v git >/dev/null 2>&1; then
  exit 0  # fail-open if git unavailable
fi

AGN_PATHS=(brain/wiki brain/governance brain/MANUAL.md brain/core-knowledge)
agnostic_changed=$(
  {
    git -C "$BRAIN" diff --name-only HEAD -- "${AGN_PATHS[@]}" 2>/dev/null
    git -C "$BRAIN" diff --name-only --staged -- "${AGN_PATHS[@]}" 2>/dev/null
    git -C "$BRAIN" ls-files --others --exclude-standard -- "${AGN_PATHS[@]}" 2>/dev/null
  } | head -1
) || true

if [[ -n "$agnostic_changed" ]]; then
  exit 0
fi

# Block.
cat >&2 <<EOF
AGENT-AGNOSTIC GATE: blocked ${tool_name} on seat-local path \`${rel}\`.

This brain is an agent-agnostic OS. Before editing any seat-local file
(.claude/, .codex/, .gemini/, CLAUDE.md, AGENTS.md, GEMINI.md), you must
first write or modify the canonical content in an agnostic location:
  - brain/wiki/  (rules, tools, systems pages)
  - brain/governance/
  - brain/MANUAL.md
  - brain/core-knowledge/

Pre-edit protocol:
  1. Does canonical content exist? If NO → write it FIRST.
  2. Update ALL seat surfaces together.
  3. Self-check: "If the other seats run this tomorrow, do they see it?"

Bypass for legitimate seat-only edits (hook wiring, CLI auth, UI-only):
  BRAIN_AGNOSTIC_BYPASS=1  (see brain/MANUAL.md §6.0)
EOF
exit 2
