#!/usr/bin/env python3
"""infer-impact.py — Lightweight impact metric inference from task content.

Scans task title, description, output, and notes for keywords and suggests
the most relevant product metric. Deterministic, no external dependencies.

Usage:
    python3 infer-impact.py <task_file> [output_text]
    python3 infer-impact.py --test   # run self-tests

Output (tab-separated):
    metric\tprevious\tnext

If no match or excluded: exits with no output and exit code 0.
"""

import re
import sys

# Nodes that never affect funnel metrics -- exclude immediately, no inference
EXCLUDED_NODES = {
    "multi-agent-infra",
    "brain-ops",
    "devops-tools",
}

# Title keywords that indicate meta-infrastructure work -- exclude from inference
EXCLUDED_TITLE_KEYWORDS = [
    "verification",
    "baseline",
    "smoke test",
    "audit",
    "poe",
    "proof",
]

# Keyword → metric mapping, ordered by specificity (most specific first)
RULES = [
    # Analytics / tracking
    (["funnel", "conversion", "tracking"], "funnel_events", "unknown", "measurable"),
    (["analytics", "event", "instrumentation"], "funnel_events", "unknown", "measurable"),

    # Onboarding
    (["onboarding", "first-run", "first run", "welcome"], "archive_to_dashboard_conversion", "unknown", "measurable"),

    # Dashboard
    (["dashboard", "activation", "setup wizard"], "dashboard_activation_rate", "baseline", "improved"),

    # Player / clips
    (["player", "clip view", "clip play", "playback"], "clip_player_views", "unknown", "measurable"),
    (["clip", "archive"], "clip_player_views", "unknown", "measurable"),

    # Growth
    (["growth", "acquisition", "discover"], "user_acquisition", "unknown", "measurable"),
    (["signup", "registration", "sign up"], "signup_conversion", "unknown", "measurable"),

    # Creator
    (["creator", "streamer setup", "streamer onboard"], "creator_activation", "unknown", "measurable"),

    # Monetization
    (["monetization", "revenue", "pricing", "payment"], "revenue", "unknown", "measurable"),
    (["subscription", "pro", "premium"], "creator_pro_conversion", "0%", "measurable"),

    # Streaming
    (["stream", "broadcast", "live"], "stream_engagement", "unknown", "measurable"),

    # Infrastructure
    (["monitor", "uptime", "health check"], "service_uptime", "unknown", "monitored"),
    (["deploy", "infrastructure", "railway"], "deploy_reliability", "manual", "automated"),
]


def is_excluded(node="", title=""):
    """Return True if this task should never produce a funnel-metric attribution."""
    if node in EXCLUDED_NODES:
        return True
    title_lower = title.lower()
    return any(kw in title_lower for kw in EXCLUDED_TITLE_KEYWORDS)


def infer(title, description="", output="", notes=""):
    """Return (metric, previous, next) or None."""
    text = f"{title} {description} {output} {notes}".lower()

    best = None
    best_score = 0

    for keywords, metric, prev, nxt in RULES:
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best = (metric, prev, nxt)

    return best if best_score > 0 else None


def _run_tests():
    passed = 0
    failed = 0

    def check(label, condition):
        nonlocal passed, failed
        if condition:
            print(f"  PASS: {label}")
            passed += 1
        else:
            print(f"  FAIL: {label}")
            failed += 1

    print("=== infer-impact.py self-tests ===")

    # Exclusion by node
    check("excluded node: multi-agent-infra", is_excluded(node="multi-agent-infra", title="anything"))
    check("excluded node: brain-ops", is_excluded(node="brain-ops", title="anything"))
    check("excluded node: devops-tools", is_excluded(node="devops-tools", title="anything"))
    check("non-excluded node: coaching", not is_excluded(node="coaching", title="launch cohort waitlist"))

    # Exclusion by title keyword
    check("excluded title: verification", is_excluded(node="", title="Gemini verification run"))
    check("excluded title: audit", is_excluded(node="", title="Audit Discord MCP servers"))
    check("excluded title: proof", is_excluded(node="", title="proof-of-execution check"))
    check("excluded title: smoke test", is_excluded(node="", title="smoke test for Ollama"))
    check("excluded title: baseline", is_excluded(node="", title="capture baseline metrics"))
    check("excluded title: poe", is_excluded(node="", title="poe attribution desync fix"))

    # Title containing 'proof' or 'pro' substring should not bleed into creator_pro_conversion
    check("'proof' title excluded (no false pro match)",
          is_excluded(node="", title="proof-of-execution integration"))
    check("'pro' standalone still infers if not excluded",
          infer("upgrade pro subscription flow") is not None)

    # Legitimate inference paths
    check("infers clip metric from title", infer("clip player buffering fix") == ("clip_player_views", "unknown", "measurable"))
    check("infers revenue metric", infer("pricing page redesign") == ("revenue", "unknown", "measurable"))
    check("infers deploy metric", infer("deploy railway infrastructure") == ("deploy_reliability", "manual", "automated"))
    check("no match returns None", infer("fix YAML parse bug in brain-paths.sh") is None)

    # Excluded node produces None even with matching keywords
    check("excluded node suppresses clip match",
          is_excluded(node="multi-agent-infra", title="clip routing audit"))

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--test":
        sys.exit(0 if _run_tests() else 1)

    if len(sys.argv) < 2:
        sys.exit(0)

    task_file = sys.argv[1]
    output_text = sys.argv[2] if len(sys.argv) > 2 else ""
    notes_text = sys.argv[3] if len(sys.argv) > 3 else ""

    try:
        with open(task_file, 'r') as f:
            content = f.read()
    except OSError:
        sys.exit(0)

    # Extract title and description
    title_match = re.search(r'^# (.+)$', content, re.MULTILINE)
    title = title_match.group(1) if title_match else ""

    desc_match = re.search(r'^## Description\s*\n([\s\S]*?)(?=^## |\Z)', content, re.MULTILINE)
    description = desc_match.group(1).strip() if desc_match else ""

    # Extract node from frontmatter
    node_match = re.search(r'^node:\s*["\']?([^"\'\n]+)["\']?\s*$', content, re.MULTILINE)
    node = node_match.group(1).strip() if node_match else ""

    # Exclusion check -- meta-infra tasks produce no funnel attribution
    if is_excluded(node, title):
        sys.exit(0)

    result = infer(title, description, output_text, notes_text)

    if result:
        metric, prev, nxt = result
        print(f"{metric}\t{prev}\t{nxt}")


if __name__ == "__main__":
    main()
