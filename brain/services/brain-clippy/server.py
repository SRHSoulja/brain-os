#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
BRAIN = Path(os.environ.get("BRAIN_DIR", Path.home() / "brain"))
SYSTEM_STATE = BRAIN / "brain/ops/system-state.md"
ACTIVE_CONTEXT = BRAIN / "brain/index/active-context.md"
WINS_LOG = BRAIN / "work/logs/wins-log.md"
EVENTS_LOG = BRAIN / "brain/ops/events.log"
DEVLOG_DIR = BRAIN / "work/logs/devlog"
VERDICT_FILE = BRAIN / "brain/ops/derived/state-verdict.json"
COMPANION_NAME = "Clippy"

# Previous snapshot cache for change detection
_prev_snapshot: dict | None = None


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def extract_single_line(md: str, heading: str) -> str:
    pattern = rf"^## {re.escape(heading)}\n\n(.+)$"
    match = re.search(pattern, md, re.MULTILINE)
    return match.group(1).strip() if match else ""


def extract_bullets(md: str, heading: str) -> list[str]:
    pattern = rf"^## {re.escape(heading)}\n\n((?:- .+\n)+)"
    match = re.search(pattern, md, re.MULTILINE)
    if not match:
        return []
    return [line[2:].strip() for line in match.group(1).strip().splitlines() if line.startswith("- ")]


def extract_section(md: str, heading: str, level: int = 3) -> str:
    marker = "#" * level
    lines = md.splitlines()
    target = f"{marker} {heading}"
    start = None
    for i, line in enumerate(lines):
        if line.strip() == target:
            start = i + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for i in range(start, len(lines)):
        line = lines[i]
        if re.match(r"^#{1,3} ", line):
            end = i
            break
    return "\n".join(lines[start:end]).strip()


def extract_table_rows(md: str, heading: str, level: int = 3) -> list[list[str]]:
    section = extract_section(md, heading, level=level)
    if not section:
        return []
    rows: list[list[str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if set(stripped.replace("|", "").replace("-", "").replace(" ", "")) == set():
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) >= 2 and cells[0] not in {"Service", "Date", "Location"}:
            rows.append(cells)
    return rows


def recent_wins(n: int = 3) -> list[str]:
    """Read last N wins from wins-log.md."""
    text = read_text(WINS_LOG)
    wins = []
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("- ") and len(line) > 10:
            # Strip date prefix like "2026-04-05: "
            entry = line[2:].strip()
            if entry[:10].replace("-", "").isdigit() and ": " in entry:
                entry = entry.split(": ", 1)[1]
            wins.append(entry)
            if len(wins) >= n:
                break
    return wins


def recent_devlog_titles(n: int = 3) -> list[str]:
    """Read last N devlog filenames and extract titles."""
    if not DEVLOG_DIR.is_dir():
        return []
    files = sorted(DEVLOG_DIR.glob("*.md"), reverse=True)[:n]
    titles = []
    for f in files:
        # Extract title from frontmatter or filename
        text = f.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("title:"):
                raw = line.split(":", 1)[1].strip().strip('"').strip("'")
                titles.append(raw)
                break
        else:
            # Fallback: clean up filename
            name = f.stem
            if name[:10].replace("-", "").isdigit():
                name = name[11:]  # strip date prefix
            titles.append(name.replace("-", " ").title())
    return titles


def recent_events(n: int = 5) -> list[str]:
    """Read last N lines from events.log."""
    text = read_text(EVENTS_LOG)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return lines[-n:] if lines else []


def verdict_age_minutes() -> float:
    """How old is the current verdict in minutes."""
    text = read_text(VERDICT_FILE)
    if not text:
        return 9999
    try:
        import json as _json
        v = _json.loads(text)
        ts = v.get("timestamp", "")
        if not ts:
            return 9999
        vt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - vt).total_seconds() / 60
    except Exception:
        return 9999


