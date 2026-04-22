#!/usr/bin/env python3
"""task-schema-validator.py — Validate task files against lifecycle rules.

Scans brain/ops/tasks/{queue,active,completed}/ and emits structured issues
in LEVEL|CODE|MESSAGE format for consumption by brain-state-check.

Usage:
    python3 task-schema-validator.py <ops_tasks_dir>

Exit codes:
    0 = all OK
    1 = DRIFT or CONFLICT found
"""

import os
import re
import sys

TASK_ID_PATTERN = re.compile(r'^TASK-\d{4}-\d{2}-\d{2}-\d{3}[A-Z]?$')
FRONTMATTER_OPEN = re.compile(r'^---\s*$')
VALID_ARCHITECTURE_SCOPES = {
    "brain-core", "brain-module", "shared-infra",
    "governance-doc", "external-build", "experimental", "deprecation",
}


def extract_frontmatter(content):
    """Extract frontmatter fields from markdown. Returns dict or None."""
    lines = content.split('\n')
    if not lines or not FRONTMATTER_OPEN.match(lines[0]):
        return None

    fm_lines = []
    for line in lines[1:]:
        if FRONTMATTER_OPEN.match(line):
            break
        fm_lines.append(line)
    else:
        return None  # no closing ---

    fields = {}
    for line in fm_lines:
        m = re.match(r'^(\w+):\s*"?([^"]*)"?\s*$', line)
        if m:
            fields[m.group(1)] = m.group(2)
    return fields


def validate_task(filepath, folder):
    """Validate a single task file. Yields (level, code, message) tuples."""
    fname = os.path.basename(filepath)
    stem = fname.replace('.md', '')

    # Filename format
    if not TASK_ID_PATTERN.match(stem):
        yield ('DRIFT', 'TASK_ID_FORMAT', f'{fname}: invalid task_id format (expected TASK-YYYY-MM-DD-NNN)')

    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except OSError as e:
        yield ('DRIFT', 'TASK_UNREADABLE', f'{fname}: cannot read file: {e.strerror}')
        return

    # Frontmatter
    fm = extract_frontmatter(content)
    if fm is None:
        yield ('CONFLICT', 'FRONTMATTER_MISSING', f'{fname}: no valid frontmatter found')
        return

    # Required fields
    for key in ('task_id', 'status', 'owner'):
        if key not in fm or not fm[key]:
            yield ('DRIFT', 'FIELD_MISSING', f'{fname}: required field "{key}" missing')

    task_id = fm.get('task_id', '')
    status = fm.get('status', '')
    owner = fm.get('owner', '')

    # task_id matches filename
    if task_id and task_id != stem:
        yield ('DRIFT', 'TASKID_FILENAME_MISMATCH', f'{fname}: task_id="{task_id}" does not match filename')

    # task_id format
    if task_id and not TASK_ID_PATTERN.match(task_id):
        yield ('DRIFT', 'TASK_ID_FORMAT', f'{fname}: task_id="{task_id}" does not match expected pattern')

    # requires_agent: optional advisory routing field
    VALID_AGENTS = {'gemini', 'codex', 'claude-code', 'human', 'any'}
    requires_agent = fm.get('requires_agent', '')
    if requires_agent and requires_agent not in VALID_AGENTS:
        yield ('DRIFT', 'REQUIRES_AGENT_INVALID',
               f'{fname}: requires_agent="{requires_agent}" not in {sorted(VALID_AGENTS)}')

    # architecture_scope: validate value if present; silent if absent (backward compat)
    arch_scope = fm.get('architecture_scope', '')
    if arch_scope and arch_scope not in VALID_ARCHITECTURE_SCOPES:
        yield ('DRIFT', 'ARCH_SCOPE_INVALID',
               f'{fname}: architecture_scope="{arch_scope}" not in allowed values: '
               f'{sorted(VALID_ARCHITECTURE_SCOPES)}')

    # Folder-specific invariants
    if folder == 'queue':
        if status not in ('queued', 'parked'):
            yield ('DRIFT', 'QUEUE_STATUS', f'{fname}: status="{status}" in queue/ (must be queued or parked)')
        if owner and owner != 'unassigned':
            yield ('DRIFT', 'QUEUE_OWNER', f'{fname}: owner="{owner}" in queue/ (must be unassigned)')

    elif folder == 'active':
        if status not in ('active', 'blocked'):
            yield ('DRIFT', 'ACTIVE_STATUS', f'{fname}: status="{status}" in active/ (must be active or blocked)')
        if not owner or owner == 'unassigned':
            yield ('DRIFT', 'ACTIVE_OWNER', f'{fname}: owner="{owner}" in active/ (must be assigned)')

    elif folder == 'completed':
        if status not in ('completed', 'cancelled'):
            yield ('DRIFT', 'COMPLETED_STATUS', f'{fname}: status="{status}" in completed/ (must be completed or cancelled)')

        # Results section
        if '## Results' not in content:
            yield ('DRIFT', 'COMPLETED_NO_RESULTS', f'{fname}: missing ## Results section')
        else:
            if not re.search(r'\*\*Completed by:\*\*.*[a-z]', content):
                yield ('DRIFT', 'COMPLETED_NO_BY', f'{fname}: missing or empty Completed by')
            if not re.search(r'\*\*Completed on:\*\*.*[0-9]', content):
                yield ('DRIFT', 'COMPLETED_NO_DATE', f'{fname}: missing or empty Completed on')
            if not re.search(r'\*\*Output:\*\*.*[a-z0-9]', content):
                yield ('DRIFT', 'COMPLETED_NO_OUTPUT', f'{fname}: missing or empty Output')

        # Placeholder residue
        if 'Filled in by the completing agent' in content:
            yield ('DRIFT', 'PLACEHOLDER_RESIDUE', f'{fname}: template placeholder text remains')


def main():
    if len(sys.argv) < 2:
        print("Usage: task-schema-validator.py <ops_tasks_dir>", file=sys.stderr)
        sys.exit(1)

    ops_dir = sys.argv[1]
    has_issues = False

    for folder in ('queue', 'active', 'completed'):
        folder_path = os.path.join(ops_dir, folder)
        if not os.path.isdir(folder_path):
            continue
        for fname in sorted(os.listdir(folder_path)):
            if not fname.startswith('TASK-') or not fname.endswith('.md'):
                continue
            filepath = os.path.join(folder_path, fname)
            for level, code, message in validate_task(filepath, folder):
                print(f"{level}|{code}|{message}")
                if level in ('DRIFT', 'CONFLICT'):
                    has_issues = True

    sys.exit(1 if has_issues else 0)


if __name__ == '__main__':
    main()
