#!/usr/bin/env python3
"""devlog-to-post.py — Convert a brain devlog markdown file to a blog post PHP artifact.

Reads markdown with YAML frontmatter, converts body to HTML, outputs a PHP
array file matching a generic blog engine format.

Usage:
    python3 devlog-to-post.py <devlog.md> <output_dir>
    python3 devlog-to-post.py <devlog.md> --dry-run

Markdown to HTML conversion is done with stdlib only (no external deps).
Uses a simple line-by-line converter for headings, paragraphs, lists,
code blocks, blockquotes, bold, italic, inline code, and links.
"""

import os
import re
import sys
from datetime import datetime, timezone


def parse_frontmatter(content):
    """Extract YAML-like frontmatter and body from markdown."""
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, content

    fm_lines = []
    body_start = 1
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            body_start = i + 1
            break
        fm_lines.append(line)

    fields = {}
    for line in fm_lines:
        m = re.match(r'^(\w+):\s*"?([^"]*)"?\s*$', line)
        if m:
            key, val = m.group(1), m.group(2)
            if key == "tags":
                # Parse YAML-style array: ["tag1", "tag2"]
                tags = re.findall(r'"([^"]*)"', val)
                if not tags:
                    tags = [t.strip() for t in val.strip("[]").split(",") if t.strip()]
                fields[key] = tags
            else:
                fields[key] = val

    body = "\n".join(lines[body_start:]).strip()
    return fields, body


def md_to_html(md):
    """Convert markdown to HTML using simple line-by-line parsing."""
    lines = md.split("\n")
    html_lines = []
    in_code_block = False
    in_list = False
    in_paragraph = False

    def inline(text):
        """Process inline markdown: bold, italic, code, links."""
        # Code spans first (protect from other transforms)
        parts = re.split(r'(`[^`]+`)', text)
        result = []
        for part in parts:
            if part.startswith('`') and part.endswith('`'):
                result.append(f'<code>{esc(part[1:-1])}</code>')
            else:
                # Bold
                part = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', part)
                # Italic
                part = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', part)
                # Links
                part = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', part)
                result.append(part)
        return ''.join(result)

    def esc(s):
        return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    for line in lines:
        stripped = line.rstrip()

        # Code blocks
        if stripped.startswith("```"):
            if in_code_block:
                html_lines.append("</code></pre>")
                in_code_block = False
            else:
                if in_paragraph:
                    html_lines.append("</p>")
                    in_paragraph = False
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                lang = stripped[3:].strip()
                html_lines.append(f"<pre><code>")
                in_code_block = True
            continue

        if in_code_block:
            html_lines.append(esc(stripped))
            continue

        # Empty line
        if not stripped:
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue

        # Headings
        hm = re.match(r'^(#{1,4})\s+(.+)', stripped)
        if hm:
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            level = len(hm.group(1))
            text = inline(hm.group(2))
            html_lines.append(f"<h{level}>{text}</h{level}>")
            continue

        # Blockquotes
        if stripped.startswith(">"):
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            text = inline(stripped[1:].strip())
            html_lines.append(f"<blockquote>{text}</blockquote>")
            continue

        # List items
        lm = re.match(r'^[-*]\s+(.+)', stripped)
        if lm:
            if in_paragraph:
                html_lines.append("</p>")
                in_paragraph = False
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"  <li>{inline(lm.group(1))}</li>")
            continue

        # Regular text → paragraph
        if not in_paragraph:
            html_lines.append(f"<p>{inline(stripped)}")
            in_paragraph = True
        else:
            html_lines.append(f" {inline(stripped)}")

    # Close open tags
    if in_paragraph:
        html_lines.append("</p>")
    if in_list:
        html_lines.append("</ul>")
    if in_code_block:
        html_lines.append("</code></pre>")

    return "\n".join(html_lines)


def generate_post(devlog_path):
    """Generate a blog post dict from a devlog file."""
    with open(devlog_path, "r") as f:
        content = f.read()

    fm, body = parse_frontmatter(content)

    # Strip the first H1 if it matches the title (avoid duplication)
    title = fm.get("title", "")
    first_h1 = re.match(r'^#\s+(.+)', body)
    if first_h1:
        body = body[first_h1.end():].strip()

    # Generate slug from filename
    fname = os.path.basename(devlog_path).replace(".md", "")
    # Remove date prefix: 2026-03-13-brain-born → brain-born
    slug = re.sub(r'^\d{4}-\d{2}-\d{2}-', '', fname)

    # Extract summary: first non-empty, non-heading line
    summary = ""
    for line in body.split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and not line.startswith(">") and not line.startswith("-") and not line.startswith("```"):
            summary = line[:200]
            break

    # Convert body to HTML
    html_body = md_to_html(body)

    # Tags
    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    # Default author
    author = fm.get("author", "Claude")

    return {
        "title": title or fname,
        "slug": slug,
        "date": fm.get("date", ""),
        "author": author,
        "summary": summary,
        "tags": tags,
        "body": html_body,
        "status": "draft",
        "source_path": f"work/logs/devlog/{os.path.basename(devlog_path)}",
        "impact_ref": fm.get("impact_ref", ""),
    }


def to_php(post):
    """Convert a post dict to a PHP array file."""
    def php_str(s):
        return s.replace("\\", "\\\\").replace("'", "\\'")

    tags_php = ", ".join(f"'{php_str(t)}'" for t in post["tags"])

    php = f"""<?php
// Generated by brain-publish from: {post['source_path']}
// Converted at: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
return [
    'title' => '{php_str(post["title"])}',
    'slug' => '{php_str(post["slug"])}',
    'date' => '{php_str(post["date"])}',
    'author' => '{php_str(post["author"])}',
    'summary' => '{php_str(post["summary"])}',
    'tags' => [{tags_php}],
    'status' => '{php_str(post["status"])}',
    'source_path' => '{php_str(post["source_path"])}',
    'body' => <<<'HTML'

{post["body"]}

HTML
];
"""
    return php


def main():
    if len(sys.argv) < 2:
        print("Usage: devlog-to-post.py <devlog.md> [output_dir|--dry-run]", file=sys.stderr)
        sys.exit(1)

    devlog_path = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    output_dir = None
    for arg in sys.argv[2:]:
        if arg != "--dry-run":
            output_dir = arg

    if not os.path.isfile(devlog_path):
        print(f"Error: {devlog_path} not found", file=sys.stderr)
        sys.exit(1)

    post = generate_post(devlog_path)
    php = to_php(post)

    if dry_run:
        print(f"  Title: {post['title']}")
        print(f"  Slug: {post['slug']}")
        print(f"  Date: {post['date']}")
        print(f"  Author: {post['author']}")
        print(f"  Summary: {post['summary'][:80]}...")
        print(f"  Tags: {post['tags']}")
        print(f"  Source: {post['source_path']}")
        print(f"  Body: {len(post['body'])} chars HTML")
        sys.exit(0)

    if not output_dir:
        print(php)
        sys.exit(0)

    out_path = os.path.join(output_dir, f"{post['slug']}.php")
    with open(out_path, "w") as f:
        f.write(php)
    print(f"  Written: {out_path}")


if __name__ == "__main__":
    main()
