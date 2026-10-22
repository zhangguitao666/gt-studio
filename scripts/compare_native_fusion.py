"""Recreate the captured six Fusion cases and measure full decoded sequences."""
from collections import Counter
import argparse
import hashlib
import json
import math
import operator
import re
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from frameforge.engine import ffmpeg_executable
from scripts.verify_fusion_nodes import ConfiguredClient, decode, identity


def bounds(raw, width, height):
    points = [(i % width, i // width) for i, blue in enumerate(raw[2:width*height*3:3]) if blue > 20]
    if not points: return None
    return [min(x for x,y in points), min(y for x,y in points), max(x for x,y in points)+1, max(y for x,y in points)+1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-name')
    args=parser.parse_args()
    if args.run_name and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',args.run_name):parser.error('Invalid run name')
    suffix='-'+args.run_name if args.run_name else ''
    reference = ROOT/'research/fusion-native-runtime-v2.json'
    captured = json.loads(reference.read_text())
    records = captured['records']; assert len(records) == 6 and all(r['case']['completed'] for r in records)
    workspace = ROOT/'workspace'/('fusion-native-comparison'+suffix); workspace.mkdir(parents=True, exist_ok=True)
    client = ConfiguredClient(workspace)
    observations = []
    try:
        for record in records:
            case = record['case']; after = case['after']; mode = after['mode']
            assert after['timeline_settings'] == {'width':'640','height':'360','fps':24}
            assert after['clip']['duration'] == 48
            native = ROOT/'workspace/fusion-native-reference'/(case['timeline']+'.mov')
            client.tool('create_project', name='Fusion measured '+mode, width=640, height=360, fps=24)
            source = client.tool('import_media', path=after['source'])
            clip = client.tool('append_clip', media_id=source['id'], out_frame=48)['id']
            def add(kind, **parameters):
                return client.tool('add_fusion_node', clip_id=clip, type=kind, parameters=parameters)['id']
            def connect(node, port, source):
                client.tool('connect_fusion_nodes', clip_id=clip, target_node_id=node, input=port, source_node_id=source)
            if mode != 'identity':
                bg = add('Background', Blue=1, Alpha=1 if mode == 'rotation_90' else 0.5)
                target = bg
                if mode in ('transform_upper_right','merge_half','rotation_90'):
                    target = add('Transform', Size=0.5, CenterX=0.75, CenterY=0.75)
                    connect(target,'Input',bg)
                if mode == 'merge_half':
                    merge = add('Merge', Blend=0.5); connect(merge,'Background','MediaIn1'); connect(merge,'Foreground',target); target=merge
                elif mode == 'fanout':
                    merge = add('Merge'); connect(merge,'Background',bg); connect(merge,'Foreground',bg); target=merge
                elif mode == 'rotation_90':
                    rot = add('Transform', Angle=90); connect(rot,'Input',target); target=rot
                connect('MediaOut1','Input',target)
            output = workspace/(mode+'.mov'); result = client.tool('render', output=str(output))
            project = workspace/(mode+'.json'); client.tool('save_project', path=str(project))
            original, own = decode(native), decode(output)
            assert len(original) == len(own) == 48*640*360*3
            difference = Counter(map(operator.sub, own, original)); count = len(own)
            mae = sum(abs(delta)*n for delta,n in difference.items())/count
            mse = sum(delta*delta*n for delta,n in difference.items())/count
            def sample(raw,x,y):
                at=(y*640+x)*3;return list(raw[at:at+3])
            original_pcm, own_pcm = decode(native,True), decode(output,True)
            a=struct.unpack('<'+'h'*(len(original_pcm)//2),original_pcm)
            b=struct.unpack('<'+'h'*(len(own_pcm)//2),own_pcm)
            pcm_mse=sum((x-y)**2 for x,y in zip(a,b))/min(len(a),len(b)) if a and b else None
            observations.append({'mode':mode,'native_timeline':case['timeline'], 'native':identity(native),'independent':identity(output),'project':identity(project),
                'frames':48, 'rgb_mae':mae,'rgb_mse':mse,'rgb_max_abs':max(map(abs,difference)),
                'native_blue_bounds':bounds(original,640,360),'own_blue_bounds':bounds(own,640,360),
                'samples':[{'xy':[x,y],'native':sample(original,x,y),'own':sample(own,x,y)} for x,y in [(160,90),(480,90),(320,180)]],
                'pcm':{'native_bytes':len(original_pcm),'own_bytes':len(own_pcm),'exact':original_pcm==own_pcm,'mse_over_shorter_length':pcm_mse},
                'graph':client.tool('get_fusion_graph',clip_id=clip)})
            print(json.dumps({'mode':mode,'mae':mae,'mse':mse,'samples':observations[-1]['samples']},ensure_ascii=False),flush=True)
        report={'status':'measured_six_native_fusion_cases_not_equivalent','reference':identity(reference),'snapshot':captured['snapshot'],
                'decoder':identity(Path(ffmpeg_executable())), 'driver':identity(Path(__file__).resolve()),
                'source':identity(Path(records[0]['case']['after']['source'])),'server':client.server_info,'cases':observations,
                'full_sequence_rgb_comparison':True,'native_fusion_equivalence_verified':False,'full_resolve_parity':False,
                'limitations':['Current independent parameters reproduce selected numeric declarations, not the complete native tool state.',
                               'Native and independent ProRes encoders/color tags can add residuals; these measurements alone do not attribute a cause.',
                               'Only six static 640x360/24fps cases; no general keyframe, mask, precision, runtime, or node parity claim.']}
        target=ROOT/'research'/('fusion-native-media-comparison'+suffix+'.json');target.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n');print(target)
    finally: client.close()


if __name__=='__main__':main()
