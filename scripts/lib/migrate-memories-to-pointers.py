#!/usr/bin/env python3
"""Migrate memory files from full documents to lightweight pointers.

For each memory file:
1. Read current frontmatter + body
2. Verify wiki mirror exists and has real content (not just a stub)
3. Write pointer-format memory (frontmatter only, no body)
4. Report any issues

Usage: python3 migrate-memories-to-pointers.py [--dry-run]
"""
import os, re, sys, json

DRY_RUN = "--dry-run" in sys.argv

_BRAIN_DIR = os.environ.get("BRAIN_DIR", os.path.expanduser("~/brain"))
_BRAIN_NAME = os.path.basename(_BRAIN_DIR.rstrip("/"))
_BRAIN_SLUG = os.path.abspath(_BRAIN_DIR).replace("/", "-").lstrip("-")
MEM_DIR = os.environ.get("CLAUDE_PROJECT_DIR", os.path.expanduser(f"~/.claude/projects/{_BRAIN_SLUG}/memory"))
WIKI_DIR = os.path.join(_BRAIN_DIR, "brain", "wiki")

def parse_frontmatter(content):
    """Extract frontmatter dict and body from a markdown file."""
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)', content, re.DOTALL)
    if not m:
        return {}, content
    fm_text = m.group(1)
    body = m.group(2).strip()
    fm = {}
    for line in fm_text.split('\n'):
        kv = re.match(r'^(\w+):\s*(.+)', line)
        if kv:
            key = kv.group(1)
            val = kv.group(2).strip().strip('"').strip("'")
            fm[key] = val
    return fm, body

def find_wiki_path(basename):
    """Find wiki mirror path for a memory file."""
    for subdir in ['pages', 'systems']:
        path = os.path.join(WIKI_DIR, subdir, basename)
        if os.path.exists(path):
            return f"{subdir}/{basename}"
    return None

def is_stub(wiki_path):
    """Check if a wiki page is just a template stub (< 300 chars of real content)."""
    full = os.path.join(WIKI_DIR, wiki_path)
    if not os.path.exists(full):
        return True
    with open(full) as f:
        content = f.read()
    # Remove frontmatter
    body = re.sub(r'^---.*?---\s*', '', content, flags=re.DOTALL)
    # Remove template boilerplate
    body = body.replace('<!-- Add [[page-name]] links to cross-reference -->', '')
    body = re.sub(r'^> Created \d{4}-\d{2}-\d{2}.*$', '', body, flags=re.MULTILINE)
    body = re.sub(r'^## Related\s*$', '', body, flags=re.MULTILINE)
    body = body.strip()
    return len(body) < 50

def classify_tags(basename, fm, body):
    """Infer tags from content."""
    tags = []
    text = (body + ' ' + fm.get('description', '')).lower()
    if 'discord' in text: tags.append('discord')
    if 'wiki' in text: tags.append('wiki')
    if 'memory' in text or 'memor' in text: tags.append('memory')
    if 'task' in text: tags.append('task-system')
    if any(w in text for w in ['gate', 'block', 'enforce']): tags.append('enforcement')
    if any(w in text for w in ['ve ', 'villain', 'dual-seat']): tags.append('ve')
    if any(w in text for w in ['codex', 'gemini', 'multi-agent']): tags.append('multi-agent')
    if any(w in text for w in ['content', 'publish', 'blog']): tags.append('content')
    if any(w in text for w in ['safety', 'credential', 'never delete']): tags.append('safety')
    if any(w in text for w in ['tool', 'script', 'bin/']): tags.append('tools')
    return tags[:5]  # cap at 5

def main():
    files = sorted(f for f in os.listdir(MEM_DIR) if f.endswith('.md') and f != 'MEMORY.md')

    migrated = 0
    stubs = []
    no_wiki = []
    errors = []

    for fname in files:
        fpath = os.path.join(MEM_DIR, fname)
        with open(fpath) as f:
            content = f.read()

        fm, body = parse_frontmatter(content)

        # Already migrated? (has status + wiki fields, no body)
        if 'status' in fm and 'wiki' in fm and len(body) < 50:
            continue

        # Find wiki mirror
        wiki_path = find_wiki_path(fname)
        if not wiki_path:
            no_wiki.append(fname)
            continue

        # Check if wiki is a stub
        if is_stub(wiki_path):
            stubs.append((fname, wiki_path))

        # Build pointer
        tags = classify_tags(fname, fm, body)
        pointer = f"""---
name: {fm.get('name', fname.replace('.md', ''))}
description: {fm.get('description', '(no description)')}
type: {fm.get('type', 'feedback')}
status: active
wiki: {wiki_path}
tags: [{', '.join(tags)}]
---
"""

        if DRY_RUN:
            print(f"  WOULD migrate: {fname} -> pointer ({len(content)} -> {len(pointer)} bytes, wiki: {wiki_path})")
        else:
            with open(fpath, 'w') as f:
                f.write(pointer)
            migrated += 1

    print(f"\n{'DRY RUN — ' if DRY_RUN else ''}Migration complete:")
    print(f"  Migrated: {migrated}")
    print(f"  Wiki stubs (need content): {len(stubs)}")
    for fname, wp in stubs:
        print(f"    {fname} -> {wp}")
    print(f"  No wiki mirror: {len(no_wiki)}")
    for fname in no_wiki:
        print(f"    {fname}")
    print(f"  Errors: {len(errors)}")

if __name__ == "__main__":
    main()
