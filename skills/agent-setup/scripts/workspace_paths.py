"""Shared bounded Markdown/path support for the portable workspace tools."""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from urllib.parse import quote, unquote

TECHNICAL = {'.git', '.hg', '.svn', 'node_modules', '.venv', '__pycache__'}


def excluded(relative: Path, patterns: list[str]) -> bool:
    return any(part in TECHNICAL for part in relative.parts) or any(
        pattern in relative.parts if '/' not in pattern and not any(c in pattern for c in '*?[')
        else fnmatch.fnmatchcase(relative.as_posix(), pattern) for pattern in patterns
    )


def inside(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f'Expected a nonempty relative path: {value!r}')
    path = Path(os.path.abspath(root / value))
    if not path.is_relative_to(root) or path == root:
        raise ValueError(f'Path escapes or names the workspace root: {value}')
    cursor = path
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError(f'Symlink boundary: {cursor.relative_to(root)}')
        cursor = cursor.parent
    return path


def files(root: Path, patterns: list[str] | None = None):
    for base, dirs, names in os.walk(root, followlinks=False):
        parent = Path(base)
        dirs[:] = sorted(d for d in dirs if not (parent / d).is_symlink()
                         and not excluded((parent / d).relative_to(root), patterns or []))
        for name in sorted(names):
            path = parent / name
            if not path.is_symlink() and not excluded(path.relative_to(root), patterns or []):
                yield path


def relocated(path: Path, moves: dict[Path, Path]) -> Path:
    for old, new in moves.items():
        if path == old or path.is_relative_to(old):
            return new / path.relative_to(old)
    return path


def link_spans(text: str):
    """Yield URL-only spans for inline/images and reference definitions, outside code.

    Deliberately not a full CommonMark parser: HTML, wiki links, frontmatter
    path fields, indented code and multiline links are outside this contract.
    """
    offset, fence = 0, None
    for line in text.splitlines(keepends=True):
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            offset += len(line)
            continue
        if fence is not None or line.startswith(('    ', '\t')):
            offset += len(line)
            continue
        masked = re.sub(r'(`+)(.*?)\1', lambda m: ' ' * len(m.group()), line)
        starts = [m.end() for m in re.finditer(r'(?<!\\)\]\(', masked)]
        definition = re.match(r'^ {0,3}\[[^\]]+\]:\s*', masked)
        if definition:
            starts.append(definition.end())
        for start in sorted(set(starts)):
            while start < len(line) and line[start] in ' \t':
                start += 1
            if start >= len(line):
                continue
            if line[start] == '<':
                end = line.find('>', start + 1)
                if end != -1:
                    yield offset + start + 1, offset + end
                continue
            end, depth = start, 0
            while end < len(line):
                c = line[end]
                if c == '\\' and end + 1 < len(line):
                    end += 2
                    continue
                if c.isspace() and depth == 0:
                    break
                if c == '(':
                    depth += 1
                elif c == ')':
                    if depth == 0:
                        break
                    depth -= 1
                end += 1
            if end > start and depth == 0:
                yield offset + start, offset + end
        offset += len(line)


def rewrite_links(text: str, source: Path, destination: Path,
                  moves: dict[Path, Path] | None = None) -> str:
    replacements = []
    for start, end in link_spans(text):
        raw = text[start:end]
        if raw.startswith(('#', '?', '/')) or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', raw):
            continue
        path, suffix = re.match(r'^([^?#]*)(.*)$', raw).groups()
        if not path:
            continue
        decoded = unquote(re.sub(r'\\([\\ ()])', r'\1', path))
        target = Path(os.path.abspath(source.parent / decoded))
        new_target = relocated(target, moves or {})
        if source == destination and target == new_target:
            continue
        relative = os.path.relpath(new_target, destination.parent).replace(os.sep, '/')
        if decoded.endswith('/') and not relative.endswith('/'):
            relative += '/'
        value = quote(relative, safe='/-._~') + suffix
        if value != raw:
            replacements.append((start, end, value))
    for start, end, value in reversed(replacements):
        text = text[:start] + value + text[end:]
    return text
