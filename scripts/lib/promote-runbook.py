#!/usr/bin/env python3
"""promote-runbook.py -- Classify and promote runbooks into distributable outputs.

Scans runbooks, scores them for external value, and generates promoted
outputs for blog, product, or internal reference.

Usage:
    python3 promote-runbook.py <runbook.md>              # promote one
    python3 promote-runbook.py --scan                     # scan all, promote worthy ones
    python3 promote-runbook.py --scan --dry-run           # preview without writing

Classification:
    blog        - contains a lesson others can learn from
    product     - documents a reusable system/pattern
    internal    - useful inside CLIP only

Output: promoted markdown at work/outputs/promoted/<classification>/<task-id>.md
"""

import os
import re
import sys
from datetime import datetime

BRAIN = os.path.os.environ.get("BRAIN_DIR", os.path.expanduser("~/brain"))
RUNBOOKS_DIR = os.path.join(BRAIN, "work/outputs/runbooks")
PROMOTED_DIR = os.path.join(BRAIN, "work/outputs/promoted")

# Minimum score thresholds
BLOG_THRESHOLD = 8
PRODUCT_THRESHOLD = 9


def parse_runbook(path):
    """Parse a runbook markdown into structured data."""
    with open(path) as f:
        content = f.read()

    data = {"path": path, "content": content}

    # Frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            for line in content[3:end].split("\n"):
                m = re.match(r'^(\w+):\s*"?([^"]+)"?', line.strip())
                if m:
                    data[m.group(1)] = m.group(2).strip()

    # Sections
    for section in ["What Was Done", "Steps Taken", "Verified Criteria",
                     "Lessons Learned", "Constraints Applied", "Reuse Instructions",
                     "Files Changed", "Quick Reference"]:
        pattern = rf"^## {re.escape(section)}\s*\n([\s\S]*?)(?=^## |\Z)"
        m = re.search(pattern, content, re.MULTILINE)
        key = section.lower().replace(" ", "_")
        data[key] = m.group(1).strip() if m else ""

    # Title
    m = re.search(r"^# (.+)$", content, re.MULTILINE)
    data["title"] = m.group(1).strip() if m else ""

    # Counts
    data["criteria_count"] = content.count("- [x]")
    data["word_count"] = len(content.split())

    return data


def score_blog(data):
    """Score a runbook for blog potential. Higher = more publishable."""
    score = 0
    lessons = data.get("lessons_learned", "")
    what = data.get("what_was_done", "")
    title = data.get("title", "").lower()
    constraints = data.get("constraints_applied", "")

    # Must have lessons -- this is the core blog signal
    if not lessons:
        return 0

    # Lessons with causal insight ("because", "root cause", "turned out")
    lessons_l = lessons.lower()
    if any(w in lessons_l for w in ["because", "root cause", "turned out",
                                     "discovered", "realized", "caught",
                                     "would have", "the real", "actually"]):
        score += 4

    # Lessons with surprise or correction
    if any(w in lessons_l for w in ["wrong", "error", "broken", "missed",
                                     "silent", "false positive", "failed"]):
        score += 3

    # Lessons with a transferable pattern
    if any(w in lessons_l for w in ["always", "never", "pattern", "rule",
                                     "configurable", "threshold", "policy"]):
        score += 2

    # Verified criteria = proof the lesson is grounded
    score += min(data.get("criteria_count", 0), 3)

    # Constraints show the design thinking
    if constraints:
        score += 2

    # Length matters -- too short means no substance
    if data.get("word_count", 0) > 200:
        score += 1

    # Verification passed = trustworthy
    if data.get("verification") == "pass":
        score += 1

    return score


def score_product(data):
    """Score a runbook for product/system documentation value."""
    score = 0
    what = data.get("what_was_done", "")
    steps = data.get("steps_taken", "")
    criteria = data.get("verified_criteria", "")
    reuse = data.get("reuse_instructions", "")
    title = data.get("title", "").lower()
    task_type = data.get("source_task_type", "")

    # Build tasks with steps = reusable system pattern
    if task_type == "build" and steps:
        score += 3

    # High criteria count = well-documented system
    cc = data.get("criteria_count", 0)
    if cc >= 5:
        score += 3
    elif cc >= 3:
        score += 2

    # Reuse instructions that aren't generic
    if reuse and len(reuse) > 50:
        score += 2

    # System-building keywords in title
    if any(w in title for w in ["policy", "system", "pipeline", "framework",
                                 "architecture", "engine", "dashboard",
                                 "export", "import", "tool", "utility"]):
        score += 2

    # Constraints show architectural thinking
    if data.get("constraints_applied"):
        score += 2

    # Verification passed
    if data.get("verification") == "pass":
        score += 1

    # Substantial content
    if data.get("word_count", 0) > 250:
        score += 1

    return score


