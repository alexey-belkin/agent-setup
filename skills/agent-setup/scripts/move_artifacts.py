#!/usr/bin/env python3
"""Move files/directories and rebase supported Markdown links; preview by default.

Inspired by the incoming-link preview in a working PM workspace. This version
moves the source too, rebases its outgoing links and edits exact URL spans.
"""
from __future__ import annotations

import argparse
import difflib
import os
import sys
from pathlib import Path

from workspace_paths import excluded, files, inside, relocated, rewrite_links


class MoveError(ValueError):
    pass


def plan(root: Path, pairs: list[list[str]], excludes: list[str]):
    moves = {}
    for before, after in pairs:
        old, new = inside(root, before), inside(root, after)
        if not old.exists() or not (old.is_file() or old.is_dir()):
            raise MoveError(f'Missing/unsupported source: {before}')
        if new.exists():
            raise MoveError(f'Destination already exists: {after}')
        if old in moves or old == new or new.is_relative_to(old):
            raise MoveError(f'Duplicate, unchanged or recursive move: {before} -> {after}')
        if excluded(old.relative_to(root), excludes) or excluded(new.relative_to(root), excludes):
            raise MoveError('Explicit move crosses an excluded path')
        if old.is_dir() and any(p.is_symlink() or p.name == '.git' for p in old.rglob('*')):
            raise MoveError(f'Source directory contains a symlink or nested repository: {before}')
        moves[old] = new
    items = list(moves.items())
    for i, (old, new) in enumerate(items):
        for other, target in items[i + 1:]:
            if any(a == b or a.is_relative_to(b) or b.is_relative_to(a)
                   for a, b in [(old, other), (new, target), (new, other), (target, old)]):
                raise MoveError('Overlapping/chained moves are not supported; use separate invocations')
    edits, skipped = {}, []
    for path in files(root, excludes):
        if path.suffix.lower() not in {'.md', '.mdc'}:
            continue
        before = path.read_bytes()
        text = before.decode('utf-8')
        destination = relocated(path, moves)
        after = rewrite_links(text, path, destination, moves).encode('utf-8')
        if before != after:
            edits[path] = (destination, before, after)
    # Detect likely non-Markdown consumers; do not rewrite config/code blindly.
    for path in files(root, excludes):
        if path.suffix.lower() not in {'.yaml', '.yml', '.json', '.toml', '.py', '.sh', '.html'}:
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeError:
            skipped.append('unreadable:' + path.relative_to(root).as_posix())
            continue
        needles = {value for old in moves for value in (
            old.relative_to(root).as_posix(), os.path.relpath(old, path.parent).replace(os.sep, '/'))}
        if any(value in text for value in needles):
            skipped.append(path.relative_to(root).as_posix())
    return moves, edits, skipped


def apply_plan(root: Path, moves: dict, edits: dict):
    # Recheck editable inputs before the first mutation; no Git commands are run.
    for source, (_, before, _) in edits.items():
        if source.read_bytes() != before:
            raise MoveError(f'Input changed after planning: {source.relative_to(root)}')
    done, created, written = [], [], []
    try:
        for old, new in moves.items():
            if new.exists():
                raise MoveError(f'Destination appeared after planning: {new.relative_to(root)}')
            missing, cursor = [], new.parent
            while not cursor.exists():
                missing.append(cursor)
                cursor = cursor.parent
            for directory in reversed(missing):
                directory.mkdir()
                created.append(directory)
            os.rename(old, new)
            done.append((old, new))
        for source, (destination, before, after) in edits.items():
            # Keep permission bits by writing through the existing file.
            written.append((destination, before))
            destination.write_bytes(after)
    except Exception:
        failures = []
        for destination, before in reversed(written):
            try:
                destination.write_bytes(before)
            except OSError as exc:
                failures.append(str(exc))
        for old, new in reversed(done):
            try:
                os.rename(new, old)
            except OSError as exc:
                failures.append(str(exc))
        for directory in reversed(created):
            try:
                directory.rmdir()
            except OSError:
                pass
        if failures:
            raise MoveError('Rollback incomplete; inspect workspace: ' + '; '.join(failures))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--move', nargs=2, action='append', required=True, metavar=('OLD', 'NEW'))
    parser.add_argument('--exclude', action='append', default=[], help='Segment or fnmatch; unscanned references may remain')
    parser.add_argument('--apply', action='store_true', help='Move and edit; default is read-only preview')
    parser.add_argument('--allow-unhandled', action='store_true', help='Acknowledge reported config/code consumers; fix them separately')
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        if not root.is_dir():
            raise MoveError('Root must be an existing directory')
        moves, edits, skipped = plan(root, args.move, args.exclude)
        for old, new in moves.items():
            print(f'MOVE {old.relative_to(root)} -> {new.relative_to(root)}')
        for source, (destination, before, after) in edits.items():
            sys.stdout.writelines(difflib.unified_diff(
                before.decode('utf-8').splitlines(True), after.decode('utf-8').splitlines(True),
                fromfile=source.relative_to(root).as_posix(), tofile=destination.relative_to(root).as_posix()))
        print(f'{len(moves)} moves; {len(edits)} Markdown files rebased')
        print('Scope: inline/image/reference Markdown links outside code; excludes and other syntaxes require review.')
        if skipped:
            print('UNHANDLED config/code consumers: ' + ', '.join(skipped))
            if args.apply and not args.allow_unhandled:
                raise MoveError('Review these consumers; use --allow-unhandled only with a separate update plan')
        if args.apply:
            apply_plan(root, moves, edits)
            print('APPLIED; rebuild derived registries and run project link/acceptance checks')
        else:
            print('PREVIEW; no files changed')
        return 0
    except (ValueError, OSError, UnicodeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
