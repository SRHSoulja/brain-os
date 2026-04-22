#!/usr/bin/env python3
"""plan-order-check.py — Check if a task's execution plan predecessors are complete.

Reads queue-execution-plan.md, finds the task's tier and order number,
checks if all lower-order tasks in the same tier are DONE.

Usage:
    python3 plan-order-check.py <task_id>

Output (JSON):
    {"in_plan": bool, "tier": str, "order": str, "predecessors_done": bool,
     "blockers": ["TASK-ID (title)"]}

Exit: always 0 (caller reads JSON verdict, not exit code).
"""

import json
import os
import re
import sys


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"in_plan": False, "error": "no task_id provided"}))
        return

    task_id = sys.argv[1]
    brain = os.environ.get("BRAIN_DIR", os.environ.get("BRAIN_DIR", os.path.join(os.environ["HOME"], "brain")))
    plan_path = os.path.join(brain, "brain", "ops", "queue-execution-plan.md")
    completed_dir = os.path.join(brain, "brain", "ops", "tasks", "completed")

    if not os.path.isfile(plan_path):
        print(json.dumps({"in_plan": False, "error": "plan file not found"}))
        return

    with open(plan_path) as f:
        content = f.read()

    # Parse tier tables. Format:
    # ## Tier N: Title
    # | Order | Task | Title | ... | Status |
    # | 15 | TASK-004 | ... | ... | queued |
    current_tier = ""
    entries = []  # [{tier, order, task_id, title, status}]

    for line in content.split("\n"):
        # Detect tier headers
        tier_match = re.match(r"^## (Tier \d+.*)", line)
        if tier_match:
            current_tier = tier_match.group(1).split("(")[0].strip()
            continue

        # Detect table rows (skip headers and separators)
        if not current_tier or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 4:
            continue
        order_str = cells[0].strip()
        if not order_str or order_str == "Order" or order_str.startswith("-"):
            continue

        task_col = cells[1].strip()
        title_col = cells[2].strip() if len(cells) > 2 else ""
        status_col = cells[-1].strip()

        entries.append({
            "tier": current_tier,
            "order": order_str,
            "task_id": task_col,
            "title": title_col[:80],
            "status": status_col,
        })

    # Normalize task ID for matching: TASK-2026-04-12-004 -> TASK-004
    def short_id(tid):
        """Extract short form: TASK-2026-04-12-004 -> TASK-004, TASK-004 -> TASK-004"""
        m = re.match(r"TASK-\d{4}-\d{2}-\d{2}-(\d+)", tid)
        if m:
            return f"TASK-{m.group(1)}"
        return tid

    target_short = short_id(task_id)

    # Find target task (match on short ID)
    target = None
    for e in entries:
        if short_id(e["task_id"]) == target_short or e["task_id"] == task_id:
            target = e
            break

    if not target:
        # Task not in plan -- no ordering constraint
        print(json.dumps({"in_plan": False}))
        return

    # Find predecessors: same tier, lower order number
    target_tier = target["tier"]
    try:
        target_order = float(re.sub(r"[a-z]", ".", target["order"]))
    except ValueError:
        target_order = 999

    blockers = []
    for e in entries:
        if e["tier"] != target_tier:
            continue
        if e["task_id"] == task_id:
            continue
        try:
            e_order = float(re.sub(r"[a-z]", ".", e["order"]))
        except ValueError:
            continue
        if e_order >= target_order:
            continue
        # This is a predecessor -- check if it's done
        status_lower = e["status"].lower()
        if "done" in status_lower:
            continue
        # Check completed dir as fallback (try both short and long ID forms)
        comp_found = False
        for fname in os.listdir(completed_dir) if os.path.isdir(completed_dir) else []:
            if fname.endswith(".md") and short_id(fname.replace(".md", "")) == short_id(e["task_id"]):
                comp_found = True
                break
        if comp_found:
            continue
        blockers.append(f"{e['task_id']} ({e['title'][:50]})")

    result = {
        "in_plan": True,
        "tier": target_tier,
        "order": target["order"],
        "predecessors_done": len(blockers) == 0,
        "blockers": blockers,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
