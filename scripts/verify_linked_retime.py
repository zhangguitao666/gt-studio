"""Recreate retained native retime cases with independent linked audio items.

Native pixel/audio metrics are reused only after original artifacts and decoder
identity are verified and linked RGB/PCM exactly matches the old embedded output.
"""
import argparse
import re
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.compare_native_retime_media import MCPProjectClient
from scripts.verify_linked_split import decode
from scripts.verify_reference_transitions import identity
from frameforge.engine import ffmpeg_executable


def check_identity(record):
    actual=identity(Path(record['path']))
    assert actual['sha256']==record['sha256'],record['path']
    return actual


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-name',help='Preserve earlier runs by using a separate artifact/report suffix')
    parser.add_argument('--baseline-report',type=Path,default=ROOT/'research/native-media-comparison-precision.json')
    args=parser.parse_args()
    if args.run_name and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',args.run_name):parser.error('run-name must contain1–64 ASCII letters,digits,hyphens or underscores')
    suffix='-'+args.run_name if args.run_name else ''
    baseline_path=args.baseline_report.resolve()
    baseline=json.loads(baseline_path.read_text())
    assert len(baseline['cases'])==10
    decoder=check_identity(baseline['ffmpeg'])
    assert Path(ffmpeg_executable()).resolve()==Path(decoder['path']).resolve()
    source=check_identity(baseline['source'])
    workspace=ROOT/'workspace'/('linked-retime-acceptance'+suffix);workspace.mkdir(parents=True,exist_ok=True)
    client=MCPProjectClient(workspace);cases=[]
    try:
        for original in baseline['cases']:
            native_file=check_identity(original['native_export'])
            embedded_file=check_identity(original['independent_export'])
            check_identity(original['reconstruction']['project'])
            timeline=original['native_timeline'];first=None;media=None;actions=[]
            for record in original['reconstruction']['mcp_calls']:
                action=record['action'];params=dict(record['params'])
                if action in ('save_project','render'):continue
                assert action in ('create_project','import_media','append_clip','set_playhead','set_clip_speed','trim_clip')
                if action=='import_media':
                    assert params['path']==source['path']
                elif action=='append_clip':params['media_id']=media['id']
                elif action in ('set_clip_speed','trim_clip'):params['clip_id']=first
                result=client.tool(action,**params);actions.append({'action':action,'params':params})
                if action=='import_media':media=result
                if action=='append_clip':
                    if first is None:first=result['id']
                    client.tool('detach_audio',clip_id=result['id'],linked=True)
                    actions.append({'action':'detach_audio','params':{'clip_id':result['id'],'linked':True}})
            state=client.tool('get_state')
            video=sorted([c for t in state['timelines'][0]['tracks'] if t['kind']=='video' for c in t['clips']],key=lambda c:c['start_frame'])
            audio=sorted([c for t in state['timelines'][0]['tracks'] if t['kind']=='audio' for c in t['clips']],key=lambda c:c['start_frame'])
            normalize=lambda clips:[{'start':c['start_frame'],'duration':c['duration_frames'],'percentage':c['speed_percentage']} for c in clips]
            assert normalize(video)==normalize(audio)
            native=original['native_case'];origin=native['before']['first']['start']
            expected=[{'start':c['start']-origin,'duration':c['duration'],'percentage':c['speed']['Percentage']}
                      for c in native['after'].get('all',[native['after']['first'],native['after']['second']])]
            assert normalize(video)==expected
            project=workspace/f'{timeline}.json';client.tool('save_project',path=str(project))
            output=workspace/f'{timeline}.mov';client.tool('render',output=str(output),format='mov')
            embedded_rgb,linked_rgb=decode(Path(embedded_file['path'])),decode(output)
            assert linked_rgb==embedded_rgb,f'Linked RGB changed {timeline}'
            embedded_pcm,linked_pcm=decode(Path(embedded_file['path']),True),decode(output,True)
            assert linked_pcm==embedded_pcm,f'Linked PCM changed {timeline}'
            cases.append({'native_timeline':timeline,'reconstruction_note':original['reconstruction']['note'],
              'native_export':native_file,'previous_embedded_export':embedded_file,'linked_export':identity(output),'project':identity(project),
              'mcp_actions':actions,'native_video_timing':expected,'linked_video_timing':normalize(video),'linked_audio_timing':normalize(audio),
              'decoded_rgb_equal_to_embedded':True,'decoded_pcm_equal_to_embedded':True,'decoded_frames':len(linked_rgb)//(640*360*3),
              'prior_native_image_metrics':{k:v for k,v in original['comparison']['images'].items() if k!='per_frame'},
              'prior_native_audio_metrics':original['comparison']['audio']})
        report={'status':'passed_linked_retime_baseline_equivalence','cases':cases,'baseline_report':identity(baseline_path),
          'decoder':decoder,'source':source,'public_mcp_tools':len(client.request('tools/list',{})['tools']),
          'limitations':['Linked RGB/PCM is compared to the retained independent embedded-audio outputs, not newly rendered original software.',
                         'Prior native metrics apply only because native/embedded artifacts, decoder identity and exact linked decoded streams are verified.',
                         'Native audio item getters were not captured in the original retime probe; matching peer positions are an independent invariant.',
                         'The older default-playhead freeze remains a selected-state reconstruction, not action-equivalence proof.',
                         'Native pixels/audio remain different; arbitrary offset, mixed-length, track-lock and keyframe retime behavior remain open.'],
          'full_resolve_parity':False}
        (ROOT/'research'/('linked-retime-verification'+suffix+'.json')).write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'status':report['status'],'cases':len(cases),'tools':report['public_mcp_tools']}))
    finally:client.close()

if __name__=='__main__':main()
