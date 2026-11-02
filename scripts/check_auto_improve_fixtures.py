#!/usr/bin/env python3
"""Static helper fixtures only. No model, setup skill or real project is run."""
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / 'skills/agent-setup/scripts/check_auto_improve.py'
    spec = importlib.util.spec_from_file_location('check_auto_improve', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    asset = (root / 'skills/agent-setup/assets/templates/auto-improve.template.md').read_text()
    rows = []
    with tempfile.TemporaryDirectory(prefix='auto-improve-static-') as temp:
        base = Path(temp)
        cases = [
            ('codex-direct', '[auto-improve](.agents/skills/auto-improve/SKILL.md)', asset, True),
            ('missing-installed-skill', 'V15 (auto-improve) выбрана; сопровождение описано.', None, False),
            ('bare-mention', 'Установлен .agents/skills/auto-improve/SKILL.md', asset, False),
            ('code-example-only', '```md\n[skill](.agents/skills/auto-improve/SKILL.md)\n```', asset, False),
            ('wrong-native-name', '[skill](.agents/skills/auto-improve/SKILL.md)', asset.replace('name: auto-improve', 'name: other'), False),
            ('empty-description', '[skill](.agents/skills/auto-improve/SKILL.md)', asset.replace(next(x for x in asset.splitlines() if x.startswith('description:')), 'description:'), False),
            ('moved-map-broken-outgoing', '[карта](setup/WORKSPACE.md)', asset, False),
            ('moved-map-recalculated', '[карта](setup/WORKSPACE.md)', asset, True),
        ]
        for name, entry, body, expected in cases:
            project = base / name
            project.mkdir()
            (project / 'AGENTS.md').write_text(entry)
            if body is not None:
                path = project / '.agents/skills/auto-improve/SKILL.md'
                path.parent.mkdir(parents=True)
                path.write_text(body)
            if name.startswith('moved-map-'):
                (project / 'setup').mkdir()
                prefix = '../' if name.endswith('recalculated') else ''
                (project / 'setup/WORKSPACE.md').write_text('[skill](' + prefix + '.agents/skills/auto-improve/SKILL.md)')
            before = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob('*') if p.is_file()}
            result = module.check(project)
            after = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob('*') if p.is_file()}
            ok = (result['status'] == 'pass') == expected and before == after
            rows.append({'case': name, 'expected': 'pass' if expected else 'fail', 'actual': result['status'], 'filesUnchanged': before == after, 'pass': ok})
        project = base / 'claude-delivery'
        path = project / '.agents/skills/auto-improve/SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text(asset)
        (project / '.claude/skills').mkdir(parents=True)
        (project / '.claude/skills/auto-improve').symlink_to('../../.agents/skills/auto-improve', target_is_directory=True)
        (project / 'CLAUDE.md').write_text('[skill](.claude/skills/auto-improve/SKILL.md)')
        result = module.check(project, 'CLAUDE.md', '.claude/skills/auto-improve/SKILL.md')
        rows.append({'case': 'claude-delivery', 'expected': 'pass', 'actual': result['status'], 'pass': result['status'] == 'pass'})
        try:
            module.check(project, 'CLAUDE.md', '../outside.md')
            rejected = False
        except ValueError:
            rejected = True
        rows.append({'case': 'outside-project-rejected', 'pass': rejected})
        project = base / 'project with spaces'
        path = project / '.agents/skills/auto-improve/SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text(asset)
        (project / 'AGENTS.md').write_text('[skill](.agents/skills/auto-improve/SKILL.md)')
        for name, entry, expected in [('cli-with-spaces', 'AGENTS.md', 0), ('cli-missing-entry', 'absent.md', 1)]:
            run = subprocess.run([sys.executable, '-B', str(source), '--root', str(project), '--entry', entry], capture_output=True, text=True)
            result = json.loads(run.stdout)
            rows.append({'case': name, 'expectedExit': expected, 'actualExit': run.returncode, 'pass': run.returncode == expected and result['behavior'] == 'not-run'})
    print(json.dumps({'scope': 'static fixtures; no model/skill execution', 'cases': rows, 'status': 'pass' if all(x['pass'] for x in rows) else 'fail'}, ensure_ascii=False, indent=2))
    return int(not all(x['pass'] for x in rows))


if __name__ == '__main__':
    raise SystemExit(main())
