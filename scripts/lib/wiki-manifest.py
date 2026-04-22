#!/usr/bin/env python3
"""wiki-manifest.py — Generate machine-readable manifests for wiki folders.

Produces manifest.json alongside MAP.md in brain/wiki/systems/ and brain/wiki/pages/.
Each manifest classifies every page in the folder with:
  - page_type: concept | reference | project-note | task-stub | healing | feedback | digest | tool-doc | session
  - topic_bucket: section name from MAP.md (null for pages not in MAP)
  - is_hand_authored: true/false (false for auto-generated task stubs and session digests)
  - title, tags, related: from frontmatter (if present)

Usage:
    python3 wiki-manifest.py <wiki_dir> [<folder>]
    python3 wiki-manifest.py ~/brain/brain/wiki systems
    python3 wiki-manifest.py ~/brain/brain/wiki pages
    python3 wiki-manifest.py ~/brain/brain/wiki       # generates both

Regenerate whenever MAP.md changes or new pages are added.
Called by: brain-wiki manifest (subcommand added to brain-wiki)
"""

import json
import os
import re
import sys
from datetime import datetime, timezone


# ── Page type derivation ─────────────────────────────────────────────────────

def derive_page_type(filename: str, category: str) -> str:
    """Derive page_type from filename pattern and folder category."""
    name = filename.replace(".md", "")

    if category == "systems":
        if re.match(r"task_\d{4}_\d{2}_\d{2}_\d+", name):
            return "task-stub"
        if name.startswith("healing-"):
            return "healing"
        if name.startswith("reference_"):
            return "reference"
        if name.startswith("project_"):
            return "project-note"
        return "concept"

    if category == "pages":
        if name.startswith("memory_digest_"):
            return "digest"
        if name.startswith("healing-"):
            return "healing"
        if name.startswith("feedback_"):
            return "feedback"
        # Named reference/convention docs
        return "reference"

    if category == "tools":
        return "tool-doc"

    if category == "sessions":
        return "session"

    return "wiki"


def is_hand_authored(filename: str, page_type: str) -> bool:
    """True for human/agent-written content; false for auto-generated stubs."""
    return page_type not in ("task-stub", "session")


# ── Frontmatter parser ───────────────────────────────────────────────────────

def parse_frontmatter(content: str) -> dict:
    """Extract title, tags, related from YAML-like frontmatter."""
    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not fm_match:
        return {}

    fm = fm_match.group(1)
    result = {}

    t = re.search(r'title:\s*"?([^"\n]+)', fm)
    if t:
        result["title"] = t.group(1).strip()

    # Tags: [a, b, c] inline form
    tag_match = re.search(r"tags:\s*\[([^\]]*)\]", fm)
    if tag_match:
        result["tags"] = [
            x.strip().strip('"').strip("'")
            for x in tag_match.group(1).split(",")
            if x.strip()
        ]
    else:
        result["tags"] = []

    # Related: [a, b, c] inline form
    rel_match = re.search(r"related:\s*\[([^\]]*)\]", fm)
    if rel_match:
        result["related"] = [
            x.strip().strip('"').strip("'")
            for x in rel_match.group(1).split(",")
            if x.strip()
        ]
    else:
        result["related"] = []

    return result


# ── MAP.md parser ─────────────────────────────────────────────────────────────

def parse_map_buckets(map_path: str) -> dict:
    """Parse MAP.md and return {filename: topic_bucket} mapping.

    Reads section headers (## Section Name) and table rows containing
    filename links ([filename.md](filename.md)).
    """
    if not os.path.isfile(map_path):
        return {}

    with open(map_path) as f:
        content = f.read()

    buckets = {}
    current_bucket = None

    for line in content.split("\n"):
        # Section header
        h2 = re.match(r"^## (.+)$", line)
        if h2:
            current_bucket = h2.group(1).strip()
            continue

        # Table row with a markdown link to a .md file
        # Matches: | [label](filename.md) | ... |
        link_match = re.search(r"\[([^\]]+)\]\(([^)]+\.md)\)", line)
        if link_match and current_bucket:
            linked_file = os.path.basename(link_match.group(2))
            buckets[linked_file] = current_bucket

    return buckets


# ── Manifest builder ──────────────────────────────────────────────────────────

def build_manifest(wiki_dir: str, folder: str) -> dict:
    """Build the manifest for a single folder."""
    folder_path = os.path.join(wiki_dir, folder)
    map_path = os.path.join(folder_path, "MAP.md")

    buckets = parse_map_buckets(map_path)

    pages = []
    hand_authored_count = 0
    auto_count = 0

    for fname in sorted(os.listdir(folder_path)):
        if not fname.endswith(".md") or fname == "MAP.md":
            continue

        fpath = os.path.join(folder_path, fname)
        try:
            with open(fpath, errors="replace") as f:
                content = f.read()
        except OSError:
            continue

        fm = parse_frontmatter(content)
        ptype = derive_page_type(fname, folder)
        authored = is_hand_authored(fname, ptype)

        if authored:
            hand_authored_count += 1
        else:
            auto_count += 1

        # Title fallback: derive from filename
        title = fm.get("title") or fname.replace(".md", "").replace("_", " ").replace("-", " ").title()

        entry = {
            "path": f"{folder}/{fname}",
            "filename": fname,
            "title": title,
            "page_type": ptype,
            "is_hand_authored": authored,
            "topic_bucket": buckets.get(fname),
            "tags": fm.get("tags", []),
            "related": fm.get("related", []),
        }
        pages.append(entry)

    # Build topic_bucket index: bucket -> list of paths
    by_bucket: dict = {}
    unindexed = []
    for p in pages:
        b = p["topic_bucket"]
        if b:
            by_bucket.setdefault(b, []).append(p["path"])
        elif p["is_hand_authored"]:
            unindexed.append(p["path"])

    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "folder": folder,
        "total_pages": len(pages),
        "hand_authored": hand_authored_count,
        "auto_stubs": auto_count,
        "has_map": os.path.isfile(map_path),
        "topic_buckets": list(by_bucket.keys()),
        "by_bucket": by_bucket,
        "unindexed_hand_authored": unindexed,
        "pages": pages,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: wiki-manifest.py <wiki_dir> [<folder>]", file=sys.stderr)
        sys.exit(1)

    wiki_dir = sys.argv[1]
    folders = [sys.argv[2]] if len(sys.argv) >= 3 else ["systems", "pages"]

    for folder in folders:
        folder_path = os.path.join(wiki_dir, folder)
        if not os.path.isdir(folder_path):
            print(f"SKIP: {folder}/ not found in {wiki_dir}", file=sys.stderr)
            continue

        manifest = build_manifest(wiki_dir, folder)
        out_path = os.path.join(folder_path, "manifest.json")

        # Atomic write
        tmp = out_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(manifest, f, indent=2)
        os.replace(tmp, out_path)

        print(
            f"manifest.json: {folder}/ — {manifest['total_pages']} pages "
            f"({manifest['hand_authored']} hand-authored, {manifest['auto_stubs']} auto-stubs), "
            f"{len(manifest['topic_buckets'])} topic buckets"
        )


if __name__ == "__main__":
    main()
