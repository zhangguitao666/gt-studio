"""Replay completed native audio-boundary cases through the configured MCP."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.verify_fusion_nodes import ConfiguredClient,identity
from frameforge.engine import ffmpeg_executable


def decode(path):
    return subprocess.check_output([ffmpeg_executable(),'-v','error','-i',str(path),'-vn','-c:a','pcm_s32le','-f','s32le','-'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-name',required=True);args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',args.run_name):parser.error('Invalid run name')
    source=ROOT/'research/audio-boundary-runtime-v2.json';status=ROOT/'research/audio-boundary-final-status.json'
    rows=json.loads(source.read_text())['records'];states={j['id']:j['status'] for r in json.loads(status.read_text())['records'] for j in r['case']['after']['jobs']}
    workspace=ROOT/'workspace'/('audio-boundary-comparison-'+args.run_name);workspace.mkdir(exist_ok=True)
    client=ConfiguredClient(workspace);cases=[];excluded=[]
    try:
        tools=client.request('tools/list',{})['tools']
        for record in rows:
            row=record['case'];a=row['after'];spec=a['case'];job=a['jobs'][0]['id']
            if states[job]['JobStatus']!='Complete':excluded.append({'case':spec['name'],'job':job,'status':states[job]});continue
            client.tool('create_project',name='Native audio '+spec['name'],width=16,height=16,fps=24,sample_rate=48000)
            media=client.tool('import_media',path=a['source']);state=client.tool('get_state')
            tracks=[t for t in state['timelines'][0]['tracks'] if t['kind']=='audio']
            while len(tracks)<max(i['track'] for i in spec['items']):tracks.append(client.tool('add_track',kind='audio'))
            for item in spec['items']:
                client.tool('append_clip',media_id=media['id'],track_id=tracks[item['track']-1]['id'],in_frame=item['source_start'],out_frame=item['source_end'],start_frame=item['start'])
            project=workspace/(spec['name']+'.json');client.tool('save_project',path=str(project));client.tool('open_project',path=str(project))
            output=workspace/(spec['name']+'.mov');client.tool('render',output=str(output))
            native=ROOT/'workspace/audio-boundary-native'/(row['timeline']+'.mov');expected,actual=decode(native),decode(output)
            result={'case':spec['name'],'native':identity(native),'independent':identity(output),'project':identity(project),'source':identity(Path(a['source'])),'pcm_s32le_bytes':len(expected),'own_pcm_s32le_bytes':len(actual),'pcm_exact':actual==expected,'native_pcm_sha256':hashlib.sha256(expected).hexdigest(),'own_pcm_sha256':hashlib.sha256(actual).hexdigest()};cases.append(result);print(json.dumps({'case':spec['name'],'exact':result['pcm_exact'],'native_bytes':len(expected),'own_bytes':len(actual)}),flush=True)
        report={'status':'measured_completed_native_audio_cases','native_runtime':identity(source),'native_status':identity(status),'driver':identity(Path(__file__)),'production':[identity(ROOT/p) for p in ('frameforge/engine.py','frameforge/audio_edges.py')],'cases':cases,'excluded':excluded,'public_tools':len(tools),'calls':client.calls,'full_resolve_parity':False,'limits':['48kHz, stereo output of owned mono DC and sine sources, constant speed and default gain only.','Native exports are audio-only MOV; independent exports include a black video track. Audio waveform equality is not container equivalence.','One original Ready job did not start through either scoped API form and remains unmeasured.','Other sample rates, gain changes, manual fades, retime audio, bus/limiter/plugin behavior remain unverified.']}
        target=ROOT/'research'/('audio-boundary-comparison-'+args.run_name+'.json');target.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(target)
        assert len(cases)==8 and all(c['pcm_exact'] for c in cases)
    finally:client.close()


if __name__=='__main__':main()
