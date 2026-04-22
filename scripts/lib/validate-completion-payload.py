#!/usr/bin/env python3
"""validate-completion-payload.py — Validate a Completion Payload JSON file.

Checks structure, required fields, types, and impact format.
Exits 0 if valid, 1 if invalid (with error messages to stderr).

Usage:
    python3 validate-completion-payload.py <payload.json>

    # From stdin
    echo '{"task_id":"..."}' | python3 validate-completion-payload.py -
"""

import json
import re
import sys


def validate(payload):
    """Validate a payload dict. Returns list of error strings (empty = valid)."""
    errors = []

    if not isinstance(payload, dict):
        return ["Payload must be a JSON object"]

    # Required string fields
    for field in ("task_id", "completion_summary", "implementation_notes"):
        val = payload.get(field)
        if not val or not isinstance(val, str):
            errors.append(f"Missing or empty required field: {field}")
        elif val.startswith("<") and val.endswith(">"):
            errors.append(f"Field {field} contains unfilled placeholder: {val}")

    # Required array fields
    for field in ("artifacts_touched", "criteria_met"):
        val = payload.get(field)
        if val is not None and not isinstance(val, list):
            errors.append(f"Field {field} must be an array, got {type(val).__name__}")
        elif isinstance(val, list):
            for i, item in enumerate(val):
                if not isinstance(item, str):
                    errors.append(f"{field}[{i}] must be a string")
                elif item.startswith("<") and item.endswith(">"):
                    errors.append(f"{field}[{i}] contains unfilled placeholder: {item}")

    # Impact format (optional but must be valid if present)
    impact = payload.get("impact", "")
    if impact and isinstance(impact, str):
        if impact.startswith("<"):
            pass  # placeholder — acceptable in template mode
        elif ":" not in impact:
            errors.append(f"Impact must follow metric:before:after format, got: {impact}")
        else:
            parts = impact.split(":", 2)
            if len(parts) < 2:
                errors.append(f"Impact must have at least metric:before, got: {impact}")
            elif not parts[0].strip():
                errors.append("Impact metric name is empty")

    # task_id format
    tid = payload.get("task_id", "")
    if tid and not tid.startswith("<"):
        if not re.match(r"^TASK-\d{4}-\d{2}-\d{2}-\d{3}", tid):
            errors.append(f"task_id format invalid: {tid} (expected TASK-YYYY-MM-DD-NNN)")

    return errors


def main():
    if len(sys.argv) < 2:
        print("Usage: validate-completion-payload.py <payload.json | ->", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]

    try:
        if path == "-":
            payload = json.load(sys.stdin)
        else:
            with open(path, "r") as f:
                payload = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"Cannot read file: {e}", file=sys.stderr)
        sys.exit(1)

    errors = validate(payload)

    if errors:
        for err in errors:
            print(f"  Error: {err}", file=sys.stderr)
        sys.exit(1)
    else:
        print("Payload valid")
        sys.exit(0)


if __name__ == "__main__":
    main()
