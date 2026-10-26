"""Replay measured native gain/overload cases using configured stdio MCP."""
import argparse
import array
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_fusion_nodes import ConfiguredClient, identity
from frameforge.engine import ffmpeg_executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-name', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', args.run_name):
        parser.error('Invalid run name')
    fixture = ROOT/'tests/fixtures/audio-gain.json'
    reference = json.loads(fixture.read_text())
    statuses = json.loads((ROOT/'research/audio-gain-status.json').read_text())
    jobs = {j['id']: j['status'] for r in statuses['records']
            if r['case']['after'].get('audio_gain_status')
            for j in r['case']['after']['jobs']}
    workspace = ROOT/'workspace'/('audio-gain-comparison-'+args.run_name)
    workspace.mkdir(exist_ok=True)
    client = ConfiguredClient(workspace)
    results = []
    try:
        tools = client.request('tools/list', {})['tools']
        for case in reference['cases']:
            assert jobs[case['job_id']]['JobStatus'] == 'Complete'
            client.tool('create_project', name='Native gain '+case['name'],
                        width=16, height=16, fps=24, sample_rate=48000)
            media = {name: client.tool('import_media', path=str(
                ROOT/'workspace/audio-gain-native'/(name+'.wav')))
                for name in sorted({i['source'] for i in case['items']})}
            state = client.tool('get_state')
            tracks = [t for t in state['timelines'][0]['tracks'] if t['kind']=='audio']
            while len(tracks) < max(i['track'] for i in case['items']):
                tracks.append(client.tool('add_track', kind='audio'))
            for item in case['items']:
                clip = client.tool('append_clip', media_id=media[item['source']]['id'],
                    track_id=tracks[item['track']-1]['id'], in_frame=0, out_frame=48,
                    start_frame=item['start'])
                client.tool('set_clip_properties', clip_id=clip['id'],
                            properties={'volume': 10**(item['gain']/20)})
            project = workspace/(case['name']+'.json')
            client.tool('save_project', path=str(project))
            client.tool('open_project', path=str(project))
            output = workspace/(case['name']+'.mov')
            client.tool('render', output=str(output))
            own = subprocess.check_output([ffmpeg_executable(), '-v', 'error',
                '-i', str(output), '-vn', '-c:a', 'pcm_s32le', '-f', 's32le', '-'])
            native = zlib.decompress(base64.b64decode(case['native_pcm_s32le_zlib']))
            assert hashlib.sha256(native).hexdigest()==case['native_pcm_s32le_sha256']
            a, b = array.array('i'), array.array('i')
            a.frombytes(native); b.frombytes(own)
            result = {'name': case['name'], 'native_job': case['job_id'],
                'native_status': jobs[case['job_id']], 'pcm_exact': own==native,
                'native_bytes': len(native), 'own_bytes': len(own),
                'changed_scalars': sum(x!=y for x,y in zip(a,b)),
                'max_delta': max((abs(x-y) for x,y in zip(a,b)), default=0),
                'native_pcm_sha256': hashlib.sha256(native).hexdigest(),
                'own_pcm_sha256': hashlib.sha256(own).hexdigest(),
                'output': identity(output), 'project': identity(project)}
            results.append(result)
            print(json.dumps({k: result[k] for k in ('name','pcm_exact','changed_scalars','max_delta')}), flush=True)
        report = {'fixture': identity(fixture), 'driver': identity(Path(__file__)),
            'production': identity(ROOT/'frameforge/engine.py'),
            'server': client.server_info, 'public_tools': len(tools),
            'cases': results, 'calls': client.calls, 'full_resolve_parity': False,
            'limits': [reference['scope'],
                'Native audio-only MOV versus independent black-video MOV: PCM equality is not container parity.',
                'No claim about configured compressors, limiters, plugins, buses, resampling or AAC overload behavior.']}
        target = ROOT/'research'/('audio-gain-comparison-'+args.run_name+'.json')
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        assert len(results)==8 and all(r['pcm_exact'] for r in results)
    finally:
        client.close()


if __name__=='__main__':
    main()