def newest_task_age_minutes() -> float:
    """Minutes since the most recently modified task file."""
    import os
    newest = 0
    for d in [BRAIN / "brain/ops/tasks/queue", BRAIN / "brain/ops/tasks/completed", BRAIN / "brain/ops/tasks/active"]:
        if not d.is_dir():
            continue
        for f in d.glob("*.md"):
            mt = os.path.getmtime(f)
            if mt > newest:
                newest = mt
    if newest == 0:
        return 9999
    return (datetime.now().timestamp() - newest) / 60


def read_queue_tasks() -> list[dict]:
    """Read queued task files and return basic metadata."""
    queue_dir = BRAIN / "brain/ops/tasks/queue"
    if not queue_dir.is_dir():
        return []
    tasks = []
    for f in sorted(queue_dir.glob("TASK-*.md")):
        text = f.read_text(encoding="utf-8")
        title = ""
        status = "queued"
        priority = "P3"
        for line in text.splitlines():
            if line.startswith("title:"):
                title = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("status:"):
                status = line.split(":", 1)[1].strip().strip('"')
            elif line.startswith("priority:"):
                priority = line.split(":", 1)[1].strip().strip('"')
        tasks.append({"id": f.stem, "title": title, "status": status, "priority": priority})
    return tasks


def read_verdict() -> dict:
    """Read the current Brain verdict."""
    text = read_text(VERDICT_FILE)
    if not text:
        return {"status": "UNKNOWN"}
    try:
        import json as _json
        return _json.loads(text)
    except Exception:
        return {"status": "UNKNOWN"}


def build_why_concerned(verdict: dict, services: list[list[str]], attention: list[str]) -> str:
    """Explain why Clippy is concerned/angry. Uses services, verdict issues.
    If nothing is wrong, says so plainly."""

    reasons = []

    # Check verdict issues
    status = verdict.get("status", "OK")
    issues = verdict.get("issues", [])
    if status == "CONFLICT":
        reasons.append(f"Verdict is CONFLICT: {verdict.get('summary', 'unknown reason')}")
    elif status == "DRIFT":
        reasons.append(f"Verdict is DRIFT: {verdict.get('summary', 'state inconsistency')}")
    for issue in issues:
        if issue.get("level") in ("CONFLICT", "DRIFT") and not any("Verdict" in r for r in reasons):
            reasons.append(f"{issue['code']}: {issue['message']}")

    # Check services that need attention (degraded/down)
    for row in services:
        if len(row) < 2:
            continue
        name, svc_status = row[0], row[1]
        if svc_status not in ("online", "inactive-on-demand", "inactive-until-stream"):
            reasons.append(f"{name} is {svc_status}")

    if not reasons:
        return "Nothing is wrong right now. Board is healthy."

    if len(reasons) == 1:
        return reasons[0] + "."

    # Multiple: lead with count, list top 2
    top = ". ".join(reasons[:2])
    extra = f" (+{len(reasons) - 2} more)" if len(reasons) > 2 else ""
    return f"{len(reasons)} issues. {top}.{extra}"


