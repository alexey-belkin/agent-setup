#!/usr/bin/env python3
"""Read-only presence/basic-manifest/reachability check; never invokes a skill."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import unquote


def prose(text):
    result, fence = [], None
    for line in text.splitlines():
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            result.append(line)
    return '\n'.join(result)


def contained(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Entry and installed skill must stay inside the target project')
    return path


def check(root, entry='AGENTS.md', skill='.agents/skills/auto-improve/SKILL.md'):
    root = Path(root).resolve(strict=True)
    start, target = contained(root, entry), contained(root, skill)
    errors = []
    if not start.is_file():
        errors.append('Missing working entry: ' + entry)
    if not target.is_file():
        errors.append('Missing installed auto-improve: ' + skill)
    else:
        body = target.read_text(encoding='utf-8-sig')
        header = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)', body, re.S)
        if not header:
            errors.append('Installed skill lacks frontmatter')
        else:
            fields = header.group(1)
            if not re.search(r'^name:[ \t]*[\'\"]?auto-improve[\'\"]?\s*$', fields, re.M):
                errors.append('Installed skill name must be auto-improve')
            if not re.search(r'^description:[ \t]*\S', fields, re.M):
                errors.append('Installed skill lacks a description value or block marker')
    # Traverse real Markdown links, not a bare ID/mention or fenced example.
    reached, pending = set(), [start]
    while pending and target not in reached:
        node = pending.pop()
        if node in reached or not node.is_file():
            continue
        reached.add(node)
        if len(reached) > 2000:
            errors.append('Reachability search limit exceeded; result is incomplete')
            break
        text = prose(node.read_text(encoding='utf-8-sig'))
        for raw in re.findall(r'\]\((<[^>]+>|[^)]+)\)', text):
            link = raw.strip().strip('<>')
            if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', link) or '{{' in link:
                continue
            path = unquote(link).partition('#')[0]
            dest = (node.parent / path).resolve() if path else node
            if dest.is_relative_to(root) and dest.is_file() and dest.suffix.lower() in {'.md', '.mdc'}:
                pending.append(dest)
    if target not in reached:
        errors.append('Installed auto-improve is not reachable by Markdown links from the working entry')
    return {'scope': 'File presence, basic manifest fields and local Markdown reachability only; not full YAML validation, harness discovery or behavioral execution', 'entry': entry, 'skill': skill, 'reachable': target in reached, 'behavior': 'not-run', 'errors': errors, 'status': 'fail' if errors else 'pass'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--entry', default='AGENTS.md')
    parser.add_argument('--skill', default='.agents/skills/auto-improve/SKILL.md')
    args = parser.parse_args()
    try:
        result = check(args.root, args.entry, args.skill)
    except (OSError, ValueError) as error:
        result = {'status': 'fail', 'errors': [str(error)], 'behavior': 'not-run'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(result['status'] != 'pass')


if __name__ == '__main__':
    raise SystemExit(main())
