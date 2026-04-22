#!/usr/bin/env python3
"""enrich-completion.py -- Auto-populate artifacts_touched and criteria_met in completion JSON.

Fills hollow completion payloads with real data:
- artifacts_touched: from git diff between claimed_at and now
- criteria_met: by matching completion_summary against completion_criteria from run record

Usage:
    python3 enrich-completion.py <completion.json> [--run-record <run.json>]

Mutates the completion JSON in place. Idempotent -- won't overwrite non-empty fields.
"""

import json
import os
import re
import subprocess
import sys

BRAIN = os.path.os.environ.get("BRAIN_DIR", os.path.expanduser("~/brain"))


def get_git_diff_files(claimed_at):
    """Get files changed since claimed_at timestamp."""
    if not claimed_at:
        return []
    try:
        result = subprocess.run(
            ["git", "-C", BRAIN, "diff", "--name-only", f"--since={claimed_at}", "HEAD"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    except Exception:
        pass

    # Fallback: diff against staged + unstaged
    try:
        result = subprocess.run(
            ["git", "-C", BRAIN, "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=10
        )
        files = []
        if result.stdout.strip():
            files.extend(result.stdout.strip().split("\n"))

        result2 = subprocess.run(
            ["git", "-C", BRAIN, "diff", "--name-only", "--cached"],
            capture_output=True, text=True, timeout=10
        )
        if result2.stdout.strip():
            files.extend(result2.stdout.strip().split("\n"))

        return list(set(f.strip() for f in files if f.strip()))
    except Exception:
        return []


def get_committed_files_since(claimed_at, completed_at=None):
    """Get files from commits made between claimed_at and completed_at."""
    if not claimed_at:
        return []
    try:
        cmd = ["git", "-C", BRAIN, "log", f"--since={claimed_at}", "--name-only", "--pretty=format:"]
        if completed_at:
            cmd.insert(4, f"--until={completed_at}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return list(set(f.strip() for f in result.stdout.strip().split("\n") if f.strip()))
    except Exception:
        pass
    return []


def match_criteria(summary, notes, criteria):
    """Match completion summary/notes against completion criteria.

    Returns list of criteria that appear satisfied based on keyword overlap.
    Conservative: only marks as met if 2+ significant words from the criterion
    appear in the summary or notes.
    """
    if not criteria:
        return []

    met = []
    text = f"{summary} {notes}".lower()
    # Remove common stop words
    stop = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "and",
            "or", "to", "in", "of", "for", "on", "at", "by", "with", "from",
            "that", "this", "it", "its"}

    for criterion in criteria:
        words = set(re.findall(r'[a-z]{3,}', criterion.lower())) - stop
        if not words:
            continue
        matches = sum(1 for w in words if w in text)
        # Need at least 2 word matches or >50% of significant words
        if matches >= 2 or (len(words) <= 2 and matches >= 1):
            met.append(criterion)

    return met


def load_criteria_from_run_record(run_path):
    """Load completion_criteria from the run record's execution pack."""
    if not run_path or not os.path.isfile(run_path):
        return []
    try:
        with open(run_path) as f:
            data = json.load(f)
        return data.get("execution_pack", {}).get("completion_criteria", [])
    except Exception:
        return []


def enrich(completion_path, run_record_path=None):
    """Enrich a completion JSON with artifacts and criteria."""
    with open(completion_path) as f:
        data = json.load(f)

    modified = False

    # --- artifacts_touched ---
    if not data.get("artifacts_touched"):
        claimed_at = data.get("claimed_at", "")
        completed_at = data.get("completed_at", "")
        # Primary: working tree changes (captures uncommitted work at completion time)
        files = get_git_diff_files(claimed_at)
        # Secondary: committed changes in task window (for post-commit enrichment)
        files.extend(get_committed_files_since(claimed_at, completed_at))
        files = list(set(files))

        # Filter to meaningful files (skip ops/derived, lock files, etc.)
        skip_patterns = [
            r"\.lock$", r"\.chain-depth$", r"state-verdict",
            r"brain/ops/derived/", r"\.run\.json$", r"\.completion\.json$",
        ]
        filtered = []
        for f in files:
            if any(re.search(p, f) for p in skip_patterns):
                continue
            filtered.append(f)

        if filtered:
            data["artifacts_touched"] = sorted(filtered)[:20]
            modified = True

    # --- criteria_met ---
    if not data.get("criteria_met"):
        # Try to find run record if not provided
        if not run_record_path:
            task_id = data.get("task_id", "")
            candidate = os.path.join(
                BRAIN, "brain/ops/tasks/completed", f"{task_id}.run.json"
            )
            if os.path.isfile(candidate):
                run_record_path = candidate

        criteria = load_criteria_from_run_record(run_record_path)
        if criteria:
            summary = data.get("completion_summary", "")
            notes = data.get("implementation_notes", "")
            met = match_criteria(summary, notes, criteria)
            if met:
                data["criteria_met"] = met
                modified = True

    if modified:
        with open(completion_path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        print(f"Enriched: {len(data.get('artifacts_touched', []))} artifacts, "
              f"{len(data.get('criteria_met', []))} criteria met")
    else:
        print("No enrichment needed (fields already populated or no data)")

    return data


def main():
    if len(sys.argv) < 2:
        print("Usage: enrich-completion.py <completion.json> [--run-record <run.json>]",
              file=sys.stderr)
        sys.exit(1)

    completion_path = sys.argv[1]
    run_record = None

    for i, arg in enumerate(sys.argv):
        if arg == "--run-record" and i + 1 < len(sys.argv):
            run_record = sys.argv[i + 1]

    if not os.path.isfile(completion_path):
        print(f"Error: {completion_path} not found", file=sys.stderr)
        sys.exit(1)

    enrich(completion_path, run_record)


if __name__ == "__main__":
    main()
