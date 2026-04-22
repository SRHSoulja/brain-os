#!/usr/bin/env python3
"""recall-similar.py -- Find similar completed tasks for pre-execution recall.

Scans completed/*.completion.json for tasks with matching node and/or
keyword overlap in title/summary. Returns top matches as structured JSON.

Usage:
    python3 recall-similar.py --title "Post Facebook hook" --node "content-and-docs"
    python3 recall-similar.py --title "Deploy blog post" --limit 5

Output: JSON array of matches to stdout.
Pure file I/O, no LLM, deterministic.
"""

import json
import os
import re
import sys

BRAIN = os.path.os.environ.get("BRAIN_DIR", os.path.expanduser("~/brain"))
COMPLETED_DIR = os.path.join(BRAIN, "brain/ops/tasks/completed")


def tokenize(text):
    """Extract significant words from text."""
    if not text:
        return set()
    stop = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "and",
            "or", "to", "in", "of", "for", "on", "at", "by", "with", "from",
            "that", "this", "it", "its", "task", "brain", "run", "completed"}
    words = set(re.findall(r'[a-z]{3,}', text.lower())) - stop
    return words


def score_match(query_tokens, query_node, candidate):
    """Score a candidate completion against query. Higher = more similar."""
    score = 0

    # Node match is a strong signal
    c_node = candidate.get("node", "")
    if query_node and c_node == query_node:
        score += 3

    # Keyword overlap in summary
    c_summary = candidate.get("completion_summary", "")
    c_tokens = tokenize(c_summary)
    overlap = query_tokens & c_tokens
    score += len(overlap) * 2

    # Bonus for having artifacts (richer recall value)
    if candidate.get("artifacts_touched"):
        score += 1

    # Bonus for having implementation notes
    if candidate.get("implementation_notes"):
        score += 1

    return score


def find_similar(title, node="", limit=3):
    """Find similar completed tasks."""
    if not os.path.isdir(COMPLETED_DIR):
        return []

    query_tokens = tokenize(title)
    if not query_tokens:
        return []

    candidates = []
    for fname in os.listdir(COMPLETED_DIR):
        if not fname.endswith(".completion.json"):
            continue
        path = os.path.join(COMPLETED_DIR, fname)
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        score = score_match(query_tokens, node, data)
        if score > 0:
            candidates.append((score, data))

    # Sort by score descending, then by completed_on descending (most recent first)
    candidates.sort(key=lambda x: (x[0], x[1].get("completed_on", "")), reverse=True)

    results = []
    for score, data in candidates[:limit]:
        results.append({
            "task_id": data.get("task_id", ""),
            "summary": data.get("completion_summary", "")[:200],
            "notes": data.get("implementation_notes", "")[:150],
            "artifacts": data.get("artifacts_touched", [])[:5],
            "criteria_met": data.get("criteria_met", []),
            "duration_minutes": data.get("duration_minutes"),
            "node": data.get("node", ""),
            "completed_on": data.get("completed_on", ""),
            "score": score,
        })

    return results


def main():
    title = ""
    node = ""
    limit = 3

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--title" and i + 1 < len(args):
            title = args[i + 1]
            i += 2
        elif args[i] == "--node" and i + 1 < len(args):
            node = args[i + 1]
            i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        else:
            # Treat positional as title
            title = args[i]
            i += 1

    if not title:
        print("Usage: recall-similar.py --title <title> [--node <node>] [--limit N]",
              file=sys.stderr)
        sys.exit(1)

    results = find_similar(title, node, limit)
    json.dump(results, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
