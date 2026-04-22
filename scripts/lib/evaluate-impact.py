#!/usr/bin/env python3
"""evaluate-impact.py — Analyze an impact artifact and suggest follow-up tasks.

Reads an impact JSON, checks for missing subsystems based on the evidence
and transition, and outputs structured task suggestions.

Usage:
    python3 evaluate-impact.py <impact.json>

Output: JSON array of task suggestions to stdout.
Each suggestion has: title, priority, node, rationale
"""

import json
import os
import sys

# Subsystem coverage rules: if the impact evidence mentions certain
# capabilities, check whether corresponding follow-up areas are covered.
COVERAGE_RULES = [
    {
        "trigger_keywords": ["execute", "launch", "run record", "task"],
        "check": "monitoring",
        "title": "Add monitoring for {system}",
        "rationale": "New execution capability needs health monitoring to detect failures.",
        "priority": "P2",
    },
    {
        "trigger_keywords": ["execute", "launch", "run record"],
        "check": "run_history",
        "title": "Build run history explorer for {system}",
        "rationale": "Execution records exist but no way to browse or query historical runs.",
        "priority": "P3",
    },
    {
        "trigger_keywords": ["dashboard", "panel", "control"],
        "check": "dashboard_metrics",
        "title": "Add metrics visualization to dashboard for {system}",
        "rationale": "Dashboard shows state but not trends or aggregate metrics.",
        "priority": "P3",
    },
    {
        "trigger_keywords": ["impact", "milestone", "transition"],
        "check": "impact_timeline",
        "title": "Build impact timeline view",
        "rationale": "Impact artifacts exist but no chronological view of system evolution.",
        "priority": "P3",
    },
    {
        "trigger_keywords": ["verify", "codex", "verification", "audit"],
        "check": "automated_verification",
        "title": "Automate verification triggers for {system}",
        "rationale": "Verification is manual — could be triggered after major completions.",
        "priority": "P3",
    },
    {
        "trigger_keywords": ["stale", "orphan", "drift", "state-check"],
        "check": "alerting",
        "title": "Add alerting thresholds for {system} drift",
        "rationale": "Drift detection exists but no alerting when thresholds are breached.",
        "priority": "P2",
    },
    {
        "trigger_keywords": ["payload", "completion", "structured"],
        "check": "analytics",
        "title": "Build completion analytics for {system}",
        "rationale": "Structured completion data is captured but not analyzed for patterns.",
        "priority": "P3",
    },
    {
        "trigger_keywords": ["pack", "execution", "compile"],
        "check": "documentation",
        "title": "Document {system} for external consumers",
        "rationale": "New capability should be documented for future agents and operators.",
        "priority": "P3",
    },
]


def evaluate(impact_path):
    with open(impact_path) as f:
        impact = json.load(f)

    system = impact.get("system", "unknown")
    evidence_text = " ".join(impact.get("evidence", [])).lower()
    transition = impact.get("transition", "").lower()
    description = impact.get("description", "").lower()
    full_text = f"{evidence_text} {transition} {description}"

    suggestions = []
    seen_checks = set()

    for rule in COVERAGE_RULES:
        if rule["check"] in seen_checks:
            continue
        hits = sum(1 for kw in rule["trigger_keywords"] if kw in full_text)
        if hits >= 2:  # Require at least 2 keyword matches
            suggestions.append({
                "title": rule["title"].format(system=system),
                "priority": rule["priority"],
                "node": "devops-tools",
                "rationale": rule["rationale"],
                "source_impact": impact.get("impact_id", ""),
            })
            seen_checks.add(rule["check"])

    return suggestions


def seed_tasks(suggestions_file, queue_dir, today, start_num, impact_id):
    """Create task files from suggestions JSON with provenance and duplicate guard."""
    from datetime import datetime, timezone

    with open(suggestions_file) as f:
        tasks = json.load(f)

    # Duplicate guard: scan existing queue for tasks already seeded from this impact
    existing_titles = set()
    for fname in os.listdir(queue_dir):
        if not fname.startswith("TASK-") or not fname.endswith(".md"):
            continue
        fpath = os.path.join(queue_dir, fname)
        try:
            with open(fpath) as f:
                content = f.read()
            if f"source_impact: \"{impact_id}\"" in content:
                # Extract title
                for line in content.split("\n"):
                    if line.startswith("# "):
                        existing_titles.add(line[2:].strip())
                        break
        except OSError:
            continue

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    start_num = int(start_num)
    created = 0
    skipped = 0

    for i, t in enumerate(tasks):
        title = t["title"]

        # Skip if already seeded from this impact
        if title in existing_titles:
            print(f"  Skipped (duplicate): {title}")
            skipped += 1
            continue

        num = start_num + created
        task_id = f"TASK-{today}-{num:03d}"
        filepath = os.path.join(queue_dir, f"{task_id}.md")

        content = f"""---
task_id: "{task_id}"
type: "build"
priority: "{t['priority']}"
owner: "unassigned"
status: "queued"
created: "{today}"
parent_task: ""
node: "{t.get('node', 'devops-tools')}"
source_impact: "{impact_id}"
generated_by: "brain-impact-evaluate"
generated_at: "{generated_at}"
created_by: "brain-impact-evaluate"
creation_mode: "impact-seeded"
authority_basis: "impact {impact_id}"
why_now: "Auto-generated from impact evaluation of {impact_id}"
---

# {title}

## Description

{t['rationale']}

## Completion Criteria

- [ ] Implementation complete
- [ ] Verified working

## Context

- Source impact: `brain/ops/impacts/{impact_id}.json`
- Generated by: `brain-impact-evaluate --seed`
- Generated at: {generated_at}
"""
        # Write to temp file, then admit through canonical gate
        import subprocess
        import tempfile
        tmp_dir = tempfile.gettempdir()
        tmp_path = os.path.join(tmp_dir, f"{task_id}.md")
        with open(tmp_path, "w") as f:
            f.write(content)

        admit_bin = os.path.expanduser("~/bin/brain-task-admit")
        result = subprocess.run(
            [admit_bin, tmp_path],
            capture_output=True, text=True
        )
        os.unlink(tmp_path)

        if result.returncode != 0:
            print(f"  REJECTED: {task_id} — {title}")
            if result.stdout.strip():
                for line in result.stdout.strip().split("\n"):
                    print(f"    {line}")
            skipped += 1
            continue

        print(f"  Admitted: {task_id} — {title}")
        created += 1

    print(f"\n  Created: {created} | Skipped (duplicates): {skipped}")


def main():
    # Seed mode: evaluate-impact.py --seed <suggestions.json> <queue_dir> <today> <start_num> <impact_id>
    if len(sys.argv) >= 2 and sys.argv[1] == "--seed":
        if len(sys.argv) < 7:
            print("Seed usage: evaluate-impact.py --seed <suggestions.json> <queue_dir> <today> <start_num> <impact_id>", file=sys.stderr)
            sys.exit(1)
        seed_tasks(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])
        sys.exit(0)

    if len(sys.argv) < 2:
        print("Usage: evaluate-impact.py <impact.json>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)

    suggestions = evaluate(path)
    json.dump(suggestions, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
