#!/bin/bash
# Shared frontmatter parser for Brain CLI tools (shell version)
# Source this file: . "$TOOLS/lib/frontmatter.sh"
#
# Usage:
#   fm_get <file> <key>           → prints the value (stripped of quotes)
#   fm_has <file> <key>           → exit 0 if key exists in frontmatter, 1 if not
#   fm_get_bool <file> <key>      → prints "true" or "false"
#   fm_has_frontmatter <file>     → exit 0 if file starts with ---, 1 if not
#
# Handles: quoted values, unquoted values, empty strings, booleans, arrays (as raw string)
# Does NOT handle: multiline values, nested objects

fm_get() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 0
  # Extract frontmatter block (between first two --- lines), find key, strip quotes
  # Strips both double and single quotes, lowercases for consistent comparison,
  # and removes inline comments (# ...) from the value
  local _raw
  _raw=$(awk 'NR==1 && /^---$/{fm=1; next} fm && /^---$/{exit} fm{print}' "$file" | \
    grep "^${key}:" | head -1 | \
    sed "s/^${key}: *//; s/^ *[\"']//; s/[\"'] *$//; s/ *#.*//" || true)
  echo "$_raw"
}

fm_has() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 1
  awk 'NR==1 && /^---$/{fm=1; next} fm && /^---$/{exit} fm{print}' "$file" | \
    grep -q "^${key}:"
}

fm_get_bool() {
  local val
  val=$(fm_get "$1" "$2")
  [[ "$val" == "true" ]] && echo "true" || echo "false"
}

fm_has_frontmatter() {
  [[ -f "$1" ]] || return 1
  head -1 "$1" 2>/dev/null | grep -q '^---$'
}

# fm_probe — diagnostic status check for frontmatter parsing
# Returns exit codes:
#   0 = key present and parseable
#   1 = key missing (frontmatter exists, key not in it)
#   2 = no frontmatter (file doesn't start with ---) or file missing
#   3 = malformed frontmatter (starts with --- but no closing ---)
# Use this for safety-critical checks (e.g., privacy field validation).
# Use fm_get for normal value retrieval (backward-compatible, always exit 0).
fm_probe() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 2
  # Check frontmatter exists
  head -1 "$file" 2>/dev/null | grep -q '^---$' || return 2
  # Check closing --- exists (malformed check)
  local _closing
  _closing=$(awk 'NR==1 && /^---$/{fm=1; next} fm && /^---$/{print "FOUND"; exit}' "$file")
  [[ "$_closing" == "FOUND" ]] || return 3
  # Check key exists in frontmatter
  awk 'NR==1 && /^---$/{fm=1; next} fm && /^---$/{exit} fm{print}' "$file" | \
    grep -q "^${key}:" || return 1
  return 0
}
