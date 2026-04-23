#!/usr/bin/env python3
"""verify-outcome.py -- Verify task outcomes against completion criteria.

Extracts deterministic probes from criteria text and runs them.
Produces a structured verification result with pass/fail per criterion.

Probe types:
  file_exists   - criterion mentions a file path -> check it exists
  file_contains - criterion mentions content in a file -> grep for keywords
  http_status   - criterion mentions a URL/endpoint -> curl for 200
  command_runs  - criterion mentions a command -> run it, check exit 0
  artifact_hit  - criterion mentions a path -> check artifacts_touched
  unverifiable  - no deterministic probe possible -> tagged honestly

Usage:
    python3 verify-outcome.py <completion.json>
    python3 verify-outcome.py <completion.json> --run-record <run.json>

Output: JSON verification result to stdout. Also patches completion.json
with verification_result field.

Exit codes:
    0 = all verifiable criteria passed
    1 = at least one verifiable criterion failed
    2 = error (missing files, bad input)
"""

import json
import os
import re
import subprocess
import sys

BRAIN = os.path.os.environ.get("BRAIN_DIR", os.path.expanduser("~/brain"))


def extract_file_paths(text):
    """Extract file paths from criterion text."""
    paths = []
    # Backtick-enclosed paths
    for m in re.finditer(r'`([^`]{3,80})`', text):
        val = m.group(1).strip()
        if '/' in val and not val.startswith(('http', 'ssh', 'git ', 'npm ')):
            paths.append(val)
    # Bare paths that look like file references
    for m in re.finditer(r'(?:in |at |to |from )([a-zA-Z][\w./\-]+\.\w{1,5})', text):
        paths.append(m.group(1))
    return paths


def extract_urls(text):
    """Extract URLs or endpoint paths from criterion text."""
    urls = []
    # Full URLs
    for m in re.finditer(r'(https?://[^\s,\)]+)', text):
        urls.append(m.group(1).rstrip('.'))
    # Endpoint paths like /health, /api/
    for m in re.finditer(r'(/(?:health|api|status)\S*)\s', text):
        urls.append(m.group(1))
    return urls


def extract_commands(text):
    """Extract runnable commands from criterion text."""
    commands = []
    # Backtick-enclosed commands
    for m in re.finditer(r'`(brain-\S+[^`]*)`', text):
        cmd = m.group(1).strip()
        if not cmd.endswith(('.md', '.json', '.py', '.sh', '.js')):
            commands.append(cmd)
    # "X passes" or "X runs" patterns
    for m in re.finditer(r'(brain-\S+)\s+(?:passes|runs|works|returns)', text):
        commands.append(m.group(1))
    return commands


def extract_keywords(text):
    """Extract significant keywords for content verification."""
    stop = {'the', 'a', 'an', 'is', 'are', 'was', 'and', 'or', 'to', 'in',
            'of', 'for', 'on', 'at', 'by', 'with', 'from', 'that', 'this',
            'must', 'should', 'not', 'has', 'have', 'been', 'can', 'will'}
    words = re.findall(r'[a-z]{4,}', text.lower())
    return [w for w in words if w not in stop][:5]


