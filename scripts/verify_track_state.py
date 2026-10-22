"""Exercise independent track masks and lock rejection through actual stdio MCP."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.compare_native_retime_media import MCPProjectClient
from scripts.verify_linked_split import decode
from scripts.verify_reference_transitions import identity


def main():
    workspace=ROOT/'workspace/track-state-acceptance';workspace.mkdir(parents=True,exist_ok=True)
    client=MCPProjectClient(workspace)
    try:
        client.tool('create_project',name='Track state acceptance',width=640,height=360,fps=24)
        media=client.tool('import_media',path=str(ROOT/'workspace/demo-media/motion.mp4'))
        clip=client.tool('append_clip',media_id=media['id'],in_frame=12,out_frame=60)
        audio=client.tool('detach_audio',clip_id=clip['id'],linked=True)
        state=client.tool('get_state');video_track=next(t['id'] for t in state['timelines'][0]['tracks'] if t['kind']=='video')
        audio_track=audio['audio_track_id']
        baseline=workspace/'baseline.mov';client.tool('render',output=str(baseline))
        baseline_rgb,baseline_pcm=decode(baseline),decode(baseline,True)
        client.tool('set_track_state',track_id=video_track,enabled=False)
        black=workspace/'video-off.mov';client.tool('render',output=str(black))
        black_rgb,black_pcm=decode(black),decode(black,True)
        assert len(black_rgb)==48*640*360*3 and max(black_rgb)<10
        assert black_pcm==baseline_pcm
        client.tool('set_track_state',track_id=video_track,enabled=True)
        client.tool('set_track_state',track_id=audio_track,enabled=False,locked=True)
        silent=workspace/'audio-off.mov';client.tool('render',output=str(silent))
        assert decode(silent)==baseline_rgb and not any(decode(silent,True))
        before=client.tool('get_state')
        rejected=client.request('tools/call',{'name':'set_clip_speed','arguments':{'clip_id':clip['id'],'percentage':50,'ripple':True}})
        assert rejected['isError'] and client.tool('get_state')==before
        client.tool('undo')
        restored=next(t for t in client.tool('get_state')['timelines'][0]['tracks'] if t['id']==audio_track)
        assert restored['enabled'] and not restored['locked']
        client.tool('redo');assert client.tool('get_state')==before
        project=workspace/'track-state.json';client.tool('save_project',path=str(project))
        client.tool('open_project',path=str(project))
        tracks=client.tool('get_state')['timelines'][0]['tracks']
        assert next(t for t in tracks if t['id']==audio_track)['locked']
        report={'status':'passed_independent_track_state_checks','project':identity(project),'renders':[identity(p) for p in (baseline,black,silent)],
                'video_off_frames':48,'video_off_pcm_equals_baseline':True,'audio_off_rgb_equals_baseline':True,'audio_off_pcm_silent':True,
                'locked_peer_rejects_group_edit':True,'single_undo_restores_track_flags':True,'tracks':tracks,
                'public_mcp_tools':len(client.request('tools/list',{})['tools']),
                'declaration_evidence':identity(ROOT/'research/track-state-api-evidence.json'),
                'native_runtime_compared':False,'limitations':['Native enable/lock declarations are inspected; native render and locked UI/API editing policies are not runtime-compared.',
                                                           'Independent lock enforcement includes all clip metadata and track transitions; native exceptions/sync-lock rules remain open.'],
                'full_resolve_parity':False}
        (ROOT/'research/track-state-verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'status':report['status'],'tools':report['public_mcp_tools']}))
    finally:client.close()

if __name__=='__main__':main()
