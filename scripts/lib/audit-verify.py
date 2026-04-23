#!/usr/bin/env python3
"""audit-verify.py — Deterministic verification of post-task audit items.

Checks that the completed task has proper documentation coverage.
Called by brain-task-execute --audit-done before clearing the marker.

Usage:
    python3 audit-verify.py <task_id> [--completion-json <path>]

Output (JSON):
    {"pass": bool, "checks": [...], "hard_fails": [...], "warnings": [...]}

Checks:
    1. Task has a wiki page (hard)
    2. Modified tools have wiki tool pages (hard)
    3. Modified tools are in MAP.md (hard)
    4. Execution plan references the task (warn)
    5. Today's devlog mentions the task (warn)
    6. Verification evidence exists for P1/P2 or governance-touching tasks (hard by default)
"""

import json
import os
import re
import sys
from datetime import datetime


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"pass": False, "error": "no task_id"}))
        return

    task_id = sys.argv[1]
    brain = os.environ.get("BRAIN_DIR", os.environ.get("BRAIN_DIR", os.path.join(os.environ["HOME"], "brain")))
    tools_dir = os.path.join(os.environ.get("BRAIN_DIR", os.path.join(os.environ["HOME"], "brain")), "scripts")
    wiki_dir = os.path.join(brain, "brain", "wiki")
    today = datetime.now().strftime("%Y-%m-%d")

    checks = []
    hard_fails = []
    warnings = []
    allow_unverified = os.environ.get("AUDIT_VERIFY_ALLOW_UNVERIFIED", "").lower() in (
        "1",
        "true",
        "yes",
    )

    # Normalize task ID for wiki slug matching: TASK-2026-04-12-032 -> task_2026_04_12_032
    slug = task_id.lower().replace("-", "_")

    # 1. Task has a wiki page (hard)
    wiki_found = False
    for subdir in ["systems", "pages", "tools", "decisions"]:
        dirpath = os.path.join(wiki_dir, subdir)
        if not os.path.isdir(dirpath):
            continue
        for fname in os.listdir(dirpath):
            if slug in fname.lower():
                wiki_found = True
                break
        if wiki_found:
            break
    # Also check if any wiki page mentions the task ID
    if not wiki_found:
        for root, dirs, files in os.walk(wiki_dir):
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath) as f:
                        if task_id in f.read():
                            wiki_found = True
                            break
                except:
                    pass
            if wiki_found:
                break

    if wiki_found:
        checks.append("PASS: task wiki page exists")
    else:
        hard_fails.append(f"FAIL: no wiki page found for {task_id}")

    # 2+3. Modified tools have wiki pages + MAP entries (hard)
    # Read completion json if available to find artifacts
    completion_path = os.path.join(
        brain, "brain", "ops", "tasks", "completed", f"{task_id}.completion.json"
    )
    baseline_path = os.path.join(
        brain, "brain", "ops", "tasks", "completed", f".baseline-{task_id}.json"
    )

    modified_tools = []
    if os.path.isfile(baseline_path):
        try:
            with open(baseline_path) as f:
                baseline = json.load(f)
            for fpath in baseline.get("changed_files", []):
                if "/tools/bin/brain-" in fpath or "/tools/lib/" in fpath:
                    modified_tools.append(os.path.basename(fpath))
        except:
            pass

    # Also check tools repo git status
    try:
        import subprocess
        result = subprocess.run(
            ["git", "-C", tools_dir, "diff", "--name-only", "HEAD~1"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split("\n"):
            if line.endswith(".pyc"):
                continue
            if line.startswith("bin/brain-") or line.startswith("lib/"):
                basename = os.path.basename(line)
                if basename not in modified_tools:
                    modified_tools.append(basename)
    except:
        pass

    map_path = os.path.join(wiki_dir, "tools", "MAP.md")
    map_content = ""
    if os.path.isfile(map_path):
        with open(map_path) as f:
            map_content = f.read()

    for tool in modified_tools:
        tool_name = tool.replace(".py", "").replace(".sh", "")
        # Check wiki tool page
        tool_wiki = os.path.join(wiki_dir, "tools", f"{tool_name}.md")
        if os.path.isfile(tool_wiki):
            checks.append(f"PASS: {tool_name} has wiki tool page")
        else:
            hard_fails.append(f"FAIL: {tool_name} modified but no wiki tool page")

        # Check MAP entry
        if f"`{tool_name}`" in map_content or tool_name in map_content:
            checks.append(f"PASS: {tool_name} in MAP.md")
        else:
            hard_fails.append(f"FAIL: {tool_name} modified but not in MAP.md")

    # 4. Execution plan references the task.
    # Hard fail if task is in the plan but status column still shows "queued" —
    # that means the plan was not updated after completion (the Gap 5 failure mode).
    # Warn-only if task is absent from the plan entirely (may be legitimately off-plan).
    plan_path = os.path.join(brain, "brain", "ops", "queue-execution-plan.md")
    if os.path.isfile(plan_path):
        with open(plan_path) as f:
            plan_content = f.read()
        # Extract short ID: TASK-2026-04-12-032 -> TASK-032
        short_match = re.match(r"TASK-\d{4}-\d{2}-\d{2}-(\d+)", task_id)
        short_id = f"TASK-{short_match.group(1)}" if short_match else task_id

        # Find the plan table line that contains this task
        plan_line = None
        for line in plan_content.split("\n"):
            if task_id in line or (short_id and short_id in line):
                plan_line = line
                break

        if plan_line is not None:
            # Parse status from last non-empty pipe-delimited cell
            cells = [c.strip() for c in plan_line.split("|") if c.strip()]
            last_cell = cells[-1] if cells else ""
            if last_cell.lower() == "queued":
                hard_fails.append(
                    f"FAIL: {task_id} is in execution plan but status still shows 'queued' — "
                    "update queue-execution-plan.md to mark it DONE"
                )
            else:
                checks.append("PASS: task in execution plan")
        else:
            warnings.append(f"WARN: {task_id} not found in execution plan")

    # 5. Today's devlog mentions the task (warn)
    devlog_dir = os.path.join(brain, "work", "logs", "devlog")
    devlog_found = False
    if os.path.isdir(devlog_dir):
        for fname in os.listdir(devlog_dir):
            if fname.startswith(today) and fname.endswith(".md"):
                fpath = os.path.join(devlog_dir, fname)
                try:
                    with open(fpath) as f:
                        if task_id in f.read():
                            devlog_found = True
                            break
                except:
                    pass
    if devlog_found:
        checks.append("PASS: task in today's devlog")
    else:
        warnings.append(f"WARN: {task_id} not in today's devlog")

    # 6. Verification evidence for higher-risk tasks (hard unless explicit override)
    completed_md = os.path.join(brain, "brain", "ops", "tasks", "completed", f"{task_id}.md")
    run_json = os.path.join(brain, "brain", "ops", "tasks", "completed", f"{task_id}.run.json")
    priority = ""
    needs_verification = False
    gov_touch = False
    gov_patterns = [
        "brain/governance/",
        "brain/MANUAL.md",
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        "state-verdict",
        "safety",
    ]

    if os.path.isfile(completed_md):
        try:
            with open(completed_md) as f:
                text = f.read()
            m = re.search(r"^priority:\s*\"?([A-Za-z0-9_-]+)\"?", text, re.MULTILINE)
            priority = (m.group(1) if m else "").upper()
        except Exception:
            priority = ""

    if priority in {"P1", "P2"}:
        needs_verification = True

    if os.path.isfile(run_json):
        try:
            with open(run_json) as f:
                r = json.load(f)
            surfaces = (
                r.get("execution_pack", {})
                .get("execution_contract", {})
                .get("allowed_write_surfaces", [])
            )
            if isinstance(surfaces, list):
                flat = [str(s) for s in surfaces]
            else:
                flat = [str(surfaces)]
            gov_touch = any(any(p in s for p in gov_patterns) for s in flat)
            if gov_touch:
                needs_verification = True
        except Exception:
            pass

    if needs_verification:
        codex_lab = os.environ.get("CODEX_LAB_PATH") or os.path.join(os.environ.get("HOME", ""), "codex-lab")
        audits_dir = os.path.join(codex_lab, "audits")
        dispatch_reviews_dir = os.path.join(brain, "work", "outputs", "reviews")
        verification_found = False
        verification_sources = []

        # Legacy sidecar evidence (codex-lab/audits/*verification*.md)
        if os.path.isdir(audits_dir):
            for fname in os.listdir(audits_dir):
                if "verification" not in fname or not fname.endswith(".md"):
                    continue
                fpath = os.path.join(audits_dir, fname)
                try:
                    with open(fpath) as f:
                        if task_id in f.read():
                            verification_found = True
                            verification_sources.append(fpath)
                            break
                except Exception:
                    pass

        # Dispatch-native evidence (work/outputs/reviews/<TASK-ID>-verification.md)
        if not verification_found and os.path.isdir(dispatch_reviews_dir):
            for fname in os.listdir(dispatch_reviews_dir):
                if not fname.endswith(".md") or "verification" not in fname:
                    continue
                fpath = os.path.join(dispatch_reviews_dir, fname)
                try:
                    with open(fpath) as f:
                        body = f.read()
                    if task_id in body and "(dispatch returned no output)" not in body:
                        verification_found = True
                        verification_sources.append(fpath)
                        break
                except Exception:
                    pass

        if verification_found:
            if verification_sources:
                checks.append(
                    f"PASS: verification evidence exists for required task ({verification_sources[0]})"
                )
            else:
                checks.append("PASS: verification evidence exists for required task")
        else:
            msg = (
                f"FAIL: verification evidence missing for {task_id} "
                f"(priority={priority or 'unknown'}, governance_touch={str(gov_touch).lower()}). "
                f"Run: brain-review-dispatch {task_id} --type verification "
                f"(or compatibility wrapper: brain-task-handoff {task_id} --type verification)"
            )
            if allow_unverified:
                warnings.append(
                    "WARN: verification evidence requirement bypassed by explicit override "
                    "(AUDIT_VERIFY_ALLOW_UNVERIFIED=1)"
                )
            else:
                hard_fails.append(msg)

    result = {
        "pass": len(hard_fails) == 0,
        "checks": checks,
        "hard_fails": hard_fails,
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
