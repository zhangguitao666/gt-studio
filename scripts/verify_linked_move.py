"""Replay native linked nudge through independent MCP and decode retained media."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.compare_native_retime_media import MCPProjectClient
from scripts.verify_linked_split import normalized,decode
from scripts.verify_reference_transitions import identity


def main():
    source=ROOT/'research/linked-move-runtime.json'
    rows=json.loads(source.read_text())['records']
    before=next(r['case'] for r in rows if r['case']['action']=='linked_move_prepare')
    after=next(r['case'] for r in rows if r['case']['action']=='linked_move_after')
    workspace=ROOT/'workspace/linked-move-acceptance';workspace.mkdir(parents=True,exist_ok=True)
    client=MCPProjectClient(workspace)
    try:
        client.tool('create_project',name='Native linked nudge replay',width=640,height=360,fps=24)
        media=client.tool('import_media',path=str(ROOT/'workspace/demo-media/motion.mp4'))
        clip=client.tool('append_clip',media_id=media['id'],start_frame=48,in_frame=12,out_frame=60)
        client.tool('detach_audio',clip_id=clip['id'],linked=True)
        initial=workspace/'before.mov';client.tool('render',output=str(initial))
        observations=[]
        for phase,case in [('before',before),('after',after)]:
            if phase=='after':client.tool('move_clip',clip_id=clip['id'],start_frame=49)
            actual=normalized(client.tool('get_state'))
            expected=[]
            for c in case['items']:
                expected.append({'kind':c['kind'],'start':c['start']-case['origin'],'duration':c['duration'],
                  'links':[{'kind':l['kind'],'start':l['start']-case['origin'],'duration':l['duration']} for l in c['links']]})
            expected.sort(key=lambda i:(i['kind'],i['start']))
            assert actual==expected
            observations.append({'phase':phase,'native':expected,'actual':actual})
        moved=workspace/'after.mov';client.tool('render',output=str(moved))
        before_rgb,after_rgb=decode(initial),decode(moved)
        before_pcm,after_pcm=decode(initial,True),decode(moved,True)
        assert len(before_rgb)==96*640*360*3 and len(after_rgb)==97*640*360*3
        assert before_rgb[48*640*360*3:]==after_rgb[49*640*360*3:]
        assert before_pcm[48*2000*4:]==after_pcm[49*2000*4:] and not any(after_pcm[:49*2000*4])
        project=workspace/'linked-move.json';client.tool('save_project',path=str(project))
        saved=client.tool('get_state');client.tool('undo')
        assert all(i['start']==48 for i in normalized(client.tool('get_state')))
        client.tool('redo');assert client.tool('get_state')==saved
        report={'status':'passed_bounded_linked_move_checks','native_evidence':identity(source),'observations':observations,
          'project':identity(project),'renders':[identity(initial),identity(moved)],'independent_decoded_source_rgb_identical':True,
          'independent_decoded_source_pcm_identical':True,'silent_lead_frames':49,'decoded_frame_counts':[96,97],
          'public_mcp_tools':len(client.request('tools/list',{})['tools']),
          'limitations':['Native readback covers one aligned A/V pair nudged right one frame through menus with linked selection enabled.',
                         'Independent RGB/PCM compares retained source payloads before and after move, not native rendered pixels/audio.',
                         'Cross-track vertical mappings, overwrite collisions, locks, disabled linked selection and general move semantics remain unverified.'],
          'full_resolve_parity':False}
        (ROOT/'research/linked-move-verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'status':report['status'],'tools':report['public_mcp_tools'],'native_phases':len(observations)}))
    finally:client.close()

if __name__=='__main__':main()