def classify(data):
    """Classify a runbook into blog, product, or internal."""
    blog_score = score_blog(data)
    product_score = score_product(data)

    if blog_score >= BLOG_THRESHOLD and blog_score >= product_score:
        return "blog", blog_score
    elif product_score >= PRODUCT_THRESHOLD:
        return "product", product_score
    elif blog_score >= BLOG_THRESHOLD:
        return "blog", blog_score
    else:
        return "internal", max(blog_score, product_score)


def extract_core_insight(data):
    """Extract the single most important insight from a runbook."""
    lessons = data.get("lessons_learned", "")
    if lessons:
        # Take the first sentence that contains causal language
        for sent in re.split(r'(?<=[.!])\s+', lessons):
            if any(w in sent.lower() for w in ["because", "root cause", "turned out",
                                                 "caught", "would have", "actually",
                                                 "the real", "discovered"]):
                return sent.strip()
        # Fall back to first sentence
        first = re.split(r'(?<=[.!])\s+', lessons)[0]
        return first.strip() if first else ""
    return ""


def extract_reusable_pattern(data):
    """Extract the reusable pattern from a runbook."""
    constraints = data.get("constraints_applied", "")
    lessons = data.get("lessons_learned", "")
    reuse = data.get("reuse_instructions", "")

    parts = []

    # Pattern from constraints (design rules)
    if constraints:
        # Extract "do not" rules as they define boundaries
        for line in constraints.split("\n"):
            line = line.strip()
            if line.startswith("- ") and any(w in line.lower()
                                              for w in ["do not", "never", "must",
                                                        "only", "always"]):
                parts.append(line[2:])

    # Pattern from lessons (learned rules)
    if lessons:
        for sent in re.split(r'(?<=[.!])\s+', lessons):
            if any(w in sent.lower() for w in ["always", "never", "pattern",
                                                 "rule", "must", "threshold"]):
                parts.append(sent.strip())

    return parts[:5]


def suggest_title(data, classification):
    """Suggest a clean title for external use."""
    raw_title = data.get("title", "")
    # Strip "Build Runbook: " or "Deploy Runbook: " prefix
    clean = re.sub(r'^(Build|Deploy|Fix|Review|Documentation|General)\s+Runbook:\s*', '', raw_title)

    if classification == "blog":
        # Blog titles should be insight-driven
        insight = extract_core_insight(data)
        if insight and len(insight) < 80:
            return f"What I Learned: {clean}"
        return f"How We Built: {clean}"
    elif classification == "product":
        return f"System Pattern: {clean}"
    return clean


