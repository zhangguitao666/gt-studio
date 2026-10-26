"""Replay captured default transform chains through configured stdio MCP.

Checks the native identity-restoration relationships, separately reporting
absolute RGB hashes. Explicit native FlattenTransform controls are evidence
only: that parameter is not currently exposed by the independent model.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from frameforge.engine import ffmpeg_executable
from scripts.verify_fusion_nodes import ConfiguredClient, decode, identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-name', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', args.run_name):
        parser.error('Invalid run name')
    fixture = ROOT/'tests/fixtures/fusion-concat-reference.json'
    reference = json.loads(fixture.read_text())
    work = ROOT/'workspace'/('fusion-concat-mcp-'+args.run_name); work.mkdir(exist_ok=True)
    source = work/'texture.mov'
    if not source.exists():
        subprocess.run([ffmpeg_executable(), '-v', 'error', '-f', 'lavfi', '-i',
            "nullsrc=s=320x320:r=24:d=0.5,format=gbrp,geq=r='16+mod(X*7+Y*3,220)':g='16+mod(X*3+Y*5,220)':b='16+mod(X*5+Y*11,220)'",
            '-c:v', 'qtrle', str(source)], check=True)
    raw_source = decode(source)
    assert hashlib.sha256(raw_source).hexdigest() == reference['source_rgb24_full_sha256']
    client = ConfiguredClient(work)
    results, own_identity = [], None
    native_identity = next(c for c in reference['cases'] if c['name']=='identity')
    try:
        for case in reference['cases']:
            if 'flattened' in case['name']:
                continue
            assert case['status']['JobStatus']=='Complete' and case['identity_rgb_exact']
            assert case['native_rgb24_full_sha256']==native_identity['native_rgb24_full_sha256']
            client.tool('create_project', name='Native concat '+case['name'], width=320, height=320, fps=24)
            media = client.tool('import_media', path=str(source))
            clip = client.tool('append_clip', media_id=media['id'], out_frame=12)['id']
            target = 'MediaIn1'
            transforms = sorted((n for n in case['native_nodes'] if n['class']=='Transform'), key=lambda n:n['name'])
            for node in transforms:
                p = node['inputs']; assert p['FilterMethod']==2 and p['FlattenTransform']==0
                current = client.tool('add_fusion_node', clip_id=clip, type='Transform', parameters={
                    'Size':p['Size'], 'Angle':p['Angle'], 'CenterX':p['Center'][0], 'CenterY':p['Center'][1]})['id']
                client.tool('connect_fusion_nodes', clip_id=clip, target_node_id=current, input='Input', source_node_id=target)
                target = current
            client.tool('connect_fusion_nodes', clip_id=clip, target_node_id='MediaOut1', input='Input', source_node_id=target)
            project = work/(case['name']+'.json'); client.tool('save_project', path=str(project)); client.tool('open_project', path=str(project))
            before = client.tool('get_state')
            output = work/(case['name']+'.mov'); client.tool('render', output=str(output))
            assert client.tool('get_state') == before
            raw = decode(output); assert len(raw)==12*320*320*3
            if case['name']=='identity': own_identity = raw
            row = {'name':case['name'], 'native_job':case['job_id'], 'native_status':case['status'],
                'own_restores_identity':raw==own_identity, 'frames':12,
                'own_rgb24_full_sha256':hashlib.sha256(raw).hexdigest(),
                'native_rgb24_full_sha256':case['native_rgb24_full_sha256'],
                'absolute_native_rgb_exact':hashlib.sha256(raw).hexdigest()==case['native_rgb24_full_sha256'],
                'output':identity(output), 'project':identity(project)}
            results.append(row); print(json.dumps(row), flush=True)
        report = {'fixture':identity(fixture), 'driver':identity(Path(__file__)),
            'fusion_model':identity(ROOT/'frameforge/fusion.py'), 'server':client.server_info,
            'cases':results, 'calls':client.calls, 'full_resolve_parity':False,
            'limits':['Relational default-chain behavior only; absolute color comparison is reported separately.',
                'Native FlattenTransform controls are not an implemented independent parameter.',
                'General off-canvas storage and Merge concatenation remain unresolved.']}
        (ROOT/'research'/('fusion-concat-mcp-'+args.run_name+'.json')).write_text(json.dumps(report,indent=2)+'\n')
        assert len(results)==4 and all(r['own_restores_identity'] for r in results)
    finally:
        client.close()


if __name__=='__main__': main()
