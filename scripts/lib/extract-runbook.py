#!/usr/bin/env python3
"""extract-runbook.py -- Convert a completed task into a reusable runbook.

Reads task .md, .completion.json, and .run.json to produce a structured
markdown document that captures what was built, how, and what to reuse.

Usage:
    python3 extract-runbook.py <TASK-ID> [--output-dir <dir>]
    python3 extract-runbook.py TASK-2026-04-07-002

Output: Markdown runbook written to work/outputs/runbooks/<task-id>.md
Also prints the path to stdout.

No LLM. Deterministic template from task data.
"""

import json
import os
import re
import sys
from datetime import datetime

BRAIN = os.path.os.environ.get("BRAIN_DIR", os.path.expanduser("~/brain"))
COMPLETED = os.path.join(BRAIN, "brain/ops/tasks/completed")
DEFAULT_OUTPUT_DIR = os.path.join(BRAIN, "work/outputs/runbooks")


def load_task_data(task_id):
    """Load all data for a completed task."""
    task_file = os.path.join(COMPLETED, f"{task_id}.md")
    completion_file = os.path.join(COMPLETED, f"{task_id}.completion.json")
    run_file = os.path.join(COMPLETED, f"{task_id}.run.json")

    data = {"task_id": task_id}

    # Task markdown
    if os.path.isfile(task_file):
        with open(task_file) as f:
            content = f.read()
        data["task_content"] = content
        data["title"] = extract_title(content)
        data["frontmatter"] = extract_frontmatter(content)
        data["summary"] = extract_section(content, "Summary")
        data["goal"] = extract_section(content, "Goal")
        data["description"] = extract_section(content, "Description")
        data["steps"] = extract_section(content, "Steps")
        data["constraints"] = extract_section(content, "Constraints")
        data["inputs"] = extract_section(content, "Inputs")
    else:
        data["task_content"] = ""
        data["title"] = task_id
        data["frontmatter"] = {}

    # Completion JSON
    if os.path.isfile(completion_file):
        with open(completion_file) as f:
            data["completion"] = json.load(f)
    else:
        data["completion"] = {}

    # Run record
    if os.path.isfile(run_file):
        with open(run_file) as f:
            run = json.load(f)
        data["run"] = run
        data["execution_pack"] = run.get("execution_pack", {})
    else:
        data["run"] = {}
        data["execution_pack"] = {}

    return data


def extract_frontmatter(content):
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    fm = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r'^(\w+):\s*"?([^"]*)"?\s*$', line)
        if m:
            fm[m.group(1)] = m.group(2)
    return fm


