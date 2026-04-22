#!/usr/bin/env python3
"""confidence-check.py — Deterministic confidence gate for autonomous task execution.

Reads a compiled execution pack (JSON from stdin or --pack-file) and evaluates
whether the task should proceed, warn, or stop in autonomous (--next) mode.

Verdict levels:
  PASS  — no confidence signals triggered; autonomous execution is clear
  WARN  — soft signals present; proceed but surface them
  STOP  — hard stop; autonomous execution must not proceed without human review

STOP triggers:
  REQUIRED_REVIEW_INPUT_MISSING — P1/P2 task has a file: (or untyped path-like) entry
    in required_review_inputs that does not exist on disk at launch time.

WARN triggers:
  AMBIGUOUS_TITLE                       — title contains TBD/FIXME/???/unclear/etc.
  MISSING_REQUIRED_REVIEW_INPUTS_FIELD  — P1/P2 with no required_review_inputs declared
  MAY_SPAWN_TASKS_ON_HIGH_PRIORITY      — P1/P2 with may_spawn_tasks: true
  REQUIRED_REVIEW_INPUT_MALFORMED_URL   — url: entry scheme is not http:// or https://
  REQUIRED_REVIEW_INPUT_TASK_NOT_COMPLETE — task: entry not found in completed/
  REQUIRED_REVIEW_INPUT_UNTYPED         — untyped, non-path entry cannot be machine-verified

required_review_inputs entry forms:
  file:<path>  — local artifact; STOP if missing
  url:<uri>    — external reference; WARN if scheme not http/https
  task:<id>    — completed task dependency; WARN if not in completed/
  note:<text>  — advisory only; no machine check
  <untyped>    — path-like (has slash/path-prefix) → file: behavior; else WARN

Note: stop_and_ask_conditions is NOT evaluated here. That field is in-execution
guidance for the executing agent, not a pre-execution autonomous block. The
autonomous-block mechanism is authority_owner: human/mixed, enforced separately
in brain-task-execute before this gate runs.

Triggers are deterministic field checks. No agent judgment involved.

Usage:
    python3 confidence-check.py <task_id> [--next] [--pack-file <path>]
    echo '<pack_json>' | python3 confidence-check.py <task_id> [--next]

Output (JSON):
    {
      "verdict": "PASS" | "WARN" | "STOP",
      "signals": [{"level": "STOP"|"WARN", "code": str, "detail": str}],
      "reason": str,
      "task_id": str
    }

Exit: always 0 — caller reads JSON verdict, not exit code.
"""

import json
import os
import re
import sys


# Patterns in title that indicate incomplete specification.
# Matched case-insensitively against the task title only (not body).
_TITLE_AMBIGUITY_PATTERNS = [
    r"\bTBD\b",
    r"\bFIXME\b",
    r"\?\?\?",
    r"\bunclear\b",
    r"\bdecide:\b",
    r"\bopen question\b",
    r"\bto be determined\b",
]

_TITLE_AMBIGUITY_RE = re.compile(
    "|".join(_TITLE_AMBIGUITY_PATTERNS), re.IGNORECASE
)


