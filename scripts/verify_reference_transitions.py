"""Replay native transition cases through MCP and retain actual media samples."""
import argparse
import re
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from frameforge.engine import ffmpeg_executable
from scripts.compare_native_retime_media import MCPProjectClient


def identity(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}


def sample_pixels(path):
    raw = subprocess.run([ffmpeg_executable(), '-v', 'error', '-i', str(path), '-vf',
                          'crop=2:2:320:180,scale=1:1', '-an', '-pix_fmt', 'rgb24',
                          '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout
    assert len(raw) % 3 == 0
    return [list(raw[i:i + 3]) for i in range(0, len(raw), 3)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-name')
    args=parser.parse_args()
    if args.run_name and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',args.run_name):parser.error('Invalid run name')
    suffix='-'+args.run_name if args.run_name else ''
    evidence = ROOT / 'research/transition-runtime-v1.json'
    records = json.loads(evidence.read_text())['records']
    assert len(records) == 6
    workspace = ROOT / 'workspace' / ('transition-acceptance'+suffix)
    workspace.mkdir(parents=True, exist_ok=True)
    client = MCPProjectClient(workspace)
    observations = []
    try:
        for record in records:
            case = record['case']
            client.tool('create_project', name=case['timeline'], width=640, height=360, fps=24)
            clips = []
            duration = case['out_frame'] - case['in_frame']
            for i, color in enumerate(('red', 'blue')):
                media = client.tool('import_media', path=str(ROOT / 'workspace/transition-reference' / (color + '.mp4')))
                clips.append(client.tool('append_clip', media_id=media['id'], in_frame=case['in_frame'],
                                         out_frame=case['out_frame'], start_frame=i * duration))
            target = clips[1] if case['position'] == 'start' else clips[0]
            arguments = {'clip_id': target['id'], 'position': case['position'],
                         'duration_frames': case['duration'], 'alignment': case['alignment']}
            before = client.tool('get_state')
            reply = client.request('tools/call', {'name': 'add_transition', 'arguments': arguments})
            native_accepted = case['after']['add_returned_item']
            assert bool(reply['isError']) != native_accepted, reply
            if native_accepted:
                transition = reply['structuredContent']
                original = case['after']['transition']
                origin = case['before']['origin']
                assert transition['start_frame'] == original['start'] - origin
                assert transition['end_frame'] == original['finish'] - origin
                assert transition['duration_frames'] == original['duration']
            else:
                transition = None
                assert client.tool('get_state') == before, 'Rejected transition changed project'
            project = workspace / (case['timeline'] + '.json')
            client.tool('save_project', path=str(project))
            state = client.tool('get_state')
            positions = [(c['start_frame'], c['duration_frames']) for c in state['timelines'][0]['tracks'][0]['clips']]
            assert positions == [(0, duration), (duration, duration)]
            output = workspace / (case['timeline'] + '.mov')
            client.tool('render', output=str(output), format='mov')
            native = ROOT / 'workspace/transition-reference/native-v1' / output.name
            native_pixels, own_pixels = sample_pixels(native), sample_pixels(output)
            assert len(native_pixels) == len(own_pixels) == 2 * duration
            if transition:
                start, finish = transition['start_frame'], transition['end_frame']
                assert all(p[0] > 0 and p[2] > 0 for p in own_pixels[start:finish]), 'No real RGB dissolve'
                client.tool('delete_transition', transition_id=transition['id'])
                assert not client.tool('get_state')['timelines'][0].get('transitions')
                client.tool('undo')
                assert client.tool('get_state')['timelines'][0]['transitions'][0]['id'] == transition['id']
            observations.append({'timeline': case['timeline'], 'native_accepted': native_accepted,
                                 'independent_accepted': not reply['isError'], 'transition': transition,
                                 'project': identity(project), 'native_output': identity(native),
                                 'independent_output': identity(output), 'frames': len(own_pixels),
                                 'native_center_pixels': native_pixels, 'independent_center_pixels': own_pixels,
                                 'exact_sampled_pixels': native_pixels == own_pixels})
        result = {'status': 'structural_checks_passed_and_media_measured', 'cases': observations,
                  'native_evidence': identity(evidence),
                  'advertised_tool_count': len(client.request('tools/list', {})['tools']),
                  'limitations': ['Media samples cover a center ROI, not all pixels or fonts.',
                                  'Pixel values are measured and not declared equivalent.',
                                  'Video Cross Dissolve only; full transition registry and linked A/V semantics remain open.'],
                  'full_resolve_parity': False}
        (ROOT / 'research' / ('reference-transition-comparison'+suffix+'.json')).write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'status': result['status'], 'cases': len(observations), 'tools': result['advertised_tool_count']}))
    finally:
        client.close()


if __name__ == '__main__':
    main()
