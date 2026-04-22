#!/usr/bin/env python3
"""verdict-reader.py — Canonical reader for state-verdict.json

Reads, normalizes, and validates the brain state verdict.
Dependency-free (stdlib only). Deterministic output.

Usage from CLI:
    python3 verdict-reader.py <path>                   # tab-separated: status, summary, issue_count, timestamp, queued, active, completed
    python3 verdict-reader.py <path> --field status     # single field
    python3 verdict-reader.py <path> --json             # normalized JSON to stdout
    python3 verdict-reader.py <path> --issues           # one issue per line: [LEVEL] CODE — message

Usage from Python:
    from verdict_reader import read_verdict
    v = read_verdict("/path/to/state-verdict.json")
    # v is always a complete dict with every field present

Exit codes match brain-state-check:
    0 = OK
    1 = DRIFT or CONFLICT
    2 = STALE
"""

import json
import sys
import os

VALID_STATUSES = frozenset(("OK", "STALE", "DRIFT", "CONFLICT"))

def _corruption_verdict(reason):
    """Return a DRIFT verdict with a synthetic issue explaining the corruption."""
    return {
        "timestamp": "",
        "status": "DRIFT",
        "summary": reason,
        "task_counts": {"queued": 0, "active": 0, "completed": 0},
        "issue_count": 1,
        "issues": [{"level": "DRIFT", "code": "VERDICT_CORRUPT", "message": reason}],
    }


def read_verdict(path):
    """Read and normalize state-verdict.json. Always returns a complete dict."""
    try:
        with open(path, "r") as f:
            raw = json.load(f)
    except OSError as e:
        return _corruption_verdict(f"Cannot read verdict file: {e.strerror}")
    except json.JSONDecodeError:
        return _corruption_verdict("Verdict file contains invalid JSON")
    except TypeError:
        return _corruption_verdict("Invalid path to verdict file")

    if not isinstance(raw, dict):
        return _corruption_verdict(f"Verdict root is {type(raw).__name__}, expected object")

    # -- status: must be a known string, else DRIFT --
    status_was_invalid = False
    status = raw.get("status", "DRIFT")
    if not isinstance(status, str) or status not in VALID_STATUSES:
        status_was_invalid = True
        status = "DRIFT"

    # -- summary --
    summary = raw.get("summary", "")
    if not isinstance(summary, str):
        summary = str(summary)

    # -- timestamp --
    timestamp = raw.get("timestamp", "")
    if not isinstance(timestamp, str):
        timestamp = str(timestamp)

    # -- timestamp: must look like ISO8601 if present --
    if timestamp and not _is_plausible_timestamp(timestamp):
        timestamp = ""

    # -- task_counts: enforce non-negative int values with defaults --
    tc_raw = raw.get("task_counts", {})
    if not isinstance(tc_raw, dict):
        tc_raw = {}
    task_counts = {
        "queued": _safe_nonneg_int(tc_raw.get("queued", 0)),
        "active": _safe_nonneg_int(tc_raw.get("active", 0)),
        "completed": _safe_nonneg_int(tc_raw.get("completed", 0)),
    }

    # -- issues: validate as list of structured objects --
    issues_raw = raw.get("issues", [])
    if not isinstance(issues_raw, list):
        issues_raw = []

    issues = []
    for item in issues_raw:
        if isinstance(item, dict):
            level = item.get("level", "DRIFT")
            if not isinstance(level, str) or level not in VALID_STATUSES:
                level = "DRIFT"
            code = item.get("code", "UNKNOWN")
            if not isinstance(code, str):
                code = str(code)
            message = item.get("message", "")
            if not isinstance(message, str):
                message = str(message)
            issues.append({"level": level, "code": code, "message": message})
        elif isinstance(item, str):
            # Legacy format: "DRIFT: label — detail"
            issues.append({"level": "DRIFT", "code": "LEGACY", "message": item})

    # -- inject synthetic issue if status was unrecognized --
    if status_was_invalid:
        original = raw.get("status", "(missing)")
        issues.insert(0, {
            "level": "DRIFT",
            "code": "VERDICT_INVALID_STATUS",
            "message": f"Unrecognized status '{original}' normalized to DRIFT",
        })

    # -- issue_count: always recalculated from normalized issues --
    issue_count = len(issues)

    return {
        "timestamp": timestamp,
        "status": status,
        "summary": summary,
        "task_counts": task_counts,
        "issue_count": issue_count,
        "issues": issues,
    }


def _safe_nonneg_int(val):
    """Coerce to non-negative int, default 0. Negative values become 0."""
    try:
        n = int(val)
        return n if n >= 0 else 0
    except (TypeError, ValueError):
        return 0


def _is_plausible_timestamp(ts):
    """Check if a string looks like an ISO8601 timestamp (YYYY-MM-DD...)."""
    if len(ts) < 10:
        return False
    # Must start with 4-digit year, dash, 2-digit month, dash, 2-digit day
    try:
        return ts[4] == "-" and ts[7] == "-" and ts[:4].isdigit() and ts[5:7].isdigit()
    except IndexError:
        return False


def _exit_code(status):
    """Map status to brain-state-check exit code."""
    if status in ("DRIFT", "CONFLICT"):
        return 1
    if status == "STALE":
        return 2
    return 0


def main():
    if len(sys.argv) < 2:
        print("Usage: verdict-reader.py <path> [--field <name>|--json|--issues]", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    v = read_verdict(path)

    # --json: output normalized verdict
    if "--json" in sys.argv:
        json.dump(v, sys.stdout, indent=2)
        sys.stdout.write("\n")
        sys.exit(_exit_code(v["status"]))

    # --field: single field value
    if "--field" in sys.argv:
        idx = sys.argv.index("--field")
        if idx + 1 >= len(sys.argv):
            print("--field requires a field name", file=sys.stderr)
            sys.exit(1)
        field = sys.argv[idx + 1]
        if field == "tasks":
            tc = v["task_counts"]
            print(f"{tc['queued']}q/{tc['active']}a/{tc['completed']}c")
        elif field in v:
            val = v[field]
            if isinstance(val, (dict, list)):
                print(json.dumps(val))
            else:
                print(val)
        else:
            print(f"Unknown field: {field}", file=sys.stderr)
            sys.exit(1)
        sys.exit(_exit_code(v["status"]))

    # --issues: one per line
    if "--issues" in sys.argv:
        for issue in v["issues"]:
            print(f"  [{issue['level']}] {issue['code']} — {issue['message']}")
        sys.exit(_exit_code(v["status"]))

    # Default: tab-separated compact output for bash consumption
    # status \t summary \t issue_count \t timestamp \t queued \t active \t completed
    tc = v["task_counts"]
    print(f"{v['status']}\t{v['summary']}\t{v['issue_count']}\t{v['timestamp']}\t{tc['queued']}\t{tc['active']}\t{tc['completed']}")
    sys.exit(_exit_code(v["status"]))


if __name__ == "__main__":
    main()
