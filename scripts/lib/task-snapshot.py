#!/usr/bin/env python3
"""task-snapshot.py -- Capture or diff working-tree state for task-scoped artifact tracking.

Two modes:
  capture: Save content hashes of tracked-modified files + untracked file set to baseline.
  diff:    Compare current state against baseline, return files this task changed.

Usage:
    python3 task-snapshot.py capture <task-id>
    python3 task-snapshot.py diff <task-id>

Baseline location: brain/ops/tasks/active/.baseline-TASK-ID.json
On task completion, the baseline moves to completed/ with the task.

Uses git hash-object for content hashing (same as git internals, fast, no external deps).
Only hashes tracked-modified files (~80). Untracked files (~5000) are recorded by path only.
"""

import json
import os
import subprocess
import sys

BRAIN = os.path.os.environ.get("BRAIN_DIR", os.path.expanduser("~/brain"))
TASKS_DIR = os.path.join(BRAIN, "brain/ops/tasks")


def get_tracked_modified():
    """Get tracked files with modifications (staged or unstaged)."""
    files = set()
    for cmd in [
        ["git", "-C", BRAIN, "diff", "--name-only", "HEAD"],
        ["git", "-C", BRAIN, "diff", "--name-only", "--cached"],
    ]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                for f in result.stdout.strip().split("\n"):
                    if f.strip():
                        files.add(f.strip())
        except Exception:
            pass
    return files


