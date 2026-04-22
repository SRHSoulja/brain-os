#!/usr/bin/env python3
"""wiki-hub-generate.py -- Regenerate auto-link sections in hub_*.md pages.

For each hub page in brain/wiki/pages/ with hub_tags in frontmatter:
  - Scan all wiki pages (pages/ + systems/) for pages with matching tags
  - Rewrite the '## Linked Pages' section with current matches
  - Preserve all other sections (manually written narrative)

Hub page frontmatter expected fields:
  hub_tags: [tag1, tag2, ...]   -- tags that define membership

Usage:
  python3 wiki-hub-generate.py <wiki_dir> [--dry-run]
"""

import os, sys, re, glob

def parse_frontmatter(path):
    """Return (tags_list, raw_frontmatter_str, body_str)."""
    content = open(path).read()
    m = re.match(r'^---\n(.*?)\n---\n(.*)', content, re.DOTALL)
    if not m:
        return [], "", content
    fm_raw, body = m.group(1), m.group(2)
    tags = re.findall(r'[\w-]+', fm_raw.split('hub_tags:')[1].split('\n')[0]) \
           if 'hub_tags:' in fm_raw else []
    return tags, fm_raw, body

def scan_pages(wiki_dir, hub_tags, exclude_basename):
    """Return list of (basename, title, tags) for pages matching any hub_tag."""
    matches = []
    for pattern in (f'{wiki_dir}/pages/*.md', f'{wiki_dir}/systems/*.md'):
        for f in sorted(glob.glob(pattern)):
            b = os.path.basename(f)
            if b == exclude_basename or b.startswith('hub_'):
                continue
            in_fm = False
            tags, title = [], b.replace('.md', '')
            for line in open(f):
                line = line.rstrip()
                if line == '---':
                    if not in_fm: in_fm = True; continue
                    else: break
                if in_fm:
                    if line.startswith('tags:'):
                        tags = re.findall(r'[\w-]+', line.split(':', 1)[1])
                    elif line.startswith('title:'):
                        title = line.split(':', 1)[1].strip().strip('"')
            if any(t in hub_tags for t in tags):
                matched = sorted(set(t for t in tags if t in hub_tags))
                matches.append((b, title, matched))
    return matches

def build_linked_section(matches):
    """Build the auto-generated ## Linked Pages markdown block."""
    if not matches:
        return "## Linked Pages\n\n_No pages currently tagged for this hub._\n"
    lines = ["## Linked Pages", "", "_Auto-generated from tags. Do not hand-edit this section._", ""]
    for basename, title, matched_tags in matches:
        page_ref = basename.replace('.md', '')
        tag_str = ', '.join(f'`{t}`' for t in matched_tags)
        lines.append(f"- [[{page_ref}]] — {title[:80]} _{tag_str}_")
    lines.append("")
    return '\n'.join(lines)

def rewrite_hub(path, dry_run=False):
    """Rewrite the ## Linked Pages section of a hub page. Return (changed, count)."""
    hub_tags, fm_raw, body = parse_frontmatter(path)
    if not hub_tags:
        return False, 0

    wiki_dir = os.path.dirname(os.path.dirname(path))  # pages/ -> wiki/
    matches = scan_pages(wiki_dir, set(hub_tags), os.path.basename(path))
    new_section = build_linked_section(matches)

    # Replace existing ## Linked Pages section or append
    linked_pattern = re.compile(
        r'## Linked Pages\n.*?(?=\n## |\Z)', re.DOTALL)
    if linked_pattern.search(body):
        new_body = linked_pattern.sub(new_section.rstrip(), body)
    else:
        new_body = body.rstrip('\n') + '\n\n' + new_section

    new_content = f"---\n{fm_raw}\n---\n{new_body}"
    old_content = open(path).read()
    if new_content == old_content:
        return False, len(matches)

    if not dry_run:
        with open(path, 'w') as f:
            f.write(new_content)
    return True, len(matches)

def main():
    if len(sys.argv) < 2:
        print("Usage: wiki-hub-generate.py <wiki_dir> [--dry-run]")
        sys.exit(1)

    wiki_dir = sys.argv[1]
    dry_run = '--dry-run' in sys.argv

    hub_pages = sorted(glob.glob(f'{wiki_dir}/pages/hub_*.md'))
    if not hub_pages:
        print("No hub pages found (hub_*.md in pages/).")
        return

    total_changed = 0
    for path in hub_pages:
        changed, count = rewrite_hub(path, dry_run)
        status = 'updated' if changed else 'unchanged'
        if dry_run and changed:
            status = 'would-update'
        print(f"  {os.path.basename(path)}: {count} linked page(s) [{status}]")
        if changed:
            total_changed += 1

    print(f"\n{total_changed}/{len(hub_pages)} hub(s) {'would be ' if dry_run else ''}updated.")

if __name__ == '__main__':
    main()
