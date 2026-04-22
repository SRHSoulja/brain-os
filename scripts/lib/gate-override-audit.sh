#!/bin/bash
# gate-override-audit.sh — Verify all safety gates have documented override paths.
# Usage: bash gate-override-audit.sh [--json]
#
# Scans for gate tools and checks each has an entry in gate-overrides.json.
# Reports ungoverned gates (blocking tools with no escape hatch documentation).
#
# Exit: 0 if all gates covered, 1 if gaps found.

set -euo pipefail

TOOLS="${TOOLS:-${BRAIN_DIR:-$HOME/brain}/scripts}"
REGISTRY="$TOOLS/lib/gate-overrides.json"
JSON_MODE=false
[[ "${1:-}" == "--json" ]] && JSON_MODE=true

if [[ ! -f "$REGISTRY" ]]; then
  echo "ERROR: gate-overrides.json not found at $REGISTRY" >&2
  exit 2
fi

# Collect registered gate names
registered=$(python3 -c "
import json
data = json.load(open('$REGISTRY'))
for name in data.get('gates', {}):
    print(name)
")

# Discover gate tools in the codebase (executable scripts only, not docs/packs)
discovered=()
for f in "$TOOLS/bin/"*gate* "$HOME/bin/"*codex-gate* ; do
  [[ -f "$f" && -x "$f" ]] || continue
  name=$(basename "$f" | sed 's/\.sh$//')
  discovered+=("$name")
done

# Check coverage
missing=()
covered=()
for name in "${discovered[@]}"; do
  if echo "$registered" | grep -qF "$name"; then
    covered+=("$name")
  else
    # Skip non-blocking utilities (detect/clear/enforce are hook helpers, not standalone gates)
    case "$name" in
      discord-reply-gate-clear|discord-reply-gate-detect|discord-reply-gate-enforce)
        # These are hook components, not standalone gates. Parent gate is discord-reply-gate.
        covered+=("$name")
        ;;
      *-regression*|*-check*|*-guard*)
        # Test/guard scripts are not fail-closed gates
        covered+=("$name")
        ;;
      *)
        missing+=("$name")
        ;;
    esac
  fi
done

if $JSON_MODE; then
  python3 -c "
import json
print(json.dumps({
    'covered': $(python3 -c "import json; print(json.dumps([$(printf '"%s",' "${covered[@]}")]))" 2>/dev/null || echo '[]'),
    'missing': $(python3 -c "import json; print(json.dumps([$(printf '"%s",' "${missing[@]}")]))" 2>/dev/null || echo '[]'),
    'registry_count': $(echo "$registered" | wc -l),
    'verdict': 'PASS' if not [$(printf '"%s",' "${missing[@]}")] else 'FAIL'
}, indent=2))
" 2>/dev/null || echo '{"error": "json output failed"}'
else
  echo "Gate Override Audit"
  echo "==================="
  echo "Registry: $REGISTRY ($(echo "$registered" | wc -l) gates)"
  echo "Discovered: ${#discovered[@]} gate tools"
  echo "Covered: ${#covered[@]}"
  echo ""
  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "MISSING OVERRIDE DOCUMENTATION:"
    for name in "${missing[@]}"; do
      echo "  - $name"
    done
    echo ""
    echo "Verdict: FAIL"
    echo "Add entries to $REGISTRY for missing gates."
    exit 1
  else
    echo "All discovered gates have override documentation."
    echo "Verdict: PASS"
    exit 0
  fi
fi
