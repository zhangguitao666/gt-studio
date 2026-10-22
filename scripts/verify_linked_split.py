"""Replay saved native blade/link readbacks through the independent stdio MCP."""
import json
from pathlib import Path
import sys
import subprocess
import hashlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.compare_native_retime_media import MCPProjectClient
from scripts.verify_reference_transitions import identity
from frameforge.engine import ffmpeg_executable


def decode(path, audio=False):
    args=['-vn','-ac','2','-ar','48000','-f','s16le'] if audio else ['-an','-pix_fmt','rgb24','-f','rawvideo']
    return subprocess.run([ffmpeg_executable(),'-v','error','-i',str(path),*args,'-'],capture_output=True,check=True).stdout


def normalized(state):
    items=[(c,t['kind']) for t in state['timelines'][0]['tracks'] for c in t['clips']]
    return sorted([{'kind':kind,'start':c['start_frame'],'duration':c['duration_frames'],
                    'links':sorted([{'kind':k,'start':other['start_frame'],'duration':other['duration_frames']}
                                    for other,k in items if other['id']!=c['id'] and c.get('link_group_id') and c.get('link_group_id')==other.get('link_group_id')],key=lambda i:(i['kind'],i['start']))}
                   for c,kind in items],key=lambda i:(i['kind'],i['start']))


def main():
    evidence=ROOT/'research/linked-split-runtime.json'
    native=json.loads(evidence.read_text())
    before=next(r['case'] for r in native['records'] if r['case']['action']=='linked_split_prepare')
    after=next(r['case'] for r in native['records'] if r['case']['action']=='linked_split_after')
    workspace=ROOT/'workspace/linked-split-acceptance';workspace.mkdir(parents=True,exist_ok=True)
    client=MCPProjectClient(workspace)
    try:
        client.tool('create_project',name='Linked blade native replay',width=640,height=360,fps=24)
        media=client.tool('import_media',path=str(ROOT/'workspace/demo-media/motion.mp4'))
        v=client.tool('append_clip',media_id=media['id'],in_frame=12,out_frame=60)
        client.tool('detach_audio',clip_id=v['id'],linked=True)
        baseline=workspace/'before.mov';client.tool('render',output=str(baseline))
        observations=[]
        for label,case in [('before',before),('after',after)]:
            if label=='after':
                split=client.tool('split_clip',clip_id=v['id'],frame=24)
                assert len(split['linked_splits'])==2
            actual=normalized(client.tool('get_state'))
            expected=[]
            for item in case['items']:
                expected.append({'kind':item['kind'],'start':item['start']-case['origin'],'duration':item['duration'],
                    'links':sorted([{'kind':l['kind'],'start':l['start']-case['origin'],'duration':l['duration']} for l in item['links']],key=lambda i:(i['kind'],i['start']))})
            expected.sort(key=lambda i:(i['kind'],i['start']))
            assert actual==expected
            observations.append({'phase':label,'actual':actual,'native':expected})
        split_media=workspace/'after.mov';client.tool('render',output=str(split_media))
        baseline_rgb,split_rgb=decode(baseline),decode(split_media)
        baseline_pcm,split_pcm=decode(baseline,True),decode(split_media,True)
        assert len(split_rgb)==48*640*360*3 and baseline_rgb==split_rgb
        assert baseline_pcm==split_pcm
        project=workspace/'linked-split.json';client.tool('save_project',path=str(project))
        saved=client.tool('get_state')
        client.tool('ripple_delete',clip_id=split['second']['id'])
        remaining=normalized(client.tool('get_state'))
        assert len(remaining)==2 and all(i['start']==0 and i['duration']==24 for i in remaining)
        prefix=workspace/'prefix.mov';client.tool('render',output=str(prefix))
        prefix_rgb=decode(prefix);assert prefix_rgb==baseline_rgb[:24*640*360*3]
        prefix_pcm=decode(prefix,True);assert prefix_pcm==baseline_pcm[:24*2000*4]
        client.tool('undo');assert client.tool('get_state')==saved
        report={'status':'passed_bounded_linked_split_checks','native_evidence':identity(evidence),
                'observations':observations,'project':identity(project),'renders':[identity(x) for x in (baseline,split_media,prefix)],
                'independent_rgb_byte_identical_before_after':True,'independent_pcm_byte_identical_before_after':True,
                'remaining_prefix_frames':24,'prefix_pcm_sha256':hashlib.sha256(prefix_pcm).hexdigest(),
                'public_mcp_tools':len(client.request('tools/list',{})['tools']),
                'limitations':['Native comparison covers item positions, durations and linked peer identities normalized by kind/start/duration.',
                               'Decoded pixels and PCM compare independent renders, not original native renders.',
                               'One aligned native video/audio pair at normal speed; generic offset, track-lock, selection and retime linkage remain open.'],
                'full_resolve_parity':False}
        (ROOT/'research/linked-split-verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'status':report['status'],'tools':report['public_mcp_tools'],'native_phases':len(observations)}))
    finally:client.close()

if __name__=='__main__':main()
