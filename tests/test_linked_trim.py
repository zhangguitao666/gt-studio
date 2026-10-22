"""Native aligned edge-trim readbacks, decoded media and atomic peer constraints."""
import json
from fractions import Fraction
import pytest
from test_linked_split import linked_project, pcm, rgb, ROOT


@pytest.mark.parametrize('edge',['start','end'])
def test_linked_edge_trim_matches_native_and_retains_source_payload(linked_project,tmp_path,edge):
    e,v,a=linked_project
    reference=json.loads((ROOT/'research/linked-trim-runtime.json').read_text())
    assert reference['snapshot']['sha256']=='5d5a1ed5754933a7590f2902b9320c41dc0f845139057d9e4c31629e7c2b4228'
    original=next(r['case'] for r in reference['records'] if r['case']['action']==f'linked_trim_{edge}_after')
    e.dispatch('move_clip',{'clip_id':v['id'],'start_frame':48})
    before=e.get_state()
    baseline=tmp_path/'before.mov';e.dispatch('render',{'output':str(baseline)})
    basewav=tmp_path/'before.wav';e.dispatch('render',{'output':str(basewav)})
    result=e.dispatch('trim_clip_edge',{'clip_id':v['id'],'edge':edge,'frame':72})
    assert set(result['trimmed_clip_ids'])=={v['id'],a['id']}
    actual=[]
    for t in e._timeline()['tracks']:
        for c in t['clips']:
            actual.append({'kind':t['kind'],'start':c['start_frame'],'duration':c['duration_frames'],'source_start':c['in_frame'],'source_end':c['out_frame']})
    expected=[{'kind':c['kind'],'start':c['start']-original['origin'],'duration':c['duration'],'source_start':c['source_start'],'source_end':c['source_end']} for c in original['items']]
    assert sorted(actual,key=lambda i:i['kind'])==sorted(expected,key=lambda i:i['kind'])
    after=e.get_state();e.dispatch('undo');assert e.get_state()==before
    e.dispatch('redo');assert e.get_state()==after
    saved=tmp_path/'trim.json';e.dispatch('save_project',{'path':str(saved)});e.dispatch('open_project',{'path':str(saved)})
    rendered=tmp_path/'after.mov';e.dispatch('render',{'output':str(rendered)})
    outputwav=tmp_path/'after.wav';e.dispatch('render',{'output':str(outputwav)})
    frame_bytes=160*90*3
    if edge=='end':
        assert rgb(rendered)==rgb(baseline)[:72*frame_bytes]
        assert pcm(outputwav)==pcm(basewav)[:72*2000*4]
    else:
        assert len(rgb(rendered))==96*frame_bytes
        assert rgb(rendered)[72*frame_bytes:]==rgb(baseline)[72*frame_bytes:]
        assert pcm(outputwav)[72*2000*4:]==pcm(basewav)[72*2000*4:]
        assert not any(pcm(outputwav)[:72*2000*4])


@pytest.mark.parametrize('speed,edge,frame',[(50,'start',37),(50,'end',37),(-100,'start',17),(-100,'end',17),(150,'start',11),(0,'end',19)])
def test_linked_trim_retains_rational_retime_and_freeze_positions(linked_project,speed,edge,frame):
    e,v,a=linked_project
    for clip in (v,a):e.dispatch('set_clip_speed',{'clip_id':clip['id'],'percentage':speed,'ripple':True})
    before=e.get_state();old=e._clip(v['id'])[0].copy()
    e.dispatch('trim_clip_edge',{'clip_id':a['id'],'edge':edge,'frame':frame})
    video=e._clip(v['id'])[0];audio=e._clip(a['id'])[0]
    for key in ('start_frame','duration_frames','source_start','source_end'):assert video[key]==audio[key]
    def rational(x):return Fraction(x['num'],x['den'])
    if speed==0:
        assert video['source_start']==old['source_start'] and video['source_end']==old['source_end']
    elif edge=='start':
        assert video['duration_frames']==old['duration_frames']-frame
        if speed>0:assert rational(video['source_start'])==rational(old['source_start'])+Fraction(frame)*abs(Fraction(str(speed)))/100
        else:assert rational(video['source_end'])==rational(old['source_end'])-frame
    else:assert video['duration_frames']==frame
    e.dispatch('undo');assert e.get_state()==before


def test_linked_trim_peer_collision_source_bounds_and_transition_rollback(linked_project):
    e,v,a=linked_project
    audio_track=e._clip(a['id'])[1]
    blocker=e.dispatch('append_clip',{'media_id':v['media_id'],'track_id':audio_track['id'],'start_frame':54,'in_frame':0,'out_frame':6})
    before=e.get_state()
    with pytest.raises(ValueError,match='overlap'):e.dispatch('trim_clip_edge',{'clip_id':v['id'],'edge':'end','frame':60})
    assert e.get_state()==before
    for edge,frame in [('start',48),('end',0),('end',100)]:
        with pytest.raises(ValueError):e.dispatch('trim_clip_edge',{'clip_id':v['id'],'edge':edge,'frame':frame})
        assert e.get_state()==before
    e.dispatch('undo');assert len(e._clip(a['id'])[1]['clips'])==1
    second=e.dispatch('append_clip',{'media_id':v['media_id'],'in_frame':12,'out_frame':60})
    e.dispatch('add_transition',{'clip_id':v['id']})
    before=e.get_state()
    with pytest.raises(ValueError,match='transition'):e.dispatch('trim_clip_edge',{'clip_id':v['id'],'edge':'end','frame':36})
    assert e.get_state()==before
