"""Verify installed Fusion examples through the configured MCP launcher.

A private HTTP service/port leaves the live desktop project untouched.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from frameforge.fusion_settings import inspect_fusion_settings
from frameforge.service import Controller, EditorServer


def identity(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def main():
    workspace = ROOT / 'workspace/fusion-inspection-verification'
    workspace.mkdir(parents=True, exist_ok=True)
    base = Path('/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer')
    paths = sorted(base.glob('Fusion Templates/**/*.setting')) + [base / 'Fusion Fuse/FuseExamples.comp']
    assert len(paths) == 4
    expected = [inspect_fusion_settings(path, 'nodes', limit=100) for path in paths]
    assert sum(r['node_count'] for r in expected) == 83
    assert sum(r['connection_count'] for r in expected) == 133
    assert sum(r['unresolved_connection_count'] for r in expected) == 4
    config = tomllib.loads((Path.home() / '.codex/config.toml').read_text())['mcp_servers']['frameforge']
    server = EditorServer(('127.0.0.1', 0), Controller(workspace))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bad = workspace / 'rejected.setting'
    bad.write_text('{ Value = os.execute("must never run") }')
    calls = [('initialize', {'protocolVersion': '2025-11-25'}), ('tools/list', {}),
             ('tools/call', {'name': 'get_state', 'arguments': {}})]
    for path in paths:
        calls.append(('tools/call', {'name': 'inspect_fusion_settings', 'arguments': {'path': str(path)}}))
        calls.append(('tools/call', {'name': 'inspect_fusion_settings', 'arguments': {'path': str(path), 'detail': 'nodes', 'limit': 100}}))
    calls.extend([('tools/call', {'name': 'inspect_fusion_settings', 'arguments': {'path': str(bad)}}),
                  ('tools/call', {'name': 'get_state', 'arguments': {}})])
    command = [config['command'], *config.get('args', []), '--port', str(server.server_port), '--workspace', str(workspace)]
    try:
        process = subprocess.run(command, input=''.join(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params}) + '\n' for i, (method, params) in enumerate(calls)),
                                 capture_output=True, text=True, timeout=30, check=True)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)
    replies = [json.loads(line)['result'] for line in process.stdout.splitlines()]
    assert len(replies) == len(calls)
    tool = next(t for t in replies[1]['tools'] if t['name'] == 'inspect_fusion_settings')
    assert tool['annotations']['readOnlyHint'] is True
    assert replies[2]['structuredContent'] == replies[-1]['structuredContent'] == {'project': None}
    assert replies[-2]['isError'] is True
    observations = []
    for index, path in enumerate(paths):
        summary, full = replies[3 + index * 2:5 + index * 2]
        assert not summary['isError'] and not full['isError']
        assert full['structuredContent'] == expected[index]
        assert 'nodes' not in summary['structuredContent']
        observations.append({'artifact': identity(path), 'summary': summary['structuredContent'], 'nodes': full['structuredContent']})
    helper = Path('/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fuscript')
    help_run = subprocess.run([str(helper), '-h'], capture_output=True, text=True, timeout=10)
    report = {'status': 'passed_configured_mcp_fusion_literal_inspection',
              'server': replies[0]['serverInfo'], 'tool_count': len(replies[1]['tools']),
              'launcher': {'command': config['command'], 'args': config.get('args', []), 'isolation': 'private test service and port overrides'},
              'artifacts': observations, 'rejected_executable_syntax': replies[-2], 'project_unchanged': True,
              'fuscript': {**identity(helper), 'probe_args': ['-h'], 'exit': help_run.returncode, 'stdout': help_run.stdout, 'stderr': help_run.stderr,
                           'interpretation': 'Banner-only CLI invocation; no usable composition API or render execution has been established.'},
              'rea_bundle': identity(ROOT / 'research/evidence/fuscript-macho-rea.json'),
              'implementation': [identity(ROOT / p) for p in ['frameforge/fusion_settings.py', 'frameforge/control.py', 'frameforge/engine.py', 'frameforge/mcp.py']],
              'native_node_execution_verified': False, 'native_window_verification': 'pending', 'full_resolve_parity': False}
    out = ROOT / 'research/fusion-settings-verification.json'
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'report': str(out), 'tools': report['tool_count'], 'nodes': 83, 'connections': 133, 'status': report['status']}))


if __name__ == '__main__':
    main()