def build_probes(criterion, artifacts_touched):
    """Build verification probes from a criterion string."""
    probes = []

    # 1. File existence checks
    paths = extract_file_paths(criterion)
    for p in paths:
        # Resolve relative to brain
        full = os.path.join(BRAIN, p) if not p.startswith('/') else p
        probes.append({
            "type": "file_exists",
            "target": p,
            "full_path": full,
        })

        # Also check if this file is in artifacts_touched
        if artifacts_touched:
            if any(p in a or a.endswith(p) for a in artifacts_touched):
                probes.append({
                    "type": "artifact_hit",
                    "target": p,
                })

    # 2. URL/endpoint checks
    urls = extract_urls(criterion)
    for u in urls:
        if u.startswith('/'):
            continue  # Local endpoint, would need host info
        probes.append({
            "type": "http_status",
            "target": u,
        })

    # 3. Command checks
    commands = extract_commands(criterion)
    for cmd in commands:
        probes.append({
            "type": "command_runs",
            "target": cmd,
        })

    # 4. If criterion mentions a directory, check something was written there
    dir_match = re.search(r'(?:in|to|at)\s+`?([a-zA-Z][\w./\-]+/)`?', criterion)
    if dir_match:
        dirpath = dir_match.group(1)
        full = os.path.join(BRAIN, dirpath) if not dirpath.startswith('/') else dirpath
        if not any(p['type'] == 'file_exists' for p in probes):
            probes.append({
                "type": "dir_has_content",
                "target": dirpath,
                "full_path": full,
            })

    # 5. For paths that look partial (e.g., "completed/"), try common brain prefixes
    for probe in list(probes):
        if probe["type"] in ("file_exists", "dir_has_content"):
            if not os.path.exists(probe["full_path"]):
                # Try with brain/ops/tasks/ prefix
                for prefix in ["brain/ops/tasks/", "brain/ops/", "work/", "brain/"]:
                    alt = os.path.join(BRAIN, prefix, probe["target"])
                    if os.path.exists(alt):
                        probe["full_path"] = alt
                        break

    return probes


def run_probe(probe):
    """Execute a single verification probe. Returns (passed: bool, detail: str)."""
    ptype = probe["type"]

    if ptype == "file_exists":
        exists = os.path.isfile(probe["full_path"])
        if not exists:
            # Try as directory
            exists = os.path.isdir(probe["full_path"])
        return exists, f"{'exists' if exists else 'not found'}: {probe['target']}"

    elif ptype == "dir_has_content":
        path = probe["full_path"]
        if os.path.isdir(path):
            contents = os.listdir(path)
            has = len(contents) > 0
            return has, f"{'has content' if has else 'empty'}: {probe['target']} ({len(contents)} items)"
        return False, f"directory not found: {probe['target']}"

    elif ptype == "http_status":
        url = probe["target"]
        try:
            result = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 "-L", "--max-time", "10", url],
                capture_output=True, text=True, timeout=15
            )
            code = result.stdout.strip()
            passed = code in ("200", "301", "302")
            return passed, f"HTTP {code}: {url}"
        except Exception as e:
            return False, f"request failed: {url} ({e})"

    elif ptype == "command_runs":
        cmd = probe["target"]
        try:
            # Only allow brain-* commands for safety
            if not cmd.startswith("brain-"):
                return False, f"skipped (not a brain- command): {cmd}"
            # Expand to full path
            full_cmd = os.path.expanduser(f"~/bin/{cmd}")
            if not os.path.isfile(full_cmd.split()[0]):
                return False, f"command not found: {cmd}"
            result = subprocess.run(
                full_cmd.split(), capture_output=True, text=True, timeout=30,
                cwd=os.path.os.environ.get("BRAIN_DIR", os.path.expanduser("~/brain"))
            )
            passed = result.returncode == 0
            return passed, f"{'passed' if passed else 'failed'} (exit {result.returncode}): {cmd}"
        except Exception as e:
            return False, f"execution error: {cmd} ({e})"

    elif ptype == "artifact_hit":
        return True, f"found in artifacts_touched: {probe['target']}"

    return False, f"unknown probe type: {ptype}"


