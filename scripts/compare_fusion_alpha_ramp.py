"""Rebuild captured Alpha/Blend/lower-track cases through configured MCP."""
import argparse
from collections import Counter
import json
import operator
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from frameforge.engine import ffmpeg_executable
from scripts.verify_fusion_nodes import ConfiguredClient, identity


def decode(path, rgba=False, first=False):
    args = ['-frames:v', '1'] if first else []
    return subprocess.run([ffmpeg_executable(), '-v', 'error', '-i', str(path), '-an', *args,
                           '-pix_fmt', 'rgba64le' if rgba else 'rgb24', '-f', 'rawvideo', '-'],
                          capture_output=True, check=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-name', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', args.run_name): parser.error('Invalid run name')
    reference = ROOT/'research/fusion-alpha-ramp-runtime-v2.json'
    records = json.loads(reference.read_text())['records']
    status_path = ROOT/'research/fusion-alpha-ramp-status.json'
    status = json.loads(status_path.read_text())['records'][0]['case']['after']
    assert not status['rendering']
    complete = {j['id'] for j in status['jobs'] if j['status'] == {'CompletionPercentage': 100, 'JobStatus': 'Complete'}}
    assert len(records) == 13 and all(row['case']['completed'] for row in records)
    workspace = ROOT/'workspace'/('fusion-alpha-ramp-'+args.run_name)
    workspace.mkdir(exist_ok=True)
    client = ConfiguredClient(workspace)
    cases = []
    try:
        for record in records:
            native = record['case']; info = native['after']; spec = info['case']
            assert info['duration'] == 12 and info['timeline_settings'] == {'fps': 24, 'height': '360', 'width': '640'}
            assert all(j['id'] in complete for j in info['jobs'])
            client.tool('create_project', name='Alpha ramp '+spec['name'], width=640, height=360, fps=24)
            media = client.tool('import_media', path=info['source'])
            def append(track_id=None):
                return client.tool('append_clip', media_id=media['id'], out_frame=12,
                                   **({'track_id': track_id} if track_id else {}))['id']
            def bg(clip_id, **params):
                return client.tool('add_fusion_node', clip_id=clip_id, type='Background', parameters=params)['id']
            def connect(clip_id, node, port, source):
                client.tool('connect_fusion_nodes', clip_id=clip_id, target_node_id=node, input=port, source_node_id=source)
            if spec.get('lower'):
                lower = append(); generator = bg(lower, Green=1 if spec['lower'] == 'green' else 0, Alpha=1)
                connect(lower, 'MediaOut1', 'Input', generator)
                top_track = client.tool('add_track', kind='video')['id']; clip = append(top_track)
            else:
                clip = append()
            target = bg(clip, Blue=1, Alpha=spec['alpha'])
            if 'blend' in spec:
                back = 'MediaIn1' if spec['back'] == 'media' else bg(clip, Red=1, Alpha=1)
                merge = client.tool('add_fusion_node', clip_id=clip, type='Merge', parameters={'Blend': spec['blend']})['id']
                connect(clip, merge, 'Background', back); connect(clip, merge, 'Foreground', target); target = merge
            connect(clip, 'MediaOut1', 'Input', target)
            output = workspace/(spec['name']+'.mov'); checkpoint = workspace/(spec['name']+'.png')
            client.tool('render', output=str(output))
            client.tool('render_fusion_frame', clip_id=clip, frame=0, output=str(checkpoint))
            project = workspace/(spec['name']+'.json'); client.tool('save_project', path=str(project))
            native_rgb = ROOT/'workspace/fusion-alpha-ramp-native'/(native['timeline']+'_rgb.mov')
            native_rgba = native_rgb.with_name(native['timeline']+'_rgba.mov')
            a, b = decode(native_rgb), decode(output)
            assert len(a) == len(b) == 12*640*360*3
            counts = Counter(map(operator.sub, b, a)); length = len(a)
            at = (180*640+320)*3
            rgba_at = (180*640+320)*8
            result = {'name': spec['name'], 'spec': spec, 'frames': 12,
                      'native_rgb': identity(native_rgb), 'native_rgba': identity(native_rgba),
                      'independent': identity(output), 'checkpoint': identity(checkpoint), 'project': identity(project),
                      'rgb_mae': sum(abs(d)*n for d,n in counts.items())/length,
                      'rgb_mse': sum(d*d*n for d,n in counts.items())/length,
                      'native_rgb_center': list(a[at:at+3]), 'own_rgb_center': list(b[at:at+3]),
                      'native_rgba_center': list(struct.unpack_from('<4H', decode(native_rgba, True, True), rgba_at)),
                      'own_node_rgba_center': list(struct.unpack_from('<4H', decode(checkpoint, True, True), rgba_at)),
                      'node_and_native_rgba_scope_equal': not bool(spec.get('lower'))}
            cases.append(result)
            print(json.dumps({k: result[k] for k in ('name','rgb_mae','native_rgb_center','own_rgb_center','native_rgba_center','own_node_rgba_center')}), flush=True)
        report = {'status': 'measured_controlled_native_alpha_blend_and_lower_tracks', 'server': client.server_info,
                  'run_name': args.run_name, 'driver': identity(Path(__file__)), 'decoder': identity(Path(ffmpeg_executable())),
                  'reference': identity(reference), 'native_job_status': identity(status_path), 'cases': cases,
                  'production_sources': [identity(ROOT/'frameforge'/f) for f in ('fusion.py','engine.py','control.py')],
                  'limitations': ['Native exports include color and encoding; not internal node buffers.',
                                  'Generator values, static frames and two lower colors only.',
                                  'Node checkpoints exclude lower tracks, so lower-track RGBA scopes differ.'],
                  'native_equivalence_verified': False, 'full_resolve_parity': False}
        destination = ROOT/'research'/('fusion-alpha-ramp-comparison-'+args.run_name+'.json')
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n'); print(destination)
    finally:
        client.close()


if __name__ == '__main__': main()