def load_pack(task_id: str, pack_file: str | None) -> dict:
    if pack_file:
        with open(pack_file) as f:
            return json.load(f)
    raw = sys.stdin.read().strip()
    if raw:
        return json.loads(raw)
    # Fallback: locate compiled pack on disk
    brain = os.environ.get("BRAIN_DIR", os.environ.get("BRAIN_DIR", os.path.join(os.environ["HOME"], "brain")))
    candidates = [
        os.path.join(brain, "brain", "ops", "tasks", "active", f"{task_id}.run.json"),
        os.path.join(brain, "brain", "ops", "tasks", "queue", f"{task_id}.json"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            with open(path) as f:
                return json.load(f)
    return {}


def _is_path_like(s: str) -> bool:
    """Return True if an untyped entry looks like a file path (has a slash or path prefix)."""
    return s.startswith(("/", "./", "../", "~/")) or "/" in s


def check_required_review_inputs(contract: dict, priority: str, brain: str) -> list[dict]:
    """Typed required_review_inputs dispatch for P1/P2 tasks.

    Entry forms:
      file:<path>   — local artifact; STOP if missing on disk
      url:<uri>     — external reference; WARN if scheme is not http:// or https://
      task:<id>     — completed task dependency; WARN if not found in completed/
      note:<text>   — advisory only; no machine check
      <untyped>     — path-like (contains slash or path prefix) → legacy file: behavior
                      non-path-like → WARN: REQUIRED_REVIEW_INPUT_UNTYPED
    """
    if priority not in ("P1", "P2"):
        return []
    inputs = contract.get("required_review_inputs", [])
    if not inputs:
        return [{
            "level": "WARN",
            "code": "MISSING_REQUIRED_REVIEW_INPUTS_FIELD",
            "detail": (
                f"{priority} task has no required_review_inputs declared. "
                "High-priority tasks should specify review artifacts."
            ),
        }]

    completed_dir = os.path.join(brain, "brain", "ops", "tasks", "completed")
    signals = []

    for raw in inputs:
        entry = str(raw).strip()

        if entry.startswith("file:"):
            path_str = entry[len("file:"):]
            path = path_str if os.path.isabs(path_str) else os.path.join(brain, path_str)
            if not os.path.exists(path):
                signals.append({
                    "level": "STOP",
                    "code": "REQUIRED_REVIEW_INPUT_MISSING",
                    "detail": f"Required review artifact does not exist on disk: {path_str}",
                })

        elif entry.startswith("url:"):
            uri = entry[len("url:"):]
            if not (uri.startswith("http://") or uri.startswith("https://")):
                signals.append({
                    "level": "WARN",
                    "code": "REQUIRED_REVIEW_INPUT_MALFORMED_URL",
                    "detail": (
                        f"url: entry does not start with http:// or https://: {uri!r}"
                    ),
                })

        elif entry.startswith("task:"):
            task_id = entry[len("task:"):]
            task_path = os.path.join(completed_dir, f"{task_id}.md")
            if not os.path.exists(task_path):
                signals.append({
                    "level": "WARN",
                    "code": "REQUIRED_REVIEW_INPUT_TASK_NOT_COMPLETE",
                    "detail": (
                        f"Required task dependency not found in completed/: {task_id}"
                    ),
                })

        elif entry.startswith("note:"):
            pass  # advisory only; no machine check

        else:
            # Untyped entry: path-like → legacy file behavior; otherwise WARN
            if _is_path_like(entry):
                path = entry if os.path.isabs(entry) else os.path.join(brain, entry)
                if not os.path.exists(path):
                    signals.append({
                        "level": "STOP",
                        "code": "REQUIRED_REVIEW_INPUT_MISSING",
                        "detail": f"Required review artifact does not exist on disk: {entry}",
                    })
            else:
                signals.append({
                    "level": "WARN",
                    "code": "REQUIRED_REVIEW_INPUT_UNTYPED",
                    "detail": (
                        f"Untyped, non-path entry cannot be verified: {entry!r}. "
                        "Use file:, url:, task:, or note: prefix."
                    ),
                })

    return signals


def check_title_ambiguity(title: str) -> list[dict]:
    """Title contains explicit ambiguity markers → WARN (not STOP: false-positive risk)."""
    m = _TITLE_AMBIGUITY_RE.search(title)
    if m:
        return [{
            "level": "WARN",
            "code": "AMBIGUOUS_TITLE",
            "detail": (
                f"Task title contains ambiguity marker '{m.group(0)}'. "
                "Confirm the task is fully specified before autonomous execution."
            ),
        }]
    return []


def check_may_spawn_tasks(contract: dict, priority: str) -> list[dict]:
    """P1/P2 with may_spawn_tasks: true → WARN; autonomous spawning on high-priority tasks
    can introduce untracked work chains."""
    if priority not in ("P1", "P2"):
        return []
    if contract.get("may_spawn_tasks") is True:
        return [{
            "level": "WARN",
            "code": "MAY_SPAWN_TASKS_ON_HIGH_PRIORITY",
            "detail": (
                f"{priority} task allows spawning follow-up tasks. "
                "Confirm this is intentional — autonomous spawning on high-priority tasks "
                "can introduce untracked work."
            ),
        }]
    return []


def _normalize_priority(raw: str) -> str:
    """Normalize numeric-style priority to P-prefixed form.

    brain-task-pack may emit priority as "1" or "2" (string, no prefix) for
    tasks whose frontmatter uses numeric-style priority. Normalize to "P1"/"P2"
    so all comparison logic operates on a single canonical form.
    """
    s = str(raw).strip()
    if s and not s.startswith("P") and s.isdigit():
        return f"P{s}"
    return s


def run(task_id: str, pack: dict) -> dict:
    brain = os.environ.get("BRAIN_DIR", os.environ.get("BRAIN_DIR", os.path.join(os.environ["HOME"], "brain")))
    contract = pack.get("execution_contract", {})
    priority = _normalize_priority(pack.get("priority", ""))
    title = pack.get("title", "")

    signals: list[dict] = []
    signals += check_required_review_inputs(contract, priority, brain)
    signals += check_title_ambiguity(title)
    signals += check_may_spawn_tasks(contract, priority)

    stop_signals = [s for s in signals if s["level"] == "STOP"]
    warn_signals = [s for s in signals if s["level"] == "WARN"]

    if stop_signals:
        verdict = "STOP"
        reason = f"{len(stop_signals)} stop signal(s): " + "; ".join(
            s["code"] for s in stop_signals
        )
    elif warn_signals:
        verdict = "WARN"
        reason = f"{len(warn_signals)} warn signal(s): " + "; ".join(
            s["code"] for s in warn_signals
        )
    else:
        verdict = "PASS"
        reason = "no confidence signals triggered"

    return {
        "verdict": verdict,
        "signals": signals,
        "reason": reason,
        "task_id": task_id,
    }


def main():
    task_id = ""
    pack_file = None
    next_mode = False  # reserved for future caller-context-aware logic

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--pack-file" and i + 1 < len(args):
            pack_file = args[i + 1]
            i += 2
        elif args[i] == "--next":
            next_mode = True
            i += 1
        elif not args[i].startswith("-"):
            task_id = args[i]
            i += 1
        else:
            i += 1

    try:
        pack = load_pack(task_id, pack_file)
    except Exception as e:
        print(json.dumps({
            "verdict": "WARN",
            "signals": [{"level": "WARN", "code": "PACK_LOAD_ERROR", "detail": str(e)}],
            "reason": f"could not load pack: {e}",
            "task_id": task_id,
        }))
        return

    result = run(task_id, pack)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