def generate_promoted(data, classification, blog_score, product_score):
    """Generate a promoted output from a runbook."""
    insight = extract_core_insight(data)
    patterns = extract_reusable_pattern(data)
    ext_title = suggest_title(data, classification)
    task_id = data.get("task_id", "unknown")

    lines = []
    lines.append("---")
    lines.append(f'task_id: "{task_id}"')
    lines.append(f'type: promoted')
    lines.append(f'classification: {classification}')
    lines.append(f'blog_score: {blog_score}')
    lines.append(f'product_score: {product_score}')
    lines.append(f'promoted_at: "{datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")}"')
    lines.append(f'source: "work/outputs/runbooks/{task_id}.md"')
    lines.append("---")
    lines.append("")

    lines.append(f"# {ext_title}")
    lines.append("")

    # Core insight (the hook)
    if insight:
        lines.append("## Core Insight")
        lines.append("")
        lines.append(insight)
        lines.append("")

    # What happened (clean summary)
    what = data.get("what_was_done", "")
    if what:
        lines.append("## Summary")
        lines.append("")
        # Strip the "**Goal:**" prefix line if present, keep the rest
        clean_what = re.sub(r'\*\*Goal:\*\*.*\n\n?', '', what).strip()
        if clean_what:
            lines.append(clean_what)
        else:
            lines.append(what)
        lines.append("")

    # Reusable patterns
    if patterns:
        lines.append("## Reusable Patterns")
        lines.append("")
        for p in patterns:
            lines.append(f"- {p}")
        lines.append("")

    # Steps (if substantial)
    steps = data.get("steps_taken", "")
    if steps and classification == "product":
        lines.append("## How It Works")
        lines.append("")
        lines.append(steps)
        lines.append("")

    # Verified criteria (proof)
    criteria = data.get("verified_criteria", "")
    if criteria:
        lines.append("## Verified")
        lines.append("")
        lines.append(criteria)
        lines.append("")

    # Lessons (full)
    lessons = data.get("lessons_learned", "")
    if lessons and classification == "blog":
        lines.append("## The Full Lesson")
        lines.append("")
        lines.append(lessons)
        lines.append("")

    # Audience value tag
    lines.append("## Who This Is For")
    lines.append("")
    if classification == "blog":
        lines.append("Anyone building AI-assisted systems who wants to avoid the same mistake or learn the same pattern.")
    elif classification == "product":
        lines.append("Builders who want to implement this pattern in their own system.")
    lines.append("")

    lines.append("---")
    lines.append(f"*Promoted from {task_id} by promote-runbook.py*")

    return "\n".join(lines)


def promote_one(path, dry_run=False):
    """Promote a single runbook. Returns (classification, score, output_path or None)."""
    data = parse_runbook(path)
    classification, score = classify(data)
    blog_score = score_blog(data)
    product_score = score_product(data)

    task_id = data.get("task_id", os.path.basename(path).replace(".md", ""))

    if classification == "internal":
        return classification, score, None

    promoted = generate_promoted(data, classification, blog_score, product_score)

    if dry_run:
        return classification, score, "(dry-run)"

    out_dir = os.path.join(PROMOTED_DIR, classification)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{task_id}.md")
    with open(out_path, "w") as f:
        f.write(promoted)

    return classification, score, out_path


def scan_all(dry_run=False):
    """Scan all runbooks and promote worthy ones."""
    if not os.path.isdir(RUNBOOKS_DIR):
        print("No runbooks directory found", file=sys.stderr)
        return

    results = {"blog": [], "product": [], "internal": []}

    for f in sorted(os.listdir(RUNBOOKS_DIR)):
        if not f.endswith(".md"):
            continue
        path = os.path.join(RUNBOOKS_DIR, f)
        classification, score, out_path = promote_one(path, dry_run)
        results[classification].append((f, score, out_path))

    # Print summary
    print(f"Scanned {sum(len(v) for v in results.values())} runbooks\n")

    if results["blog"]:
        print(f"BLOG CANDIDATES ({len(results['blog'])}):")
        for f, s, p in sorted(results["blog"], key=lambda x: -x[1]):
            status = p if p else "(not promoted)"
            print(f"  [{s:2}] {f:45} {status}")
        print()

    if results["product"]:
        print(f"PRODUCT/SYSTEM CANDIDATES ({len(results['product'])}):")
        for f, s, p in sorted(results["product"], key=lambda x: -x[1]):
            status = p if p else "(not promoted)"
            print(f"  [{s:2}] {f:45} {status}")
        print()

    internal_count = len(results["internal"])
    print(f"INTERNAL ONLY: {internal_count} runbooks (not promoted)")


def main():
    dry_run = "--dry-run" in sys.argv
    scan_mode = "--scan" in sys.argv

    # Filter out flags
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if scan_mode:
        scan_all(dry_run)
    elif args:
        path = args[0]
        if not os.path.isfile(path):
            # Try as task ID
            path = os.path.join(RUNBOOKS_DIR, f"{args[0]}.md")
        if not os.path.isfile(path):
            print(f"Error: {args[0]} not found", file=sys.stderr)
            sys.exit(1)
        classification, score, out_path = promote_one(path, dry_run)
        print(f"Classification: {classification} (score: {score})")
        if out_path:
            print(f"Promoted to: {out_path}")
        else:
            print("Not promoted (internal only)")
    else:
        print("Usage:", file=sys.stderr)
        print("  promote-runbook.py <runbook.md|TASK-ID>", file=sys.stderr)
        print("  promote-runbook.py --scan [--dry-run]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
