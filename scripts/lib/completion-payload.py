#!/usr/bin/env python3
"""completion-payload.py — Generate a structured Completion Payload for a task.

Creates a JSON payload that mirrors the Execution Pack as the structured
end-of-task object. Can be used as a template (with placeholders) or
filled with actual values.

Usage:
    # Generate template from execution pack
    python3 completion-payload.py <task_file>

    # Generate filled payload
    python3 completion-payload.py <task_file> --summary "..." --notes "..." --artifacts "file1,file2" --impact "metric:before:after"

Output: JSON to stdout.
"""

import json
import os
import re
import sys

TOOLS_LIB = os.path.dirname(os.path.abspath(__file__))


def extract_frontmatter(content):
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    fm_lines = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        fm_lines.append(line)
    else:
        return {}
    fields = {}
    for line in fm_lines:
        m = re.match(r'^(\w+):\s*"?([^"]*)"?\s*$', line)
        if m:
            fields[m.group(1)] = m.group(2)
    return fields


def extract_criteria(content):
    """Extract Success/Completion Criteria bullets."""
    for heading in ["Completion Criteria", "Success Criteria"]:
        pattern = rf"^## {re.escape(heading)}\s*\n([\s\S]*?)(?=^## |\Z)"
        m = re.search(pattern, content, re.MULTILINE)
        if m:
            items = []
            for line in m.group(1).split("\n"):
                bm = re.match(r"^\s*-\s*(?:\[.\]\s*)?(.+)", line)
                if bm:
                    items.append(bm.group(1).strip())
            return items
    return []


def generate_payload(filepath, summary="", notes="", artifacts_str="", impact=""):
    with open(filepath, "r") as f:
        content = f.read()

    fm = extract_frontmatter(content)
    task_id = fm.get("task_id", os.path.basename(filepath).replace(".md", ""))
    criteria = extract_criteria(content)

    # Parse artifacts
    artifacts = [a.strip() for a in artifacts_str.split(",") if a.strip()] if artifacts_str else []

    # Build criteria_met as template or filled
    if summary:
        # Filled mode — mark all criteria as met
        criteria_met = criteria
    else:
        # Template mode — placeholders
        criteria_met = []

    payload = {
        "task_id": task_id,
        "completion_summary": summary or "<completion_summary>",
        "implementation_notes": notes or "<implementation_notes>",
        "artifacts_touched": artifacts if artifacts else ["<artifact_path>"],
        "criteria_met": criteria_met if criteria_met else criteria,
        "impact": impact or "<metric>:<before>:<after>",
    }

    return payload


def main():
    if len(sys.argv) < 2:
        print("Usage: completion-payload.py <task_file> [--summary ...] [--notes ...] [--artifacts ...] [--impact ...]", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.isfile(filepath):
        print(f"Error: {filepath} not found", file=sys.stderr)
        sys.exit(1)

    # Parse optional flags
    summary = notes = artifacts = impact = ""
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--summary" and i + 1 < len(args):
            summary = args[i + 1]; i += 2
        elif args[i] == "--notes" and i + 1 < len(args):
            notes = args[i + 1]; i += 2
        elif args[i] == "--artifacts" and i + 1 < len(args):
            artifacts = args[i + 1]; i += 2
        elif args[i] == "--impact" and i + 1 < len(args):
            impact = args[i + 1]; i += 2
        else:
            i += 1

    payload = generate_payload(filepath, summary, notes, artifacts, impact)
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