def extract_title(content):
    m = re.search(r"^# (.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def extract_section(content, heading):
    pattern = rf"^## {re.escape(heading)}\s*\n([\s\S]*?)(?=^## |\Z)"
    m = re.search(pattern, content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def classify_task(data):
    """Classify task type for runbook framing."""
    title = data.get("title", "").lower()
    summary = data.get("summary", "").lower()
    desc = data.get("description", "").lower()
    combined = f"{title} {summary} {desc}"

    if any(w in combined for w in ["build", "create", "implement", "add", "define", "enforce"]):
        return "build"
    elif any(w in combined for w in ["deploy", "ship", "publish", "post", "launch"]):
        return "deploy"
    elif any(w in combined for w in ["fix", "repair", "resolve", "patch"]):
        return "fix"
    elif any(w in combined for w in ["review", "audit", "check", "verify", "evaluate"]):
        return "review"
    elif any(w in combined for w in ["document", "write", "update doc"]):
        return "document"
    return "general"


def format_duration(minutes):
    if minutes is None:
        return "unknown"
    if minutes < 1:
        return "<1 min"
    if minutes < 60:
        return f"{minutes} min"
    h = minutes // 60
    m = minutes % 60
    return f"{h}h {m}m" if m else f"{h}h"


def generate_runbook(data):
    """Generate a structured runbook from task data."""
    comp = data.get("completion", {})
    pack = data.get("execution_pack", {})
    fm = data.get("frontmatter", {})
    verify = comp.get("verification_result", {})

    task_type = classify_task(data)
    title = data.get("title", data["task_id"])
    goal = data.get("goal", "") or pack.get("goal", "") or title
    summary_text = comp.get("completion_summary", "")
    notes = comp.get("implementation_notes", "")
    artifacts = comp.get("artifacts_touched", [])
    criteria_met = comp.get("criteria_met", [])
    duration = comp.get("duration_minutes")
    node = comp.get("node", "") or fm.get("node", "")
    completed_on = comp.get("completed_on", "")
    priority = fm.get("priority", "")

    # Verification status
    v_status = verify.get("status", "not verified")
    v_pass = verify.get("pass_count", 0)
    v_fail = verify.get("fail_count", 0)
    v_unverifiable = verify.get("unverifiable_count", 0)

    lines = []

    # Header
    lines.append("---")
    lines.append(f'task_id: "{data["task_id"]}"')
    lines.append(f'type: runbook')
    lines.append(f'source_task_type: {task_type}')
    if node:
        lines.append(f'node: "{node}"')
    lines.append(f'generated: "{datetime.now(tz=None).strftime("%Y-%m-%dT%H:%M:%SZ")}"')
    lines.append(f'completed: "{completed_on}"')
    lines.append(f'verification: "{v_status}"')
    lines.append("---")
    lines.append("")

    # Title
    type_labels = {
        "deploy": "Deploy Runbook",
        "build": "Build Runbook",
        "fix": "Fix Runbook",
        "review": "Review Runbook",
        "document": "Documentation Runbook",
        "general": "Runbook",
    }
    lines.append(f"# {type_labels.get(task_type, 'Runbook')}: {title}")
    lines.append("")

    # Quick reference
    lines.append("## Quick Reference")
    lines.append("")
    lines.append(f"- **Task:** {data['task_id']}")
    if priority:
        lines.append(f"- **Priority:** {priority}")
    if node:
        lines.append(f"- **Node:** {node}")
    lines.append(f"- **Duration:** {format_duration(duration)}")
    lines.append(f"- **Verification:** {v_status} ({v_pass} pass, {v_fail} fail, {v_unverifiable} unverifiable)")
    lines.append("")

    # What was done
    lines.append("## What Was Done")
    lines.append("")
    if goal and goal != title:
        lines.append(f"**Goal:** {goal}")
        lines.append("")
    if summary_text:
        lines.append(summary_text)
    lines.append("")

    # Steps (from task file or execution pack)
    steps_text = data.get("steps", "")
    pack_steps = pack.get("steps", [])
    if steps_text:
        lines.append("## Steps Taken")
        lines.append("")
        lines.append(steps_text)
        lines.append("")
    elif pack_steps:
        lines.append("## Steps Taken")
        lines.append("")
        for i, s in enumerate(pack_steps, 1):
            lines.append(f"{i}. {s}")
        lines.append("")

    # Artifacts
    if artifacts:
        lines.append("## Files Changed")
        lines.append("")
        for a in artifacts:
            lines.append(f"- `{a}`")
        lines.append("")

    # Verification
    if criteria_met:
        lines.append("## Verified Criteria")
        lines.append("")
        for c in criteria_met:
            lines.append(f"- [x] {c}")
        lines.append("")

    # Lessons / Notes
    if notes:
        lines.append("## Lessons Learned")
        lines.append("")
        lines.append(notes)
        lines.append("")

    # Constraints (from task file)
    constraints = data.get("constraints", "")
    if constraints:
        lines.append("## Constraints Applied")
        lines.append("")
        lines.append(constraints)
        lines.append("")

    # Reuse section
    lines.append("## Reuse Instructions")
    lines.append("")
    # Filter artifacts to only meaningful files (not ops noise)
    key_artifacts = [a for a in artifacts
                     if not a.startswith(("brain/ops/", "brain/index/", "work/logs/", ".brain-index"))]

    if task_type == "deploy":
        lines.append("To repeat this deployment:")
        lines.append("")
        if pack_steps or steps_text:
            lines.append("1. Follow the steps above")
        if key_artifacts:
            lines.append(f"2. Key files: {', '.join('`' + a + '`' for a in key_artifacts[:5])}")
        elif summary_text:
            # Extract URLs from summary as deployment targets
            import re as _re
            urls = _re.findall(r'(https?://\S+)', summary_text)
            if urls:
                lines.append(f"2. Target: {urls[0]}")
        if criteria_met:
            lines.append(f"3. Verify: {criteria_met[0]}")
    elif task_type == "build":
        lines.append("This created a new capability. To use or extend it:")
        lines.append("")
        if key_artifacts:
            lines.append(f"- Entry points: {', '.join('`' + a + '`' for a in key_artifacts[:5])}")
        if notes:
            lines.append(f"- Key insight: {notes[:200]}")
        if criteria_met:
            lines.append(f"- Verify it works: {criteria_met[0]}")
    elif task_type == "fix":
        lines.append("If this issue recurs:")
        lines.append("")
        lines.append(f"- Root cause: see lessons above")
        if key_artifacts:
            lines.append(f"- Files involved: {', '.join('`' + a + '`' for a in key_artifacts[:5])}")
        elif artifacts:
            lines.append(f"- Files involved: {', '.join('`' + a + '`' for a in artifacts[:3])}")
    else:
        lines.append("Refer to the steps and artifacts above to replicate this work.")
    lines.append("")

    # Source reference
    lines.append("---")
    lines.append(f"*Generated from {data['task_id']} by extract-runbook.py*")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: extract-runbook.py <TASK-ID> [--output-dir <dir>]",
              file=sys.stderr)
        sys.exit(1)

    task_id = sys.argv[1]
    output_dir = DEFAULT_OUTPUT_DIR

    for i, arg in enumerate(sys.argv):
        if arg == "--output-dir" and i + 1 < len(sys.argv):
            output_dir = sys.argv[i + 1]

    data = load_task_data(task_id)

    if not data.get("task_content") and not data.get("completion"):
        print(f"Error: no data found for {task_id}", file=sys.stderr)
        sys.exit(1)

    runbook = generate_runbook(data)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{task_id}.md")
    with open(out_path, "w") as f:
        f.write(runbook)

    print(out_path)


if __name__ == "__main__":
    main()
