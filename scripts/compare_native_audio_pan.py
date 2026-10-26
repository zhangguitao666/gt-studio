"""Replay measured native pan cases using configured stdio MCP."""
import argparse
import array
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import struct
import wave
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_fusion_nodes import ConfiguredClient, identity
from frameforge.engine import ffmpeg_executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-name', required=True)
    parser.add_argument('--fixture', type=Path, default=ROOT/'research/audio-pan-fixtures.json')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', args.run_name):
        parser.error('Invalid run name')
    fixture = args.fixture.resolve()
    reference = json.loads(fixture.read_text())
    assert reference.get('sample_rate', 48000) == 48000
    jobs = {c['job']: c['native_status'] for c in reference['cases']}
    workspace = ROOT/'workspace'/('audio-pan-comparison-'+args.run_name)
    workspace.mkdir(exist_ok=True)
    client = ConfiguredClient(workspace)
    results = []
    try:
        tools = client.request('tools/list', {})['tools']
        pan_tool = next(t for t in tools if t['name']=='set_clip_properties')
        assert 'pan' in pan_tool['inputSchema']['properties']['properties']['properties']
        measured = [c for c in reference['cases'] if c['bits']==24]
        assert measured
        for case in measured:
            assert jobs[case['job']]['JobStatus'] == 'Complete'
            client.tool('create_project', name='Native pan '+case['name'],
                        width=16, height=16, fps=24, sample_rate=48000)
            source = workspace/(case['source']+'.wav')
            values = reference['sources'][case['source']]
            if isinstance(values, dict):
                assert values['sample_rate'] == 48000 and values['frames'] == 96000
                raw = zlib.decompress(base64.b64decode(values['pcm_s16le_zlib']))
                assert hashlib.sha256(raw).hexdigest() == values['pcm_s16le_sha256']
                channels = values['channels']
                assert len(raw) == channels*2*96000
            else:
                channels = len(values)
                raw = struct.pack('<'+'h'*channels, *values)*96000
            with wave.open(str(source), 'wb') as wav:
                wav.setparams((channels, 2, 48000, 96000, 'NONE', 'not compressed'))
                wav.writeframes(raw)
            media = client.tool('import_media', path=str(source))
            state = client.tool('get_state')
            track = next(t for t in state['timelines'][0]['tracks'] if t['kind']=='audio')
            clip = client.tool('append_clip', media_id=media['id'], track_id=track['id'], in_frame=0, out_frame=48)
            client.tool('set_clip_properties', clip_id=clip['id'], properties={'pan': case['pan']})
            project = workspace/(case['name']+'.json')
            client.tool('save_project', path=str(project))
            client.tool('open_project', path=str(project))
            output = workspace/(case['name']+'.mov')
            client.tool('render', output=str(output))
            own = subprocess.check_output([ffmpeg_executable(), '-v', 'error',
                '-i', str(output), '-vn', '-c:a', 'pcm_s32le', '-f', 's32le', '-'])
            native = zlib.decompress(base64.b64decode(case['pcm_s32le_zlib']))
            assert hashlib.sha256(native).hexdigest()==case['pcm_s32le_sha256']
            a, b = array.array('i'), array.array('i')
            a.frombytes(native); b.frombytes(own)
            result = {'name': case['name'], 'native_job': case['job'],
                'native_status': jobs[case['job']], 'pcm_exact': own==native,
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
            'pan_model': identity(ROOT/'frameforge/audio_pan.py'),
            'server': client.server_info, 'public_tools': len(tools),
            'cases': results, 'calls': client.calls, 'full_resolve_parity': False,
            'limits': [reference['scope'],
                'Native audio-only MOV versus independent black-video MOV: PCM equality is not container parity.',
                '48kHz/default bus and selected static pan values/sources only; automation, explicit fades, offsets and actual desktop acceptance require separate evidence.']}
        target = ROOT/'research'/('audio-pan-comparison-'+args.run_name+'.json')
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        assert len(results)==len(measured) and all(r['pcm_exact'] for r in results)
    finally:
        client.close()


if __name__=='__main__':
    main()
