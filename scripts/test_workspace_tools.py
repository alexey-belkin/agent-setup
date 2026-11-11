"""Filesystem regressions for delivered CLIs; no skill/model/setup execution."""
from pathlib import Path
from unittest import mock
import contextlib
import importlib
import io
import json
import shutil
import sys
import tempfile
import unittest

import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/agent-setup/scripts'
sys.path.insert(0, str(SCRIPTS))
move = importlib.import_module('move_artifacts')
registry = importlib.import_module('build_registries')


class ToolsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, content):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))
        return p

    def invoke(self, module, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = module.main(['--root', str(self.root), *args])
        return code, out.getvalue()

    def config(self, name='docs/registry.yaml', **extra):
        spec = {'version': 1, 'title': 'Registry', 'tables': [{
            'include': ['**/*.md'], 'exclude': ['README.md'],
            'columns': [{'label': 'Document', 'field': 'title', 'link': True, 'required': True},
                        {'label': 'Status', 'field': 'status'},
                        {'label': 'Summary', 'field': 'registry.summary'}]}]}
        spec.update(extra)
        return self.write(name, yaml.safe_dump(spec, allow_unicode=True))

    def test_move_preview_then_incoming_outgoing_and_reference_links(self):
        src = self.write('notes/a.md', '[b](../b.md#part "title")\n[ref]: ../b.md\n')
        self.write('b.md', '# B\n')
        ref = self.write('AGENTS.md', '[a](notes/a.md?q=1#here)\n![image](notes/a.md)\n')
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(self.invoke(move, '--move', 'notes/a.md', 'guides/deep/a.md')[0], 0)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertTrue(src.exists())
        self.assertEqual(self.invoke(move, '--move', 'notes/a.md', 'guides/deep/a.md', '--apply')[0], 0)
        self.assertFalse(src.exists())
        self.assertIn('../../b.md#part "title"', (self.root / 'guides/deep/a.md').read_text())
        self.assertIn('[ref]: ../../b.md', (self.root / 'guides/deep/a.md').read_text())
        self.assertIn('guides/deep/a.md?q=1#here', ref.read_text())

    def test_unicode_spaces_angles_balanced_paths_and_code_occurrence(self):
        self.write('old/a (1).md', '# one')
        ref = self.write('r.md', '`[x](old/a%20%281%29.md)`\n[x](<old/a (1).md> "t")\n[y](old/a(2).md)\n~~~md\n[x](old/a%20%281%29.md)\n~~~\n')
        self.assertEqual(self.invoke(move, '--move', 'old/a (1).md', 'новое/a.md', '--apply')[0], 0)
        text = ref.read_text()
        self.assertIn('[x](<%D0%BD%D0%BE%D0%B2%D0%BE%D0%B5/a.md> "t")', text)
        self.assertIn('`[x](old/a%20%281%29.md)`', text)
        self.assertIn('~~~md\n[x](old/a%20%281%29.md)', text)
        self.assertIn('[y](old/a(2).md)', text)

    def test_directory_and_two_files_move_internal_and_external_links(self):
        self.write('area/a.md', '[b](b.md) [outside](../out.md)')
        self.write('area/b.md', '# B')
        self.write('out.md', '[a](area/a.md)')
        self.assertEqual(self.invoke(move, '--move', 'area', 'nested/area', '--move', 'out.md', 'other/out.md', '--apply')[0], 0)
        self.assertEqual((self.root / 'nested/area/a.md').read_text(), '[b](b.md) [outside](../../other/out.md)')
        self.assertIn('../nested/area/a.md', (self.root / 'other/out.md').read_text())

    def test_collisions_escape_and_overlapping_rejected_without_writes(self):
        self.write('a.md', 'A')
        self.write('b.md', 'B')
        for args in [('--move', 'a.md', 'b.md'), ('--move', 'a.md', '../outside.md'),
                     ('--move', 'a.md', 'new/a.md', '--move', 'a.md', 'other/a.md')]:
            self.assertEqual(self.invoke(move, *args, '--apply')[0], 2)
        self.assertEqual((self.root / 'a.md').read_text(), 'A')
        self.assertEqual((self.root / 'b.md').read_text(), 'B')

    def test_symlink_and_nested_repository_not_moved_or_followed(self):
        self.write('real/a.md', '# A')
        (self.root / 'alias').symlink_to(self.root / 'real', target_is_directory=True)
        self.assertEqual(self.invoke(move, '--move', 'alias/a.md', 'new.md', '--apply')[0], 2)
        self.write('repo/.git/config', '')
        self.write('repo/a.md', '')
        self.assertEqual(self.invoke(move, '--move', 'repo', 'next', '--apply')[0], 2)

    def test_config_consumers_reported_and_apply_blocked_until_acknowledged(self):
        self.write('docs/a.md', '# A')
        self.write('docs/registry.yaml', 'path: a.md\n')
        code, text = self.invoke(move, '--move', 'docs/a.md', 'docs/b.md', '--apply')
        self.assertEqual(code, 2)
        self.assertIn('UNHANDLED', text)
        self.assertTrue((self.root / 'docs/a.md').exists())
        self.assertEqual(self.invoke(move, '--move', 'docs/a.md', 'docs/b.md', '--apply', '--allow-unhandled')[0], 0)
        self.assertEqual((self.root / 'docs/registry.yaml').read_text(), 'path: a.md\n')

    def test_excluded_docs_are_not_changed_and_excluded_sources_refused(self):
        self.write('a.md', '# A')
        excluded = self.write('archive/ref.md', '[a](../a.md)')
        self.assertEqual(self.invoke(move, '--move', 'a.md', 'b.md', '--exclude', 'archive', '--apply')[0], 0)
        self.assertEqual(excluded.read_text(), '[a](../a.md)')
        self.assertEqual(self.invoke(move, '--move', 'archive/ref.md', 'ref.md', '--exclude', 'archive', '--apply')[0], 2)

    def test_move_io_failure_rolls_back_renames_and_edits(self):
        self.write('a.md', '[z](z.md)')
        ref = self.write('ref.md', '[a](a.md)')
        moves, edits, _ = move.plan(self.root, [['a.md', 'deep/a.md']], [])
        original = Path.write_bytes
        calls = 0
        def fail_once(path, content):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError('simulated failure')
            return original(path, content)
        with mock.patch.object(Path, 'write_bytes', fail_once):
            with self.assertRaises(OSError):
                move.apply_plan(self.root, moves, edits)
        self.assertEqual((self.root / 'a.md').read_text(), '[z](z.md)')
        self.assertEqual(ref.read_text(), '[a](a.md)')
        self.assertFalse((self.root / 'deep').exists())

    def test_move_plan_detects_concurrent_edit(self):
        self.write('a.md', '[b](b.md)')
        moves, edits, _ = move.plan(self.root, [['a.md', 'deep/a.md']], [])
        self.write('a.md', 'user edit')
        with self.assertRaises(move.MoveError):
            move.apply_plan(self.root, moves, edits)
        self.assertTrue((self.root / 'a.md').exists())

    def test_registry_preview_check_apply_and_metadata_updates(self):
        self.config()
        p = self.write('docs/a.md', '---\ntitle: One\nstatus: draft\nregistry:\n  summary: Meaning\n---\n# Ignored')
        output = self.root / 'docs/REGISTRY.md'
        self.assertEqual(self.invoke(registry)[0], 0)
        self.assertFalse(output.exists())
        self.assertEqual(self.invoke(registry, '--check')[0], 1)
        self.assertFalse(output.exists())
        self.assertEqual(self.invoke(registry, '--apply')[0], 0)
        before = output.read_bytes()
        self.assertEqual(self.invoke(registry, '--check')[0], 0)
        self.assertEqual(self.invoke(registry, '--apply')[0], 0)
        self.assertEqual(before, output.read_bytes())
        p.write_text(p.read_text().replace('One', 'Two').replace('draft', 'done'))
        self.assertEqual(self.invoke(registry, '--check')[0], 1)
        self.assertEqual(output.read_bytes(), before)
        self.assertEqual(self.invoke(registry, '--apply')[0], 0)
        self.assertIn('[Two](a.md) | done | Meaning', output.read_text())
        p.unlink()
        self.assertEqual(self.invoke(registry, '--apply')[0], 0)
        self.assertNotIn('a.md', output.read_text())

    def test_registry_preserves_readme_bytes_outside_block(self):
        self.config(output='README.md', section=True)
        self.write('docs/a.md', '# A')
        manual = b'Human\r\n<!-- registry:start -->\r\nold\r\n<!-- registry:end -->\r\nFooter\r\n'
        output = self.write('docs/README.md', manual)
        self.assertEqual(self.invoke(registry, '--apply')[0], 0)
        actual = output.read_bytes()
        self.assertTrue(actual.startswith(b'Human\r\n<!-- registry:start -->'))
        self.assertTrue(actual.endswith(b'<!-- registry:end -->\r\nFooter\r\n'))
        self.assertEqual(self.invoke(registry, '--check')[0], 0)

    def test_registry_refuses_manual_file_and_malformed_markers(self):
        self.config()
        manual = self.write('docs/REGISTRY.md', '# Manual knowledge')
        self.assertEqual(self.invoke(registry, '--apply')[0], 2)
        self.assertEqual(manual.read_text(), '# Manual knowledge')
        self.config(output='README.md', section=True)
        self.write('docs/README.md', '<!-- registry:end -->\n<!-- registry:start -->')
        self.assertEqual(self.invoke(registry, '--apply')[0], 2)

    def test_registry_validates_all_before_write(self):
        self.config('a/registry.yaml')
        self.write('a/a.md', '# A')
        self.config('b/registry.yaml')
        self.write('b/b.md', 'no title')
        self.assertEqual(self.invoke(registry, '--apply')[0], 2)
        self.assertFalse((self.root / 'a/REGISTRY.md').exists())

    def test_registry_duplicate_yaml_and_missing_records_are_errors(self):
        self.write('registry.yaml', 'version: 1\nversion: 1\ntitle: X\ntables: []')
        self.assertEqual(self.invoke(registry, '--apply')[0], 2)
        self.config('registry.yaml', tables=[{'records': [{'path': 'missing.bin'}], 'columns': [{'label': 'File', 'field': 'name'}]}])
        self.assertEqual(self.invoke(registry, '--apply')[0], 2)

    def test_registry_rebases_metadata_links_and_explicit_non_markdown_records(self):
        self.config(output='../REGISTRY.md', tables=[{'include': ['sub/*.md'], 'records': [{'path': 'tool.py', 'title': 'Utility'}],
          'columns': [{'label': 'File', 'field': 'title', 'link': True}, {'label': 'Info', 'field': 'registry.summary'}]}])
        self.write('docs/sub/a.md', '---\ntitle: Doc\nregistry:\n  summary: \'[B](../b.md#ok "t")\'\n---')
        self.write('docs/b.md', '# B')
        self.write('docs/tool.py', '# sample')
        self.assertEqual(self.invoke(registry, '--apply')[0], 0)
        text = (self.root / 'REGISTRY.md').read_text()
        self.assertIn('[Doc](docs/sub/a.md)', text)
        self.assertIn('[B](docs/b.md#ok "t")', text)
        self.assertIn('[Utility](docs/tool.py)', text)

    def test_registry_output_escape_and_symlink_rejected(self):
        self.config(output='../../escape.md')
        self.write('docs/a.md', '# A')
        self.assertEqual(self.invoke(registry, '--apply')[0], 2)
        self.config()
        self.write('actual.md', '# manual')
        (self.root / 'docs/REGISTRY.md').symlink_to(self.root / 'actual.md')
        self.assertEqual(self.invoke(registry, '--apply')[0], 2)

    def test_registry_records_conflicts_and_archives(self):
        self.config(tables=[{'records': [{'path': 'a.md', 'title': 'Wrong'}], 'columns': [{'label': 'Title', 'field': 'title'}]}])
        self.write('docs/a.md', '---\ntitle: Canon\n---')
        self.assertEqual(self.invoke(registry, '--apply')[0], 2)
        self.config()
        self.write('archive/registry.yaml', 'invalid')
        self.assertEqual(self.invoke(registry, '--apply')[0], 0)

    def test_copied_scripts_run_as_clis_without_original_checkout(self):
        import subprocess
        installed = self.root / 'scripts'
        installed.mkdir()
        for name in ['workspace_paths.py', 'move_artifacts.py', 'build_registries.py']:
            shutil.copyfile(SCRIPTS / name, installed / name)
        self.config()
        self.write('docs/a.md', '# A')
        for script, arguments in [('build_registries.py', ['--apply']),
                                  ('move_artifacts.py', ['--move', 'docs/a.md', 'docs/b.md', '--apply']),
                                  ('build_registries.py', ['--check'])]:
            result = subprocess.run([sys.executable, '-B', str(installed / script), '--root', str(self.root), *arguments],
                                    cwd=self.temp.name, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_registry_invalid_schema_and_duplicate_outputs_do_not_write(self):
        self.config(tables=[{'include': '*.md', 'columns': [{'label': 'X', 'field': 'title'}]}])
        self.write('docs/a.md', '# A')
        self.assertEqual(self.invoke(registry, '--apply')[0], 2)
        self.assertFalse((self.root / 'docs/REGISTRY.md').exists())
        self.config('a/registry.yaml', output='../REGISTRY.md')
        self.config('b/registry.yaml', output='../REGISTRY.md')
        self.assertEqual(self.invoke(registry, '--config', 'a/registry.yaml', '--config', 'b/registry.yaml', '--apply')[0], 2)
        self.assertFalse((self.root / 'REGISTRY.md').exists())

    def test_registry_write_failure_restores_prior_outputs(self):
        self.config('a/registry.yaml')
        self.config('b/registry.yaml')
        self.write('a/a.md', '# A')
        self.write('b/b.md', '# B')
        original = registry.atomic_write
        calls = 0
        def fail_once(path, text):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('simulated failure')
            return original(path, text)
        with mock.patch.object(registry, 'atomic_write', fail_once):
            self.assertEqual(self.invoke(registry, '--apply')[0], 2)
        self.assertFalse((self.root / 'a/REGISTRY.md').exists())
        self.assertFalse((self.root / 'b/REGISTRY.md').exists())

    def test_move_then_regenerate_registry_and_check(self):
        self.config()
        self.write('docs/a.md', '# Artifact')
        self.assertEqual(self.invoke(registry, '--apply')[0], 0)
        self.assertEqual(self.invoke(move, '--move', 'docs/a.md', 'docs/sub/a.md', '--apply')[0], 0)
        self.assertEqual(self.invoke(registry, '--check')[0], 0)
        self.assertIn('sub/a.md', (self.root / 'docs/REGISTRY.md').read_text())


if __name__ == '__main__':
    unittest.main()
