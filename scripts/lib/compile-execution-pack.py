#!/usr/bin/env python3
"""compile-execution-pack.py — Compile a task markdown file into a structured Execution Pack.

Deterministic, file-driven, no LLM dependency. Supports both explicit fields
and legacy derivation from existing task structure.

Usage:
    python3 compile-execution-pack.py <task_file_path>

Output: JSON to stdout.
Exit 0 on success, 1 on failure.
"""

import json
import os
import re
import sys

# Import infer-impact if available (same directory)
TOOLS_LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS_LIB)
try:
    from importlib import import_module
    _infer_mod = None
    _infer_path = os.path.join(TOOLS_LIB, "infer-impact.py")
    if os.path.exists(_infer_path):
        import importlib.util
        spec = importlib.util.spec_from_file_location("infer_impact", _infer_path)
        _infer_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_infer_mod)
except Exception:
    _infer_mod = None

try:
    _recall_mod = None
    _recall_path = os.path.join(TOOLS_LIB, "recall-similar.py")
    if os.path.exists(_recall_path):
        import importlib.util as _ilu2
        _rspec = _ilu2.spec_from_file_location("recall_similar", _recall_path)
        _recall_mod = _ilu2.module_from_spec(_rspec)
        _rspec.loader.exec_module(_recall_mod)
except Exception:
    _recall_mod = None


def extract_frontmatter(content):
    """Parse YAML-like frontmatter between --- markers."""
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    fm_lines = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        fm_lines.append(line)
    else:
        return {}
    fields = {}
    for line in fm_lines:
        m = re.match(r'^(\w+):\s*"?([^"]*)"?\s*$', line)
        if m:
            fields[m.group(1)] = m.group(2)
    return fields


