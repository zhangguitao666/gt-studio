"""Replay captured native linked trim edges through actual independent stdio MCP."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.compare_native_retime_media import MCPProjectClient
from scripts.verify_linked_split import normalized,decode
from scripts.verify_reference_transitions import identity


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-fields',action='store_true',help='Use atomic source/start inspector edits instead of timeline-edge API')
    args=parser.parse_args()
    source=ROOT/'research/linked-trim-runtime.json'
    rows=json.loads(source.read_text())['records']
    workspace=ROOT/'workspace'/('atomic-timing-acceptance' if args.source_fields else 'linked-trim-acceptance');workspace.mkdir(parents=True,exist_ok=True)
    client=MCPProjectClient(workspace);cases=[]
    try:
        for edge in ('start','end'):
            native=next(r['case'] for r in rows if r['case']['action']==f'linked_trim_{edge}_after')
            client.tool('create_project',name=f'Native linked trim {edge} replay',width=640,height=360,fps=24)
            media=client.tool('import_media',path=str(ROOT/'workspace/demo-media/motion.mp4'))
            clip=client.tool('append_clip',media_id=media['id'],start_frame=48,in_frame=12,out_frame=60)
            client.tool('detach_audio',clip_id=clip['id'],linked=True)
            before=workspace/f'{edge}-before.mov';client.tool('render',output=str(before))
            if args.source_fields:
                result=client.tool('trim_clip',clip_id=clip['id'],in_frame=36 if edge=='start' else 12,out_frame=60 if edge=='start' else 36,start_frame=72 if edge=='start' else 48)
                assert result['id']==clip['id']
            else:
                result=client.tool('trim_clip_edge',clip_id=clip['id'],edge=edge,frame=72)
                assert len(result['trimmed_clip_ids'])==2
            state=client.tool('get_state');actual=normalized(state)
            expected=[]
            for item in native['items']:
                expected.append({'kind':item['kind'],'start':item['start']-native['origin'],'duration':item['duration'],
                    'links':[{'kind':l['kind'],'start':l['start']-native['origin'],'duration':l['duration']} for l in item['links']]})
            expected.sort(key=lambda i:(i['kind'],i['start']))
            assert actual==expected
            sources=[{'kind':t['kind'],'start':c['in_frame'],'end':c['out_frame']} for t in state['timelines'][0]['tracks'] for c in t['clips']]
            expected_sources=[{'kind':c['kind'],'start':c['source_start'],'end':c['source_end']} for c in native['items']]
            assert sorted(sources,key=lambda x:x['kind'])==sorted(expected_sources,key=lambda x:x['kind'])
            after=workspace/f'{edge}-after.mov';client.tool('render',output=str(after))
            b_rgb,a_rgb=decode(before),decode(after);b_pcm,a_pcm=decode(before,True),decode(after,True)
            size=640*360*3
            if edge=='end':
                assert a_rgb==b_rgb[:72*size] and a_pcm==b_pcm[:72*2000*4]
            else:
                assert len(a_rgb)==96*size and a_rgb[72*size:]==b_rgb[72*size:]
                assert a_pcm[72*2000*4:]==b_pcm[72*2000*4:] and not any(a_pcm[:72*2000*4])
            project=workspace/f'linked-trim-{edge}.json';client.tool('save_project',path=str(project))
            saved=client.tool('get_state');client.tool('undo');assert all(i['duration']==48 for i in normalized(client.tool('get_state')))
            client.tool('redo');assert client.tool('get_state')==saved
            cases.append({'edge':edge,'actual_items':actual,'native_items':expected,'actual_sources':sources,'native_sources':expected_sources,
                          'project':identity(project),'renders':[identity(before),identity(after)],'decoded_frames_after':len(a_rgb)//size,
                          'independent_retained_rgb_identical':True,'independent_retained_pcm_identical':True})
        report={'operation':'trim_clip' if args.source_fields else 'trim_clip_edge','status':'passed_bounded_linked_trim_checks','cases':cases,'native_evidence':identity(source),
                'public_mcp_tools':len(client.request('tools/list',{})['tools']),
                'limitations':['Native cases cover inward non-ripple edge trims of one aligned normal-speed pair, with all playhead clips selected.',
                               'Source-end equality is observed in these examples, not a universal source-boundary convention.',
                               'RGB/PCM checks compare independent outputs, not native rendered media.',
                               'Outward trims, offsets, locks, ripple/roll/slip/slide and retimed native cases remain open.'],
                'full_resolve_parity':False}
        output=ROOT/'research'/('atomic-timing-verification.json' if args.source_fields else 'linked-trim-verification.json')
        output.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'status':report['status'],'cases':len(cases),'tools':report['public_mcp_tools']}))
    finally:client.close()

if __name__=='__main__':main()
