#!/usr/bin/env python3
"""Read-only tree metadata; semantic roles and operational success require review."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath

TECHNICAL = {'.git', 'node_modules', '.venv', '.venv-policy', 'venv',
             '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.next'}
GUIDES = {'agents.md', 'claude.md', 'readme.md', 'skill.md'}
IGNORES = {'.gitignore', '.cursorignore', '.cursorindexingignore', '.claudeignore',
           '.codexignore', '.zcodeignore', '.dockerignore', '.codeiumignore'}


def inspect_tree(root, boundaries=(), output=None):
    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError('root must be a directory')
    requested = set()
    for value in boundaries:
        p = PurePosixPath(value)
        if p.is_absolute() or '..' in p.parts or str(p) == '.':
            raise ValueError('boundary must be a non-root relative path without ..')
        requested.add(str(p))
    output = Path(output).expanduser().absolute() if output else None
    rows, edges, errors, git_markers, ignore_files, hints = [], [], [], [], [], []
    matched = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        rel = directory.relative_to(root).as_posix()
        row = {'path': rel, 'files': [], 'extensions': {}, 'guides': [],
               'children': [], 'boundaries': []}
        rows.append(row)
        try:
            with os.scandir(directory) as entries:
                children = sorted(entries, key=lambda e: e.name)
        except OSError as exc:
            errors.append({'path': rel, 'operation': 'list', 'error': type(exc).__name__})
            continue
        subdirs = []
        for entry in children:
            p = Path(entry.path)
            path = p.relative_to(root).as_posix()
            if output and p.absolute() == output:
                continue
            if entry.name == '.git':
                git_markers.append(path)  # file marker covers submodule/worktree too
            if entry.name.lower() in IGNORES:
                ignore_files.append(path)
            if entry.name.lower() in GUIDES:
                row['guides'].append(entry.name)
            if entry.name == 'SKILL.md':
                hints.append({'path': path, 'kind': 'skill-candidate'})
            elif p.suffix.lower() in {'.md', '.mdc'} and any(
                    s in {'commands', 'rules'} for s in p.relative_to(root).parts[:-1]):
                hints.append({'path': path, 'kind': 'command-or-rule-candidate'})
            try:
                if path in requested:
                    matched.add(path)
                if entry.is_symlink():
                    target = p.resolve(strict=False)
                    edge = {'path': path, 'kind': 'symlink', 'target': str(target),
                            'targetExists': target.exists(),
                            'insideRoot': target == root or root in target.parents}
                    edges.append(edge)
                    row['boundaries'].append(path)
                elif entry.is_dir(follow_symlinks=False):
                    row['children'].append(entry.name)
                    technical = entry.name in TECHNICAL or p.parts[-2:] == ('.claude', 'worktrees')
                    if technical or path in requested:
                        edges.append({'path': path, 'kind': 'explicit-boundary' if path in requested else 'technical-boundary'})
                        row['boundaries'].append(path)
                    else:
                        subdirs.append(p)
                elif entry.is_file(follow_symlinks=False):
                    if path in requested:
                        edges.append({'path': path, 'kind': 'explicit-boundary', 'nodeType': 'file'})
                        row['boundaries'].append(path)
                    else:
                        row['files'].append(entry.name)
            except (OSError, RuntimeError) as exc:
                errors.append({'path': path, 'operation': 'inspect', 'error': type(exc).__name__})
        row['extensions'] = dict(sorted(Counter(Path(f).suffix.lower() or '<none>' for f in row['files']).items()))
        row['empty'] = not children
        pending.extend(reversed(subdirs))
    for path in sorted(requested - matched):
        errors.append({'path': path, 'operation': 'boundary', 'error': 'not encountered; check path or enclosing boundary'})
    return {'schemaVersion': 1, 'root': str(root),
            'observedAt': datetime.now(timezone.utc).isoformat(),
            'scope': 'Names/metadata only; no content, network, Git commands or semantic classification. Symlinks not followed. Archives/dist not excluded by name.',
            'technicalNames': sorted(TECHNICAL), 'requestedBoundaries': sorted(requested),
            'folders': rows, 'boundaries': sorted(edges, key=lambda x: x['path']),
            'gitMarkers': sorted(git_markers), 'ignoreFiles': sorted(ignore_files),
            'controlCandidates': sorted(hints, key=lambda x: x['path']), 'errors': errors,
            'status': 'partial' if errors else 'metadata-complete-within-declared-boundaries'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--boundary', action='append', default=[])
    args = parser.parse_args()
    try:
        result = inspect_tree(args.root, args.boundary, args.out)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    dest = Path(args.out).expanduser().absolute()
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Only this explicitly named output is written; source files/config are untouched.
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps({'output': str(dest), 'folders': len(result['folders']),
                      'boundaries': len(result['boundaries']), 'status': result['status']}, ensure_ascii=False))
    return 2 if result['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