def build_look_first(verdict: dict, attention: list[str], queued: int, active: int,
                     recent: list[list[str]], services: list[list[str]],
                     wins: list[str], short_focus: str) -> str:
    """Produce one prioritized recommendation with freshness awareness.
    Priority: CONFLICT/DRIFT > stale-verdict-warning > attention > active > stale > eligible > calm."""

    status = verdict.get("status", "UNKNOWN")
    v_age = verdict_age_minutes()
    t_age = newest_task_age_minutes()

    # Freshness prefix: if verdict is old, soften the recommendation
    stale_prefix = ""
    if v_age > 120:
        hrs = int(v_age // 60)
        stale_prefix = f"State is {hrs}h old. "

    # P0: Verdict is broken
    if status == "CONFLICT":
        summary = verdict.get("summary", "state conflict detected")
        return f"Verdict is CONFLICT. Fix this first. {summary}"

    if status == "DRIFT":
        return f"Verdict is DRIFT. Run brain-verdict before any work."

    # P1: Service needs attention
    if attention:
        return f"{stale_prefix}{attention[0]} needs attention."

    # P2: Active task in flight
    if active:
        return f"{stale_prefix}Task in progress. Stay on it."

    # P3: Stale verdict
    if status == "STALE":
        return "State is stale. Run brain-resume first."

    # P4: Queued tasks
    queue_tasks = read_queue_tasks()
    eligible = [t for t in queue_tasks if t["status"] not in ("parked", "blocked")]
    parked = [t for t in queue_tasks if t["status"] in ("parked", "blocked")]

    if eligible:
        next_task = eligible[0]
        title = next_task["title"]
        if len(title) > 55:
            title = title[:52] + "..."
        parked_note = f" ({len(parked)} parked)" if parked else ""
        return f"{stale_prefix}Next eligible: {title}.{parked_note}"

    if parked and not eligible:
        # Add recency context: was work moving recently?
        if t_age < 15:
            return f"{stale_prefix}All {len(parked)} queued tasks are parked. Work moved {int(t_age)}m ago."
        return f"{stale_prefix}All {len(parked)} parked. No eligible work right now."

    # P5: Nothing queued — add recency to calm state
    if t_age < 30:
        if wins:
            return f"{stale_prefix}Board clear. Work moved {int(t_age)}m ago. Last win: {wins[0]}"
        return f"{stale_prefix}Board clear. Work moved {int(t_age)}m ago."
    if wins:
        return f"{stale_prefix}Nothing waiting. Last win: {wins[0]}"
    return f"{stale_prefix}Nothing waiting. Focus: {short_focus}."


def diff_snapshots(prev: dict | None, curr: dict) -> list[dict]:
    """Compare two snapshots, return classified change events."""
    if prev is None:
        return []

    events = []

    # Service status changes
    prev_svcs = {s["name"]: s["status"] for s in prev.get("services", [])}
    for svc in curr.get("services", []):
        old_status = prev_svcs.get(svc["name"])
        if old_status and old_status != svc["status"]:
            went_down = svc["status"] not in ("online", "inactive-on-demand", "inactive-until-stream")
            came_up = old_status not in ("online", "inactive-on-demand", "inactive-until-stream") and svc["status"] == "online"
            if went_down:
                events.append({"type": "service_down", "urgency": "high", "detail": f"{svc['name']} went {svc['status']}"})
            elif came_up:
                events.append({"type": "service_up", "urgency": "low", "detail": f"{svc['name']} is back online"})

    # Task queue changes
    prev_q = prev.get("task_queue", {})
    curr_q = curr.get("task_queue", {})
    pq = prev_q.get("`brain/ops/tasks/queue/`", 0)
    cq = curr_q.get("`brain/ops/tasks/queue/`", 0)
    pa = prev_q.get("`brain/ops/tasks/active/`", 0)
    ca = curr_q.get("`brain/ops/tasks/active/`", 0)
    pc = prev_q.get("`brain/ops/tasks/completed/`", 0)
    cc = curr_q.get("`brain/ops/tasks/completed/`", 0)

    if ca > pa:
        events.append({"type": "task_started", "urgency": "medium", "detail": "A task was claimed"})
    if cc > pc:
        events.append({"type": "task_completed", "urgency": "medium", "detail": f"Task completed ({cc} total)"})
    if cq > pq:
        events.append({"type": "task_queued", "urgency": "low", "detail": f"New task queued ({cq} in queue)"})

    # New recent changes (compare by "what" field)
    prev_recent = {r.get("what", "") for r in prev.get("recent_changes", [])}
    for r in curr.get("recent_changes", []):
        what = r.get("what", "")
        if what and what not in prev_recent:
            short = what
            if "TASK-" in short and ": " in short:
                short = short.split(": ", 1)[-1]
            events.append({"type": "new_change", "urgency": "low", "detail": short})
            break  # Only report the newest one

    # Attention shift
    prev_att = prev.get("stats", {}).get("attention_services", 0)
    curr_att = curr.get("stats", {}).get("attention_services", 0)
    if curr_att > prev_att:
        events.append({"type": "attention_up", "urgency": "high", "detail": "Something new needs attention"})
    elif curr_att < prev_att and curr_att == 0:
        events.append({"type": "attention_clear", "urgency": "low", "detail": "All clear. Nothing needs attention."})

    return events


def load_snapshot() -> dict:
    system_md = read_text(SYSTEM_STATE)
    active_md = read_text(ACTIVE_CONTEXT)

    focus = extract_bullets(system_md, "Current Focus")[:5]
    services = extract_table_rows(system_md, "Service Health", level=3)[:8]
    recent = extract_table_rows(system_md, "Recently Changed", level=2)[:5]
    task_rows = extract_table_rows(system_md, "Task Queue", level=2)[:3]
    mission = extract_single_line(system_md, "Mission")
    north_star = extract_single_line(active_md, "North Star")

    online = sum(1 for row in services if len(row) > 1 and row[1] == "online")
    degraded = sum(1 for row in services if len(row) > 1 and row[1] not in {"online", "inactive-on-demand", "inactive-until-stream"})
    active_attention = [row[0] for row in services if len(row) > 1 and row[1] not in {"online", "inactive-on-demand", "inactive-until-stream"}]
    task_queue = {
        row[0]: int(re.search(r"\d+", row[1]).group(0)) if len(row) > 1 and re.search(r"\d+", row[1]) else 0
        for row in task_rows
    }

    verdict = read_verdict()
    messages = build_messages(focus, services, recent, task_queue, verdict)
    what_matters = build_what_matters(focus, active_attention, recent, task_queue)
    signature = build_signature(focus, services, recent, task_queue)

    result = {
        "mission": mission or north_star,
        "focus": focus,
        "services": [{"name": row[0], "status": row[1], "notes": row[2] if len(row) > 2 else ""} for row in services],
        "recent_changes": [{"date": row[0], "what": row[1]} for row in recent if len(row) > 1],
        "task_queue": task_queue,
        "stats": {
            "online_services": online,
            "attention_services": degraded,
            "focus_count": len(focus),
            "recent_changes_count": len(recent),
        },
        "messages": messages,
        "what_matters": what_matters,
        "signature": signature,
        "verdict": {"status": verdict.get("status", "UNKNOWN"), "summary": verdict.get("summary", "")},
        "source_note": "Documented Brain state from system-state.md and active-context.md",
    }

    global _prev_snapshot
    result["events"] = diff_snapshots(_prev_snapshot, result)
    _prev_snapshot = {
        "services": result["services"],
        "task_queue": result["task_queue"],
        "recent_changes": result["recent_changes"],
        "stats": result["stats"],
    }

    return result


def build_messages(focus: list[str], services: list[list[str]], recent: list[list[str]], task_queue: dict[str, int], verdict: dict = None) -> dict:
    # Extract short focus label (before first em-dash or colon detail)
    raw_focus = focus[0] if focus else "nothing pinned"
    short_focus = raw_focus.split("\u2014")[0].split(" - ")[0].strip()
    if ":" in short_focus and len(short_focus) > 60:
        short_focus = short_focus.split(":")[0].strip()
    if len(short_focus) > 50:
        short_focus = short_focus[:47] + "..."
    first_change = recent[0][1] if recent and len(recent[0]) > 1 else "nothing new"
    # Strip TASK-YYYY-MM-DD-NNN prefix from change text
    short_change = first_change
    if "TASK-" in short_change and ": " in short_change:
        short_change = short_change.split(": ", 1)[-1]

    online = [row[0] for row in services if len(row) > 1 and row[1] == "online"]
    sleepy = [row[0] for row in services if len(row) > 1 and row[1].startswith("inactive")]
    attention = [row[0] for row in services if len(row) > 1 and row[1] not in {"online", "inactive-on-demand", "inactive-until-stream"}]
    queued = task_queue.get("`brain/ops/tasks/queue/`", 0)
    active = task_queue.get("`brain/ops/tasks/active/`", 0)

    # Short, sharp greeting based on what actually matters
    if attention:
        greeting = f"{attention[0]} needs attention. {len(online)} services online."
    elif active:
        greeting = f"Active task in flight. {len(online)} services online. Focus: {short_focus}."
    elif queued:
        greeting = f"{queued} task(s) queued. {len(online)} services online. Focus: {short_focus}."
    else:
        greeting = f"Board is calm. {len(online)} services online. Focus: {short_focus}."

    brief = f"{len(online)} online. Latest: {short_change}."

    # State-aware pep instead of generic motivation
    if attention:
        pep = f"Something needs you. {attention[0]} is not healthy."
    elif queued and not active:
        pep = f"{queued} task(s) waiting. Pick one or let them wait."
    elif active:
        pep = "Task in progress. Stay on it."
    else:
        pep = "Nothing urgent. Good time to think, not just do."

    weird = (
        f"Sleepy friends: {', '.join(sleepy[:3])}."
        if sleepy else "Everyone is awake. Suspicious."
    )

    # Fetch wins and devlogs for contextual messages
    wins = recent_wins(3)
    devlogs = recent_devlog_titles(2)

    # "What matters" with operational context
    wm_parts = []
    if attention:
        wm_parts.append(f"{attention[0]} needs attention.")
    if active:
        wm_parts.append(f"{active} active task.")
    if queued:
        wm_parts.append(f"{queued} queued.")
    wm_parts.append(f"Focus: {short_focus}.")
    if wins:
        wm_parts.append(f"Last win: {wins[0]}.")
    what_matters = " ".join(wm_parts)

    changes_parts = []
    if short_change:
        changes_parts.append(f"Latest task: {short_change}.")
    if wins:
        changes_parts.append(f"Recent wins: {'; '.join(wins[:2])}.")
    if devlogs:
        changes_parts.append(f"Last sessions: {'; '.join(devlogs[:2])}.")
    changes_parts.append(f"{len(recent)} changes in the notebook.")

    changes = " ".join(changes_parts)

    # Idle thoughts derived from current state (used by frontend)
    idle = []
    if queued and not active:
        idle.append(f"{queued} tasks queued. None claimed yet.")
    if not attention and not active:
        idle.append("Board is clear. No fires.")
    if len(recent) == 0:
        idle.append("Nothing changed recently. Quiet shift.")
    elif len(recent) >= 5:
        idle.append(f"{len(recent)} changes in the notebook. Busy stretch.")
    if sleepy:
        idle.append(f"{len(sleepy)} services sleeping. That is normal.")
    if not idle:
        idle.append("Systems steady. Clippy is watching.")

    return {
        "greeting": greeting,
        "brief": brief,
        "pep": pep,
        "weird": weird,
        "what_matters": what_matters,
        "changes": changes,
        "full": " ".join([greeting, brief, pep]),
        "why_concerned": build_why_concerned(verdict or {}, services, attention),
        "look_first": build_look_first(
            verdict or {}, attention, queued, active, recent, services, wins, short_focus
        ),
        "idle": idle,
    }


def build_what_matters(
    focus: list[str],
    attention: list[str],
    recent: list[list[str]],
    task_queue: dict[str, int],
) -> list[str]:
    items: list[str] = []
    if attention:
        items.append(f"Attention surface: {attention[0]}")
    if task_queue.get("`brain/ops/tasks/active/`", 0):
        items.append(f"Active tasks: {task_queue['`brain/ops/tasks/active/`']}")
    if task_queue.get("`brain/ops/tasks/queue/`", 0):
        items.append(f"Queued tasks: {task_queue['`brain/ops/tasks/queue/`']}")
    if focus:
        items.append(f"Top focus: {focus[0]}")
    if recent and len(recent[0]) > 1:
        items.append(f"Latest change: {recent[0][1]}")
    return items[:4]


def build_signature(
    focus: list[str],
    services: list[list[str]],
    recent: list[list[str]],
    task_queue: dict[str, int],
) -> str:
    payload = json.dumps(
        {
            "focus": focus[:3],
            "services": [[row[0], row[1]] for row in services[:5]],
            "recent": recent[:3],
            "task_queue": task_queue,
        },
        sort_keys=True,
    )
    return str(abs(hash(payload)))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/snapshot":
            payload = load_snapshot()
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8787), Handler)
    print(f"{COMPANION_NAME} sandbox running at http://127.0.0.1:8787")
    server.serve_forever()


if __name__ == "__main__":
    main()
