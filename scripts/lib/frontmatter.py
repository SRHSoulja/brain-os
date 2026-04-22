"""Shared frontmatter parser for Brain CLI tools (Python version).

Usage:
    from frontmatter import parse_frontmatter, fm_get

    meta = parse_frontmatter("/path/to/file.md")
    title = meta.get("title", "")

    # Or one-shot:
    title = fm_get("/path/to/file.md", "title")

Handles: quoted values, unquoted values, empty strings, booleans, arrays (as strings or lists).
Does NOT handle: multiline values, nested objects.
"""

import re
import os


def parse_frontmatter(filepath):
    """Parse YAML frontmatter from a markdown file. Returns dict of key→value."""
    if not os.path.isfile(filepath):
        return {}

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (IOError, UnicodeDecodeError):
        return {}

    if not lines or lines[0].strip() != "---":
        return {}

    meta = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r'^(\w[\w_-]*)\s*:\s*(.*)', line)
        if m:
            key = m.group(1)
            raw = m.group(2).strip()
            meta[key] = _parse_value(raw)

    return meta


def _parse_value(raw):
    """Parse a single YAML value: quoted string, boolean, array, or bare value."""
    if not raw:
        return ""

    # Quoted string
    if (raw.startswith('"') and raw.endswith('"')) or \
       (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]

    # Boolean
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False

    # Array (simple single-line JSON-like)
    if raw.startswith("[") and raw.endswith("]"):
        try:
            import json
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return raw

    # Bare value
    return raw


def fm_get(filepath, key, default=""):
    """Get a single frontmatter value. Returns default if missing."""
    meta = parse_frontmatter(filepath)
    val = meta.get(key, default)
    # Coerce booleans to strings for shell-compatible usage
    if isinstance(val, bool):
        return "true" if val else "false"
    return val


def fm_has(filepath, key):
    """Check if a frontmatter key exists."""
    return key in parse_frontmatter(filepath)


def has_frontmatter(filepath):
    """Check if a file starts with --- (has frontmatter block)."""
    if not os.path.isfile(filepath):
        return False
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            first_line = f.readline()
        return first_line.strip() == "---"
    except (IOError, UnicodeDecodeError):
        return False


def fm_probe(filepath, key):
    """Diagnostic status check for frontmatter parsing.

    Returns:
        0 = key present and parseable
        1 = key missing (frontmatter exists, key not in it)
        2 = no frontmatter or file missing
        3 = malformed frontmatter (starts with --- but no closing ---)
    """
    if not os.path.isfile(filepath):
        return 2

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (IOError, UnicodeDecodeError):
        return 2

    if not lines or lines[0].strip() != "---":
        return 2

    # Check for closing ---
    found_closing = False
    for line in lines[1:]:
        if line.strip() == "---":
            found_closing = True
            break

    if not found_closing:
        return 3

    # Check if key exists
    meta = parse_frontmatter(filepath)
    return 0 if key in meta else 1
