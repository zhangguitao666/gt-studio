"""Compare native probe timing readbacks with actual independent MCP mutations."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from frameforge.service import Controller, EditorServer


def main():
    evidence = ROOT / 'research/retime-runtime-v2.json'
    freeze_evidence = ROOT / 'research/freeze-all-runtime-v3.json'
    cases = [r['case'] for r in json.loads(evidence.read_text())['records']]
    cases += [r['case'] for r in json.loads(freeze_evidence.read_text())['records']
              if r['case']['timeline'].startswith('REA_FREEZE') and 'all' in r['case']['after']]
    assert len(cases) == 10
    source = ROOT / 'workspace/demo-media/motion.mp4'
    workspace = ROOT / 'workspace/reference-retime-comparison'
    server = EditorServer(('127.0.0.1', 0), Controller(workspace))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    process = subprocess.Popen([sys.executable, str(ROOT / 'frameforge_entry.py'), 'mcp',
                                '--workspace', str(workspace), '--port', str(server.server_port)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    sequence = 0

    def request(method, params):
        nonlocal sequence
        sequence += 1
        process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': sequence, 'method': method, 'params': params}) + '\n')
        process.stdin.flush()
        line = process.stdout.readline()
        assert line, 'MCP process returned no response'
        response = json.loads(line)
        assert 'error' not in response, response
        return response['result']

    def tool(action, **params):
        result = request('tools/call', {'name': action, 'arguments': params})
        assert not result['isError'], result
        return result['structuredContent']

    observations = []
    try:
        request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                               'clientInfo': {'name': 'native retime comparison', 'version': '1'}})
        for case in cases:
            assert case['completed'] and case['set_speed']['value'] is True
            tool('create_project', name=case['timeline'], width=320, height=180, fps=24)
            media = tool('import_media', path=str(source))
            first = tool('append_clip', media_id=media['id'], in_frame=0, out_frame=47, start_frame=0)
            tool('append_clip', media_id=media['id'], in_frame=0, out_frame=47, start_frame=47)
            params = {'clip_id': first['id'], 'percentage': case['percentage'], 'ripple': case['ripple']}
            if 'seek_frame' in case:
                tool('set_playhead', frame=case['seek_frame'])
            tool('set_clip_speed', **params)
            state = tool('get_state')
            clips = state['timelines'][0]['tracks'][0]['clips']
            actual = [{'start': c['start_frame'], 'duration': c['duration_frames'], 'percentage': c['speed_percentage']}
                      for c in sorted(clips, key=lambda c: c['start_frame'])]
            native = case['after'].get('all', [case['after']['first'], case['after']['second']])
            origin = case['before']['first']['start']
            expected = [{'start': c['start'] - origin, 'duration': c['duration'], 'percentage': c['speed']['Percentage']}
                        for c in native]
            # The first older default-playhead freeze froze source46 instead of0;
            # timing alone matches. Source sampling is deliberately not compared.
            observations.append({'native_timeline': case['timeline'], 'parameters': params,
                                 'native': expected, 'independent': actual, 'timing_match': actual == expected})
        result = {'status': 'passed' if all(r['timing_match'] for r in observations) else 'failed',
                  'comparison_scope': 'Video clip count, timeline start/duration and speed percentage for ten captured cases, exercised through stdio MCP.',
                  'source': {'path': str(source), 'sha256_at_comparison': hashlib.sha256(source.read_bytes()).hexdigest()},
                  'native_evidence': [str(evidence), str(freeze_evidence)], 'cases': observations,
                  'limitations': ['No original-vs-independent decoded frame/audio comparison in this check.',
                                  'Native and internal source-boundary conventions are not equated.',
                                  'Linked native audio items and other tracks are outside this comparison.',
                                  'Out-of-clip playhead freeze behavior remains unverified.'],
                  'full_resolve_parity': False}
        (ROOT / 'research/reference-retime-comparison.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'status': result['status'], 'matched': sum(r['timing_match'] for r in observations), 'cases': len(observations)}))
        assert result['status'] == 'passed', 'Inspect research/reference-retime-comparison.json'
    finally:
        process.terminate()
        process.communicate(timeout=5)
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == '__main__':
    main()