def extract_section(content, heading):
    """Extract content under a ## heading, up to the next ## or EOF."""
    pattern = rf"^## {re.escape(heading)}\s*\n([\s\S]*?)(?=^## |\Z)"
    m = re.search(pattern, content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def extract_title(content):
    """Extract the first # heading."""
    m = re.search(r"^# (.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def extract_bullets(text):
    """Extract bullet items (- [ ] or - [x] or plain -) and numbered items (1. 2. etc)."""
    items = []
    for line in text.split("\n"):
        m = re.match(r"^\s*-\s*(?:\[.\]\s*)?(.+)", line)
        if m:
            items.append(m.group(1).strip())
            continue
        m = re.match(r"^\s*\d+\.\s+(.+)", line)
        if m:
            items.append(m.group(1).strip())
    return items


def extract_constraints(description):
    """Derive constraints from description — lines with must/should/do not/no/only."""
    constraints = []
    for line in description.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if any(kw in lower for kw in ["must ", "should ", "do not ", "don't ", "only ", "never "]):
            # Clean bullet prefix
            cleaned = re.sub(r"^[-*]\s*", "", stripped)
            constraints.append(cleaned)
    return constraints


def extract_artifacts(description, inputs_raw):
    """Derive expected artifacts from file paths in Inputs section primarily."""
    artifacts = []
    # Inputs section is the strongest signal for relevant file paths
    text = inputs_raw if inputs_raw else description
    for m in re.finditer(r"`([^`]{3,80})`", text):
        val = m.group(1).strip()
        # Must look like a file path — has extension or clear directory structure
        if not val:
            continue
        # Skip commands, URLs, inline code
        if val.startswith(("ssh ", "http", "git ", "npm ", "pip ")):
            continue
        if val.startswith("-"):  # CLI flags
            continue
        # Must have a slash (path) and ideally an extension
        if "/" in val and (re.search(r"\.\w{1,5}$", val) or val.endswith("/")):
            artifacts.append(val)
    return list(dict.fromkeys(artifacts))[:3]


def parse_execution_contract(text):
    """Parse execution contract from markdown bold-field format into structured dict."""
    contract = {
        "authority_owner": "",
        "allowed_write_surfaces": [],
        "may_spawn_tasks": False,
        "required_review_inputs": [],
        "stop_and_ask_conditions": [],
        "rollback_reference": "",
    }
    if not text:
        return contract

    for line in text.split("\n"):
        line = line.strip()
        if not line.startswith("- **"):
            continue
        m = re.match(r"^- \*\*(\w+):\*\*\s*(.*)", line)
        if not m:
            continue
        key = m.group(1).strip()
        val = m.group(2).strip()

        if key == "authority_owner":
            contract["authority_owner"] = val
        elif key == "allowed_write_surfaces":
            # Comma-separated paths, strip surrounding brackets
            cleaned = val.strip("[] ")
            contract["allowed_write_surfaces"] = [
                s.strip() for s in cleaned.split(",") if s.strip()
            ]
        elif key == "may_spawn_tasks":
            contract["may_spawn_tasks"] = val.lower() in ("true", "yes")
        elif key == "required_review_inputs":
            if val.lower() in ("none", ""):
                contract["required_review_inputs"] = []
            else:
                contract["required_review_inputs"] = [
                    s.strip() for s in val.split(",") if s.strip()
                ]
        elif key == "stop_and_ask_conditions":
            if val:
                contract["stop_and_ask_conditions"] = [val]
        elif key == "rollback_reference":
            contract["rollback_reference"] = val

    return contract


def first_sentence(text):
    """Return the first meaningful sentence from a block of text."""
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.startswith("#"):
            continue
        # Take up to first period that's not inside backticks
        # Simple approach: find period followed by space or EOL
        m = re.search(r"^(.{15,}?[.!])\s", stripped)
        if m:
            return m.group(1)
        if len(stripped) > 20:
            return stripped[:200]
    return text.split("\n")[0].strip()[:200] if text else ""


def compile_pack(filepath):
    """Compile a task file into an Execution Pack dict."""
    with open(filepath, "r") as f:
        content = f.read()

    fm = extract_frontmatter(content)
    title = extract_title(content)
    description = extract_section(content, "Description") or extract_section(content, "Objective")
    inputs_raw = extract_section(content, "Inputs") or extract_section(content, "Ready Assets")
    success_raw = extract_section(content, "Success Criteria")
    context_raw = extract_section(content, "Context")
    steps_raw = extract_section(content, "Steps")

    # Explicit or derived fields
    task_id = fm.get("task_id", os.path.basename(filepath).replace(".md", ""))
    node = fm.get("node", "")
    priority = fm.get("priority", "")
    owner = fm.get("owner", "")
    architecture_scope = fm.get("architecture_scope", "")
    scope_tags = fm.get("scope_tags", "")

    # Summary: explicit field → first sentence of description
    summary_section = extract_section(content, "Summary")
    summary = summary_section if summary_section else first_sentence(description)

    # Goal: explicit field → title
    goal_section = extract_section(content, "Goal")
    goal = goal_section if goal_section else title

    # Constraints: explicit field → derived from description
    constraints_section = extract_section(content, "Constraints")
    if constraints_section:
        constraints = constraints_section
    else:
        derived = extract_constraints(description)
        constraints = "\n".join(derived) if derived else ""

    # Completion criteria: explicit field → success criteria bullets
    criteria_section = extract_section(content, "Completion Criteria")
    if criteria_section:
        completion_criteria = extract_bullets(criteria_section)
    elif success_raw:
        completion_criteria = extract_bullets(success_raw)
    else:
        completion_criteria = []

    # Expected artifact: explicit field → derived from file paths in task
    artifact_section = extract_section(content, "Expected Artifact")
    if artifact_section:
        expected_artifact = artifact_section.strip()
    else:
        artifacts = extract_artifacts(description, inputs_raw)
        expected_artifact = ", ".join(artifacts) if artifacts else ""

    # Impact: explicit from completed task → empty for queued/active
    impact = ""
    impact_match = re.search(
        r"### Impact\s*\n.*?\*\*Metric:\*\*\s*(.+)", content
    )
    if impact_match:
        metric = impact_match.group(1).strip()
        before_m = re.search(r"\*\*Before:\*\*\s*(.+)", content)
        after_m = re.search(r"\*\*After:\*\*\s*(.+)", content)
        before = before_m.group(1).strip() if before_m else "unknown"
        after = after_m.group(1).strip() if after_m else ""
        impact = f"{metric}:{before}:{after}" if after else metric

    # Impact suggestion via infer-impact
    impact_suggestion = ""
    if _infer_mod and not impact:
        result = _infer_mod.infer(title, description)
        if result:
            metric, prev, nxt = result
            impact_suggestion = f"{metric}:{prev}:{nxt}"

    # Execution contract: parse from ## Execution Contract section
    contract_raw = extract_section(content, "Execution Contract")
    execution_contract = parse_execution_contract(contract_raw)

    # Prior task recall: find similar completed tasks
    prior_tasks = []
    if _recall_mod and fm.get("status", "") != "completed":
        try:
            prior_tasks = _recall_mod.find_similar(title, node, limit=3)
        except Exception:
            pass

    # Completion command (stable placeholder tokens) — must be built before execution_instructions
    completion_command = f"brain-task-complete {task_id} --by {owner or 'claude-code'} --output \"<completion_summary>\" --notes \"<implementation_notes>\""
    if impact_suggestion and not impact:
        completion_command += f' --impact "{impact_suggestion}"'
    elif impact:
        completion_command += f' --impact "{impact}"'

    # Steps: extract numbered or bulleted steps
    steps = extract_bullets(steps_raw) if steps_raw else []

    # Execution instructions (deterministic, not LLM-generated)
    lines = []
    lines.append(f"Task: {task_id}")
    if architecture_scope:
        scope_line = f"Architecture scope: {architecture_scope}"
        if scope_tags:
            scope_line += f" [{scope_tags}]"
        lines.append(scope_line)
    if goal:
        lines.append(f"Goal: {goal}")
    if summary and summary != goal:
        lines.append(f"Context: {summary}")
    if constraints:
        lines.append(f"Constraints: {constraints}")
    if steps:
        lines.append("Steps:")
        for i, s in enumerate(steps, 1):
            lines.append(f"  {i}. {s}")
    if completion_criteria:
        lines.append("Completion criteria:")
        for i, c in enumerate(completion_criteria, 1):
            lines.append(f"  {i}. {c}")
    if expected_artifact:
        lines.append(f"Expected artifact: {expected_artifact}")
    if inputs_raw:
        lines.append(f"Inputs: {inputs_raw[:300]}")
    if prior_tasks:
        lines.append("Prior similar tasks:")
        for pt in prior_tasks:
            _pt_id = pt.get("task_id", "?")
            _pt_sum = pt.get("summary", "")[:120]
            _pt_dur = pt.get("duration_minutes")
            _dur_str = f" ({_pt_dur}min)" if _pt_dur else ""
            lines.append(f"  - {_pt_id}{_dur_str}: {_pt_sum}")
            if pt.get("notes"):
                lines.append(f"    Lesson: {pt['notes'][:100]}")
    lines.append("Rules: Follow Brain safety rules (VERDICT_GATE, atomic writes, locking). Do not modify files outside task scope without asking.")
    lines.append(f"When done: {completion_command}")
    execution_instructions = "\n".join(lines)

    return {
        "task_id": task_id,
        "node": node,
        "priority": priority,
        "owner": owner,
        "status": fm.get("status", ""),
        "admitted_at": fm.get("admitted_at", ""),
        "depends_on": fm.get("depends_on", ""),
        "execution_profile": fm.get("execution_profile", ""),
        "architecture_scope": architecture_scope,
        "scope_tags": scope_tags,
        "summary": summary,
        "goal": goal,
        "steps": steps,
        "constraints": constraints,
        "completion_criteria": completion_criteria,
        "expected_artifact": expected_artifact,
        "impact": impact,
        "impact_suggestion": impact_suggestion,
        "execution_instructions": execution_instructions,
        "completion_command": completion_command,
        "execution_contract": execution_contract,
        "prior_tasks": prior_tasks,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: compile-execution-pack.py <task_file>", file=sys.stderr)
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.isfile(filepath):
        print(f"Error: file not found: {filepath}", file=sys.stderr)
        sys.exit(1)

    try:
        pack = compile_pack(filepath)
        json.dump(pack, sys.stdout, indent=2)
        sys.stdout.write("\n")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
