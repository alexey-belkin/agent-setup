#!/usr/bin/env python3
"""Static package validation. Never runs the skill or mutates a target project."""
from pathlib import Path
from urllib.parse import unquote, urlsplit
import json
import re
import unicodedata


def prose(text):
    result, fence = [], None
    for line in text.splitlines():
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            result.append(line)
    return '\n'.join(result)


def anchors(text):
    result, counts = set(), {}
    for line in prose(text).splitlines():
        if not re.match(r'^#{1,6} ', line):
            continue
        title = re.sub(r'^#+\s+', '', line).replace('`', '').replace('*', '').lower()
        slug = ''.join(c for c in title if c in '_- ' or unicodedata.category(c)[0] in 'LN').replace(' ', '-')
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(slug if count == 0 else f'{slug}-{count}')
    return result


def check(root):
    root = root.resolve()
    skill = root / 'skills/agent-setup'
    errors, edges, external = [], {}, set()
    aliases = {'CLAUDE.md': 'AGENTS.md', '.agents/skills/agent-setup': 'skills/agent-setup', '.claude/skills/agent-setup': 'skills/agent-setup'}
    files = []
    for path in root.rglob('*'):
        rel = path.relative_to(root)
        if any(p in {'.git', 'dist', '__pycache__'} for p in rel.parts):
            continue
        if path.is_symlink():
            target = aliases.get(rel.as_posix())
            if target is None or path.resolve() != (root / target).resolve() or not path.exists():
                errors.append(f'Unexpected or broken alias: {rel}')
        elif path.is_file():
            files.append(path)
    for rel, target in aliases.items():
        if not (root / rel).is_symlink():
            errors.append(f'Missing expected delivery alias: {rel}')
    for path in files:
        if path.suffix not in {'.md', '.py', '.yaml', '.json'}:
            continue
        text = path.read_text()
        # Exact personal markers, not a proof that all sensitive text is absent.
        if re.search(r'/Users/|/private/|Yandex\.Disk-|My Drive/|gh[pousr]_[A-Za-z0-9]{16,}|sk-[A-Za-z0-9]{20,}', text):
            # This checker contains pattern literals, not actual account values.
            if path != root / 'scripts/check_package.py':
                errors.append(f'Known private path/token marker: {path.relative_to(root)}')
        if path.suffix != '.md':
            continue
        body = prose(text)
        edges[path] = set()
        if re.search(r'^\s*\[[^]]+\]:', body, re.M):
            errors.append(f'Unhandled reference-style link: {path.relative_to(root)}')
        for raw in re.findall(r'\]\((<[^>]+>|[^)]+)\)', body):
            dest = raw.strip().strip('<>')
            if '{{' in dest and path.is_relative_to(skill / 'assets/templates'):
                continue
            if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', dest):
                u = urlsplit(dest)
                if u.scheme != 'https' or u.username or u.password or u.hostname not in {'github.com', 'learn.chatgpt.com', 'code.claude.com'}:
                    errors.append(f'External link needs review: {dest}')
                external.add(dest)
                continue
            target, _, anchor = unquote(dest).partition('#')
            resolved = (path.parent / target).resolve() if target else path
            if not resolved.is_relative_to(root) or not resolved.is_file():
                errors.append(f'{path.relative_to(root)}: missing/outside link {dest}')
                continue
            if path.is_relative_to(skill) and not resolved.is_relative_to(skill):
                errors.append(f'Skill dependency outside bundle: {path.relative_to(root)} -> {dest}')
            if anchor and resolved.suffix == '.md' and anchor not in anchors(resolved.read_text()):
                errors.append(f'{path.relative_to(root)}: bad anchor {dest}')
            if resolved.suffix == '.md':
                edges[path].add(resolved)
    reached, pending = set(), [root / 'AGENTS.md']
    while pending:
        node = pending.pop()
        if node not in reached:
            reached.add(node)
            pending.extend(edges.get(node, set()) - reached)
    for node in set(edges) - reached:
        errors.append(f'Markdown unreachable from AGENTS: {node.relative_to(root)}')
    return {'version': (root / 'VERSION').read_text().strip(), 'scope': 'Static structure/link/privacy-marker scan only; no skill or model execution', 'files': len(files), 'markdownFiles': len(edges), 'externalLinks': sorted(external), 'skillSelfContained': not any('outside bundle' in e for e in errors), 'behaviorTests': 'not-run by explicit user instruction', 'errors': errors, 'status': 'fail' if errors else 'pass'}


if __name__ == '__main__':
    result = check(Path(__file__).resolve().parents[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(result['status'] != 'pass')
