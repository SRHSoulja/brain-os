#!/usr/bin/env python3
"""post-task-audit.py -- Structural integrity checklist after task completion.

Reads the completion JSON (for artifacts_touched) and optionally a git diff,
then prints a checklist of post-task actions the agent must address.

Usage: python3 post-task-audit.py <completion.json> [--tools-dir <path>]

Output: Structured checklist to stdout. Empty if nothing to flag.
"""
import json, os, re, subprocess, sys
from datetime import datetime, timezone

def main():
    if len(sys.argv) < 2:
        return

    preflight = False
    if sys.argv[1] == "--preflight":
        preflight = True
        comp_path = None
    else:
        comp_path = sys.argv[1]
    tools_dir = os.path.os.path.join(os.environ.get("BRAIN_DIR", os.path.expanduser("~/brain")), "scripts")
    brain_dir = os.path.os.environ.get("BRAIN_DIR", os.path.expanduser("~/brain"))

    for i, arg in enumerate(sys.argv[2:], 2):
        if arg == "--tools-dir" and i + 1 < len(sys.argv):
            tools_dir = sys.argv[i + 1]

    artifacts = []
    task_id = ""
    comp = {}
    if not preflight:
        try:
            with open(comp_path) as f:
                comp = json.load(f)
        except Exception:
            return
        artifacts = list(comp.get("artifacts_touched", []))
        task_id = comp.get("task_id", "")

    # ── Determine task launch time (for stale-artifact filtering) ─
    launched_at = None
    if not preflight:
        active_dir = os.path.join(brain_dir, "brain/ops/tasks/active")
        completed_dir = os.path.join(brain_dir, "brain/ops/tasks/completed")
        for run_dir in [active_dir, completed_dir]:
            run_path = os.path.join(run_dir, f"{task_id}.run.json")
            if os.path.isfile(run_path):
                try:
                    with open(run_path) as f:
                        run = json.load(f)
                    launched_str = run.get("launched_at", "")
                    if launched_str:
                        launched_at = datetime.fromisoformat(launched_str.replace("Z", "+00:00"))
                except Exception:
                    pass
                break

    # ── Detect changes across both canonical and bridge repos ─────
    for repo_root in [brain_dir, tools_dir]:
        cmd = ["git", "-C", repo_root, "status", "--porcelain"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line_in in result.stdout.strip().split("\n"):
                    if not line_in or len(line_in) < 3: continue
                    fpath = line_in[3:].strip("\"")
                    if " -> " in fpath: fpath = fpath.split(" -> ")[-1]
                    full = os.path.join(repo_root, fpath)
                    if not any(x in full for x in ["/scripts/bin/", "/scripts/lib/", "/tools/bin/", "/tools/lib/"]):
                        continue
                    if launched_at:
                        try:
                            mtime = datetime.fromtimestamp(os.path.getmtime(full), tz=timezone.utc)
                            if mtime < launched_at: continue
                        except OSError: pass
                    if full not in artifacts: artifacts.append(full)
        except Exception: pass
    if not artifacts:
        return

    checks = []

    # ── 1. Shared lib changes ──────────────────────────────────────
    lib_changes = [a for a in artifacts if "tools/lib/" in a or "/lib/" in a or a.startswith("lib/")]
    if lib_changes:
        downstream = []
        for lib_file in lib_changes:
            lib_name = os.path.basename(lib_file)
            try:
                result = subprocess.run(
                    ["grep", "-rl", lib_name, os.path.join(tools_dir, "bin")],
                    capture_output=True, text=True, timeout=5
                )
                if result.stdout.strip():
                    tools_using = [os.path.basename(p) for p in result.stdout.strip().split("\n")]
                    downstream.append((lib_name, tools_using))
            except Exception:
                pass

        if downstream:
            lines = ["SHARED LIB CHANGED -- downstream tools may be affected:"]
            for lib_name, tools_list in downstream:
                lines.append(f"  {lib_name} sourced by: {', '.join(tools_list[:8])}")
                if len(tools_list) > 8:
                    lines.append(f"    ... and {len(tools_list) - 8} more")
            lines.append("  [ ] Verify no downstream breakage from changed signatures/behavior")
            checks.append("\n".join(lines))

    # ── 2. New tools in bin/ ───────────────────────────────────────
    new_tools = [a for a in artifacts if any(x in a for x in ["/tools/bin/", "/scripts/bin/"]) or a.startswith("bin/")]
    if new_tools:
        map_path = os.path.join(brain_dir, "brain/wiki/tools/MAP.md")
        map_content = ""
        if os.path.exists(map_path):
            with open(map_path) as f:
                map_content = f.read()

        missing_map = []
        missing_wiki = []
        for tool_path in new_tools:
            tool_name = os.path.basename(tool_path)
            if tool_name not in map_content:
                missing_map.append(tool_name)
            wiki_candidates = [f"{tool_name}.md"]
            if tool_name.endswith(".sh"):
                wiki_candidates.append(f"{tool_name[:-3]}.md")
            has_wiki = any(
                os.path.exists(os.path.join(brain_dir, "brain/wiki/tools", candidate))
                for candidate in wiki_candidates
            )
            if not has_wiki:
                missing_wiki.append(tool_name)

        if missing_map or missing_wiki:
            lines = ["NEW TOOL(S) -- may need registration:"]
            for tool_name in sorted(set(missing_map + missing_wiki)):
                missing_parts = []
                if tool_name in missing_map:
                    missing_parts.append("MAP entry")
                if tool_name in missing_wiki:
                    missing_parts.append("wiki tool page")
                lines.append(f"  [ ] {tool_name} -- needs " + " + ".join(missing_parts))
            if missing_map:
                lines.append("  Run: brain-agent-registry-generate")
            checks.append(
                "\n".join(lines)
            )

    # ── 3. New files that may need gitignore/lsyncd coverage ───────
    ops_files = [a for a in artifacts if "/brain/ops/" in a and not a.endswith(".md")]
    proof_files = [a for a in artifacts if "proof-execution" in a]
    dot_files = [a for a in artifacts if "/." in a and not a.endswith(".gitignore")]

    gitignore_path = os.path.join(brain_dir, ".gitignore")
    gitignore_content = ""
    if os.path.exists(gitignore_path):
        with open(gitignore_path) as f:
            gitignore_content = f.read()

    uncovered = []
    for f in ops_files + proof_files + dot_files:
        basename = os.path.basename(f)
        if basename not in gitignore_content and not any(
            pat in gitignore_content for pat in [basename, os.path.dirname(f).split("/")[-1] + "/"]
        ):
            uncovered.append(f)

    if uncovered:
        checks.append(
            "NEW FILES -- check gitignore/lsyncd coverage:\n"
            + "\n".join(f"  [ ] {f}" for f in uncovered[:5])
        )

    # ── 4. Function removals ───────────────────────────────────────
    # Detect removed functions from git diff. Before flagging orphan callers,
    # verify the function isn't reachable via a sourced lib file (moved, not removed).
    try:
        result = subprocess.run(
            ["git", "-C", tools_dir, "diff", "HEAD~1", "--unified=0", "--diff-filter=M"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            removed_funcs = []
            for line in result.stdout.split("\n"):
                if line.startswith("-") and not line.startswith("---"):
                    m = re.match(r'^-\s*(?:function\s+)?(\w+)\s*\(\)', line)
                    if m:
                        removed_funcs.append(m.group(1))
                    m = re.match(r'^-\s*def\s+(\w+)\s*\(', line)
                    if m:
                        removed_funcs.append(m.group(1))

            if removed_funcs:
                removed_funcs = list(set(removed_funcs))
                orphan_callers = []
                for func in removed_funcs:
                    try:
                        grep_result = subprocess.run(
                            ["grep", "-rlw", func, os.path.join(tools_dir, "bin")],
                            capture_output=True, text=True, timeout=5
                        )
                        if not grep_result.stdout.strip():
                            continue
                        callers = [os.path.basename(p) for p in grep_result.stdout.strip().split("\n")]

                        # Check if function is reachable via sourced lib files
                        # (moved to shared lib rather than deleted)
                        lib_result = subprocess.run(
                            ["grep", "-rlw", func, os.path.join(tools_dir, "lib")],
                            capture_output=True, text=True, timeout=5
                        )
                        if lib_result.stdout.strip():
                            # Function exists in a lib — likely moved, not orphaned
                            continue

                        orphan_callers.append((func, callers))
                    except Exception:
                        pass

                if orphan_callers:
                    lines = ["REMOVED FUNCTIONS -- callers still reference them:"]
                    for func, callers in orphan_callers:
                        lines.append(f"  [ ] {func}() still called by: {', '.join(callers[:5])}")
                    checks.append("\n".join(lines))
    except Exception:
        pass

    # ── 5. Gate/block additions (diff-based, not file-content scan) ─
    # Only flag if NEW lines in this task's diff contain gate keywords.
    # Avoids flagging every existing file that contains 'exit 1'.
    try:
        result = subprocess.run(
            ["git", "-C", tools_dir, "diff", "HEAD", "--unified=0"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout:
            gate_indicators = ["BLOCK", "refuse", "exit 1", "hard block", r"\bgate\b"]
            current_file = None
            gate_files_new = []
            for line in result.stdout.split("\n"):
                if line.startswith("+++ b/"):
                    current_file = os.path.basename(line[6:].strip())
                elif line.startswith("+") and not line.startswith("+++") and current_file:
                    if any(re.search(ind, line, re.IGNORECASE) for ind in gate_indicators):
                        if current_file not in gate_files_new:
                            gate_files_new.append(current_file)

            # Only flag tool files that were part of THIS task's changes (mtime-filtered artifacts)
            tool_artifacts = [a for a in artifacts if "tools/" in a or a.startswith("bin/") or a.startswith("lib/")]
            task_tool_basenames = {os.path.basename(a) for a in tool_artifacts}
            gate_files_new = [f for f in gate_files_new if f in task_tool_basenames]
            if gate_files_new and tool_artifacts:
                checks.append(
                    "GATE/BLOCK CHANGES -- verify all agent seats can pass:\n"
                    + "\n".join(f"  [ ] {f} -- NEW gate logic added, test with Claude/Codex/Gemini identities"
                                for f in sorted(set(gate_files_new))[:5])
                )
    except Exception:
        pass

    # ── 6. Smoke check modified shell scripts ──────────────────────
    # Run bash -n on modified .sh / extensionless bin/ scripts to catch syntax errors.
    tool_artifacts = [a for a in artifacts if "tools/" in a or a.startswith("bin/") or a.startswith("lib/")]
    syntax_fails = []
    for a in tool_artifacts:
        full = a if os.path.isabs(a) else os.path.join(tools_dir, a)
        if not os.path.isfile(full):
            continue
        # Only shell scripts
        is_shell = full.endswith(".sh") or (
            not "." in os.path.basename(full) and
            open(full, "rb").read(20).startswith(b"#!/")  # shebang
        )
        if not is_shell:
            continue
        try:
            result = subprocess.run(
                ["bash", "-n", full],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                syntax_fails.append((os.path.basename(full), result.stderr.strip()[:120]))
        except Exception:
            pass

    if syntax_fails:
        lines = ["SYNTAX ERRORS -- modified scripts failed bash -n:"]
        for name, err in syntax_fails:
            lines.append(f"  [ ] {name}: {err}")
        checks.append("\n".join(lines))

    # ── 7. Behavioral contract change detection ────────────────────
    # If lifecycle tools were modified, remind to check MANUAL.md etc.
    lifecycle_tools = [
        "brain-task-complete", "brain-task-execute", "brain-task-claim",
        "brain-meditate", "brain-resume", "brain-agent-bootstrap",
        "brain-session", "brain-handoff", "brain-task-handoff",
    ]
    modified_lifecycle = [
        os.path.basename(a) for a in artifacts
        if any(lt in a for lt in lifecycle_tools)
    ]
    if modified_lifecycle:
        checks.append(
            "BEHAVIORAL CONTRACT CHANGE -- lifecycle tools modified:\n"
            + "\n".join(f"  Modified: {t}" for t in sorted(set(modified_lifecycle)))
            + "\n  [ ] Check MANUAL.md, CLAUDE.md, AGENTS.md, GEMINI.md for needed updates"
            + "\n  [ ] Did this change how the brain works? Update docs if so."
        )

    # ── 8. Execution note gap scan ─────────────────────────────────
    # Check execution_note for deferred-work signals that should be tasks.
    exec_note = comp.get("execution_note", "") or ""
    if not exec_note:
        # Also check implementation_notes
        exec_note = comp.get("notes", "") or comp.get("implementation_notes", "") or ""
    gap_signals = ["still needs", "known gap", "TODO", "follow-up", "didn't", "not yet",
                   "future work", "left out", "skipped", "deferred", "next time"]
    found_gaps = [sig for sig in gap_signals if sig.lower() in exec_note.lower()]
    if found_gaps:
        preview = exec_note[:200].replace("\n", " ")
        checks.append(
            f"DEFERRED WORK SIGNALS in execution note ({', '.join(found_gaps[:3])}):\n"
            f"  \"{preview}...\"\n"
            f"  [ ] Admit follow-up tasks for any deferred items: brain-task-quick \"P3: ...\""
        )

    # ── 9. Execution plan status verification ─────────────────────
    # Check that the completed task is marked DONE in the plan (not still "queued").
    plan_path = os.path.join(brain_dir, "brain/ops/queue-execution-plan.md")
    if task_id and os.path.isfile(plan_path):
        with open(plan_path) as f:
            plan_content = f.read()
        short_match = re.match(r"TASK-\d{4}-\d{2}-\d{2}-(\d+)", task_id)
        short_id = f"TASK-{short_match.group(1)}" if short_match else task_id
        # Find the row for this task
        for line in plan_content.split("\n"):
            if (task_id in line or short_id in line) and "|" in line:
                cols = [c.strip() for c in line.split("|")]
                # Status is last non-empty column
                status_col = cols[-2] if len(cols) > 2 else ""
                if "queued" in status_col.lower():
                    checks.append(
                        f"EXECUTION PLAN NOT UPDATED -- {task_id} still shows 'queued':\n"
                        f"  [ ] Mark task DONE in brain/ops/queue-execution-plan.md"
                    )
                break

    # ── 10. Documentation reminders ────────────────────────────────
    # Preflight mode is used as a hard completion gate. It must only emit
    # actionable blockers, not generic reminders, or completion deadlocks.
    if not preflight:
        tool_artifacts_any = [a for a in artifacts if "tools/" in a or a.startswith("bin/") or a.startswith("lib/")]
        doc_checks = []
        if tool_artifacts_any:
            doc_checks.append("[ ] Wiki page: does this work have a wiki page? Create/update if not")
        doc_checks.append("[ ] Execution plan: mark task done, note any ordering/scope changes")
        doc_checks.append("[ ] Learning capture: save discoveries as memory + wiki mirror page (both required)")
        doc_checks.append("[ ] Wiki completeness: every memory, tool, runbook, and documentation artifact must have a wiki entry")
        if comp.get("escalation") != "STOP":
            doc_checks.append("[ ] New task spawns: admit follow-ups via brain-task-quick")

        checks.append("DOCUMENTATION:\n" + "\n".join(f"  {c}" for c in doc_checks))

    # ── Output ─────────────────────────────────────────────────────
    # Preflight is a fail-closed documentation gate from brain-task-complete.
    # Keep it scoped to tool-registration blockers only.
    if preflight:
        checks = [c for c in checks if c.startswith("NEW TOOL(S)")]

    if checks:
        print("")
        print("=== Post-Task Audit Checklist ===")
        print("")
        for i, check in enumerate(checks, 1):
            print(f"{i}. {check}")
            print("")
        print("Address each item before moving to the next task.")

if __name__ == "__main__":
    main()
