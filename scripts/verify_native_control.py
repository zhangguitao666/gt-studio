"""Verify configured MCP commands reach the already-open native test editor."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frame', type=int, default=24)
    parser.add_argument('--expected-project')
    args = parser.parse_args()
    if args.frame < 0:
        parser.error('--frame must be nonnegative')
    config = tomllib.loads((Path.home() / '.codex/config.toml').read_text())['mcp_servers']['frameforge']
    process = subprocess.Popen([config['command'], *config['args']], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    sequence = 0
    def request(method, params):
        nonlocal sequence
        sequence += 1
        process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': sequence, 'method': method, 'params': params}) + '\n')
        process.stdin.flush()
        reply = json.loads(process.stdout.readline())
        assert 'error' not in reply, reply
        return reply['result']
    def tool(name, **arguments):
        result = request('tools/call', {'name': name, 'arguments': arguments})
        assert not result['isError'], result
        return result['structuredContent']
    try:
        initialized = request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'native acceptance', 'version': '1'}})
        tools = request('tools/list', {})['tools']
        project = tool('get_state')
        if args.expected_project:
            assert project.get('name') == args.expected_project, project.get('name')
        before = tool('get_transport')
        assert before['ui_connected'], 'Launch GT Studio.app before this acceptance check'
        tool('set_page', page='Color')
        tool('set_playhead', frame=args.frame)
        tool('set_playback', state='playing')
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            playing = tool('get_transport')
            observed = playing['observed']
            if observed['page'] == 'Color' and observed['frame'] > args.frame and observed['playback'] == 'playing':
                break
            time.sleep(.15)
        else:
            raise AssertionError(playing)
        tool('set_playback', state='paused')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            paused = tool('get_transport')
            if paused['observed']['playback'] == 'paused' and not paused['pending']:
                break
            time.sleep(.1)
        else:
            raise AssertionError(paused)
        result = {'status': 'passed', 'configuration_launcher_verified': config['command'], 'server': initialized['serverInfo'], 'advertised_tool_count': len(tools), 'project': project.get('name'), 'requested_start_frame': args.frame, 'observed_playing': playing, 'observed_paused': paused, 'full_resolve_parity': False}
        (ROOT / 'research/native-mcp-verification.json').write_text(json.dumps(result, indent=2))
        print(json.dumps({'status': 'passed', 'tools': len(tools), 'page': paused['observed']['page'], 'frame': paused['observed']['frame'], 'playback': paused['observed']['playback']}))
    finally:
        process.terminate()
        process.communicate(timeout=5)

if __name__ == '__main__':
    main()