def verify_task(completion_path, run_record_path=None):
    """Run outcome verification on a completed task."""
    with open(completion_path) as f:
        completion = json.load(f)

    # Load criteria from run record
    criteria = []
    if run_record_path and os.path.isfile(run_record_path):
        try:
            run = json.load(open(run_record_path))
            criteria = run.get("execution_pack", {}).get("completion_criteria", [])
        except Exception:
            pass

    # Also check criteria_met from completion (may have been enriched)
    criteria_met = completion.get("criteria_met", [])
    artifacts = completion.get("artifacts_touched", [])
    summary = completion.get("completion_summary", "")

    if not criteria:
        return {
            "status": "no_criteria",
            "message": "No completion criteria defined for this task",
            "checks": [],
            "summary_probes": [],
            "pass_count": 0,
            "fail_count": 0,
            "unverifiable_count": 0,
        }

    checks = []
    pass_count = 0
    fail_count = 0
    unverifiable_count = 0

    for criterion in criteria:
        probes = build_probes(criterion, artifacts)

        if not probes:
            # No deterministic probe possible
            # Check if this criterion was matched by text in criteria_met
            text_matched = criterion in criteria_met
            checks.append({
                "criterion": criterion,
                "status": "text_matched" if text_matched else "unverifiable",
                "probes": [],
                "detail": "Matched in criteria_met via text" if text_matched else "No deterministic probe available",
            })
            if text_matched:
                pass_count += 1
            else:
                unverifiable_count += 1
            continue

        # Run all probes for this criterion
        probe_results = []
        criterion_passed = False

        for probe in probes:
            passed, detail = run_probe(probe)
            probe_results.append({
                "type": probe["type"],
                "target": probe["target"],
                "passed": passed,
                "detail": detail,
            })
            if passed:
                criterion_passed = True

        # A criterion passes if ANY probe passes (they're alternatives, not all required)
        if criterion_passed:
            pass_count += 1
            status = "pass"
        else:
            fail_count += 1
            status = "fail"

        checks.append({
            "criterion": criterion,
            "status": status,
            "probes": probe_results,
        })

    # Summary URL probes: check any URLs mentioned in the completion summary
    # These aren't criteria-level checks but provide outcome evidence
    summary_probes = []
    summary_urls = extract_urls(summary)
    for url in summary_urls:
        if url.startswith('/'):
            continue
        passed, detail = run_probe({"type": "http_status", "target": url})
        summary_probes.append({
            "type": "http_status",
            "target": url,
            "passed": passed,
            "detail": detail,
        })

    # Overall verdict
    total_verifiable = pass_count + fail_count
    if fail_count > 0:
        overall = "fail"
    elif total_verifiable > 0:
        overall = "pass"
    else:
        overall = "unverifiable"

    # If we have summary probes, a failing URL downgrades the verdict
    summary_failures = [p for p in summary_probes if not p["passed"]]
    if summary_failures and overall == "pass":
        overall = "fail"
        fail_count += len(summary_failures)

    result = {
        "status": overall,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "unverifiable_count": unverifiable_count,
        "total_criteria": len(criteria),
        "checks": checks,
        "summary_probes": summary_probes,
    }

    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: verify-outcome.py <completion.json> [--run-record <run.json>]",
              file=sys.stderr)
        sys.exit(1)

    completion_path = sys.argv[1]
    run_record = None

    for i, arg in enumerate(sys.argv):
        if arg == "--run-record" and i + 1 < len(sys.argv):
            run_record = sys.argv[i + 1]

    if not os.path.isfile(completion_path):
        print(f"Error: {completion_path} not found", file=sys.stderr)
        sys.exit(2)

    # Auto-find run record if not specified
    if not run_record:
        task_id = json.load(open(completion_path)).get("task_id", "")
        candidate = os.path.join(BRAIN, "brain/ops/tasks/completed", f"{task_id}.run.json")
        if os.path.isfile(candidate):
            run_record = candidate

    result = verify_task(completion_path, run_record)

    # Patch completion JSON with verification result
    try:
        with open(completion_path) as f:
            completion = json.load(f)
        completion["verification_result"] = {
            "status": result["status"],
            "pass_count": result["pass_count"],
            "fail_count": result["fail_count"],
            "unverifiable_count": result["unverifiable_count"],
            "summary_urls_checked": len(result.get("summary_probes", [])),
        }
        with open(completion_path, "w") as f:
            json.dump(completion, f, indent=2)
            f.write("\n")
    except Exception:
        pass

    # Print full result
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")

    # Exit code reflects verification outcome
    if result["fail_count"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