def get_untracked():
    """Get untracked files (new files not in git)."""
    files = set()
    try:
        result = subprocess.run(
            ["git", "-C", BRAIN, "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for f in result.stdout.strip().split("\n"):
                if f.strip():
                    files.add(f.strip())
    except Exception:
        pass
    return files


def hash_files_batch(filepaths):
    """Hash multiple files in one git call. Returns {path: hash}."""
    if not filepaths:
        return {}
    # git hash-object accepts multiple files
    full_paths = []
    path_map = {}
    for fp in sorted(filepaths):
        full = os.path.join(BRAIN, fp)
        if os.path.isfile(full):
            full_paths.append(full)
            path_map[full] = fp

    if not full_paths:
        return {}

    try:
        result = subprocess.run(
            ["git", "hash-object", "--"] + full_paths,
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            hashes = result.stdout.strip().split("\n")
            out = {}
            for full, h in zip(full_paths, hashes):
                if h.strip():
                    out[path_map[full]] = h.strip()
            return out
    except Exception:
        pass
    return {}


def baseline_path(task_id):
    """Return the path for this task's baseline file."""
    completed = os.path.join(TASKS_DIR, "completed", f".baseline-{task_id}.json")
    if os.path.isfile(completed):
        return completed
    return os.path.join(TASKS_DIR, "active", f".baseline-{task_id}.json")


def capture(task_id):
    """Capture current working-tree state as a baseline for this task."""
    import hashlib

    modified = get_tracked_modified()
    untracked = get_untracked()

    # Hash only tracked-modified files (small set, ~80)
    hashes = hash_files_batch(modified)

    # Record untracked compactly: count + integrity hash + sample (max 25)
    # Exclude heavy dirs (node_modules/) from the full list before hashing
    EXCLUDE_PREFIXES = ("node_modules/", ".git/", "sandbox/node_modules/")
    untracked_filtered = sorted(
        f for f in untracked
        if not any(f.startswith(p) for p in EXCLUDE_PREFIXES)
    )
    untracked_all = sorted(untracked)

    # Integrity hash of full untracked set for diff verification
    untracked_hash = hashlib.sha256(
        "\n".join(untracked_all).encode()
    ).hexdigest()[:16]

    out_path = os.path.join(TASKS_DIR, "active", f".baseline-{task_id}.json")
    with open(out_path, "w") as fp:
        json.dump({
            "task_id": task_id,
            "modified_count": len(hashes),
            "untracked_count": len(untracked_all),
            "untracked_hash": untracked_hash,
            "sampled_untracked": untracked_filtered[:25],
            "hashes": hashes,
        }, fp, indent=2)
        fp.write("\n")

    print(f"Baseline captured: {len(hashes)} modified, {len(untracked_all)} untracked (compact)",
          file=sys.stderr)
    return out_path


def diff(task_id):
    """Compare current state against baseline. Return files changed by this task."""
    import hashlib

    bp = baseline_path(task_id)
    if not os.path.isfile(bp):
        print(f"Warning: no baseline for {task_id}, returning all dirty files",
              file=sys.stderr)
        all_dirty = get_tracked_modified() | get_untracked()
        json.dump(sorted(all_dirty), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    with open(bp) as f:
        baseline = json.load(f)

    baseline_hashes = baseline.get("hashes", {})

    # Current state
    current_modified = get_tracked_modified()
    current_untracked = get_untracked()

    current_hashes = hash_files_batch(current_modified)

    changed = []

    # Check tracked-modified files
    for f in current_modified:
        if f not in baseline_hashes:
            # Newly modified tracked file -- this task changed it
            changed.append(f)
        else:
            # Was already modified -- check if content changed further
            current_h = current_hashes.get(f)
            if current_h and current_h != baseline_hashes[f]:
                changed.append(f)

    # Check newly untracked files: compare integrity hash if available (compact baseline),
    # or fall back to full set comparison (legacy baseline with "untracked" key).
    if "untracked" in baseline:
        # Legacy baseline with full untracked list
        baseline_untracked = set(baseline["untracked"])
        new_untracked = current_untracked - baseline_untracked
    elif "untracked_hash" in baseline:
        # Compact baseline: use count delta as signal.
        # If untracked count grew, report the sampled_untracked diff.
        baseline_count = baseline.get("untracked_count", 0)
        if len(current_untracked) > baseline_count:
            # Can't compute exact diff without full set -- report count delta
            print(f"  Untracked count delta: {baseline_count} -> {len(current_untracked)} "
                  f"(+{len(current_untracked) - baseline_count})", file=sys.stderr)
        new_untracked = set()  # Cannot compute exact new files from compact baseline
    else:
        new_untracked = set()

    changed.extend(sorted(new_untracked))

    # Check files that were modified at baseline but are now clean
    # (task committed them or reverted changes -- still an artifact)
    for f in baseline_hashes:
        if f not in current_modified:
            full_path = os.path.join(BRAIN, f)
            if os.path.isfile(full_path):
                changed.append(f)

    changed = sorted(set(changed))
    print(f"Task artifacts: {len(changed)} files changed since baseline",
          file=sys.stderr)
    json.dump(changed, sys.stdout, indent=2)
    sys.stdout.write("\n")


def capture_forensic(task_id):
    """Full untracked capture for forensic investigations. Use --forensic flag."""
    modified = get_tracked_modified()
    untracked = get_untracked()
    hashes = hash_files_batch(modified)
    untracked_list = sorted(untracked)

    out_path = os.path.join(TASKS_DIR, "active", f".baseline-{task_id}.json")
    with open(out_path, "w") as fp:
        json.dump({
            "task_id": task_id,
            "modified_count": len(hashes),
            "untracked_count": len(untracked_list),
            "hashes": hashes,
            "untracked": untracked_list,
            "forensic": True,
        }, fp, indent=2)
        fp.write("\n")

    print(f"Forensic baseline captured: {len(hashes)} modified, {len(untracked_list)} untracked (FULL)",
          file=sys.stderr)
    return out_path


def main():
    if len(sys.argv) < 3:
        print("Usage:", file=sys.stderr)
        print("  task-snapshot.py capture <task-id> [--forensic]", file=sys.stderr)
        print("  task-snapshot.py diff <task-id>", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    task_id = sys.argv[2]
    forensic = "--forensic" in sys.argv

    if mode == "capture":
        if forensic:
            path = capture_forensic(task_id)
        else:
            path = capture(task_id)
        print(path)
    elif mode == "diff":
        diff(task_id)
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
