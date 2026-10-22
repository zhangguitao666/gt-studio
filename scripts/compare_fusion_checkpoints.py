"""Measure independent node checkpoints against captured native RGBA exports."""
from array import array
from collections import Counter
import hashlib
import json
import operator
from pathlib import Path
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from frameforge.engine import ffmpeg_executable
from scripts.verify_fusion_nodes import ConfiguredClient,identity


def rgba(path):
    return subprocess.run([ffmpeg_executable(),'-v','error','-i',str(path),'-frames:v','1','-pix_fmt','rgba64le','-f','rawvideo','-'],capture_output=True,check=True).stdout


def main():
    baseline=ROOT/'research/fusion-native-media-comparison.json'
    original=ROOT/'research/fusion-native-alpha-measurements.json'
    cases=json.loads(baseline.read_text())['cases'];native=json.loads(original.read_text())['cases']
    workspace=ROOT/'workspace/fusion-checkpoints';workspace.mkdir(parents=True,exist_ok=True)
    client=ConfiguredClient(workspace);observations=[]
    try:
        tools=client.request('tools/list',{})['tools'];assert len(tools)==52
        assert 'render_fusion_frame' in {t['name'] for t in tools}
        for case in cases:
            project=case['project'];assert identity(Path(project['path']))==project
            client.tool('open_project',path=project['path'])
            state=client.tool('get_state');clip=state['timelines'][0]['tracks'][0]['clips'][0]
            description=client.tool('get_fusion_graph',clip_id=clip['id'])
            output=workspace/(case['mode']+'.png')
            client.tool('render_fusion_frame',clip_id=clip['id'],output=str(output),frame=0)
            assert client.tool('get_state')==state
            reference=next(n for n in native if n['timeline']==case['native_timeline'] and n['requested_alpha_mode']==1)
            assert identity(Path(reference['artifact']['path']))==reference['artifact']
            a,b=rgba(reference['artifact']['path']),rgba(output)
            assert len(a)==len(b)==640*360*8
            first,second=array('H'),array('H');first.frombytes(a);second.frombytes(b)
            if sys.byteorder!='little':first.byteswap();second.byteswap()
            channels={}
            for index,key in enumerate('RGBA'):
                counts=Counter(map(operator.sub,second[index::4],first[index::4]));length=sum(counts.values())
                channels[key]={'mae16':sum(abs(d)*n for d,n in counts.items())/length,'mse16':sum(d*d*n for d,n in counts.items())/length,'max_abs16':max(map(abs,counts))}
            samples=[]
            for x,y in [(160,90),(480,90),(320,180)]:
                at=(y*640+x)*8;samples.append({'xy':[x,y],'native':list(struct.unpack('<4H',a[at:at+8])),'independent':list(struct.unpack('<4H',b[at:at+8]))})
            intermediate=[]
            for node in description['graph']['nodes']:
                if node['type'] not in ('MediaOut',):
                    path=workspace/(case['mode']+'-'+node['id']+'.png')
                    client.tool('render_fusion_frame',clip_id=clip['id'],node_id=node['id'],output=str(path),frame=0)
                    data=rgba(path);at=(90*640+480)*8
                    intermediate.append({'node_id':node['id'],'type':node['type'],'artifact':identity(path),'sample_480_90':list(struct.unpack('<4H',data[at:at+8]))})
            observations.append({'mode':case['mode'],'native':reference['artifact'],'checkpoint':identity(output),'rgba_channels':channels,'samples':samples,
                                 'intermediate_nodes':intermediate,'project_unchanged':client.tool('get_state')==state,'baseline_video_rgb_mae':case['rgb_mae']})
            print(json.dumps({'mode':case['mode'],'samples':samples},ensure_ascii=False),flush=True)
        report={'status':'measured_node_checkpoints_against_native_exports','server':client.server_info,'public_tools':len(tools),'native_reference':identity(original),'video_baseline':identity(baseline),
                'driver':identity(Path(__file__).resolve()),'decoder':identity(Path(ffmpeg_executable())),'cases':observations,
                'scope':'first clip-local frame, selected node before clip/timeline processing, compared to FFmpeg-decoded native ProRes4444 exports',
                'limitations':['Native exports are not native internal buffers; codec and color processing residuals remain.','PNG uses RGBA16 storage; Transform/Merge processing still has an 8-bit boundary.','Only six static cases; no full native equivalence claim.'],
                'native_equivalence_verified':False,'full_resolve_parity':False}
        destination=ROOT/'research/fusion-checkpoint-comparison.json';destination.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n');print(destination)
    finally:client.close()


if __name__=='__main__':main()
