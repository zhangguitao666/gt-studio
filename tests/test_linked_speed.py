"""Linked speed equivalence to embedded media and coherent freeze groups."""
import copy
import pytest
from frameforge.engine import Engine
from test_linked_split import linked_project, rgb, pcm


@pytest.mark.parametrize('percentage,ripple',[(100,False),(200,False),(50,False),(-100,False),(200,True),(50,True),(150,True),(0,False)])
def test_linked_speed_keeps_embedded_media_behavior(linked_project,tmp_path,percentage,ripple):
    e,v,a=linked_project
    embedded=Engine(tmp_path/'embedded')
    embedded.project=copy.deepcopy(e.project)
    for track in embedded._timeline()['tracks']:
        if track['kind']=='audio':track['clips']=[]
        for clip in track['clips']:
            clip['audio_enabled']=True;clip.pop('link_group_id',None)
    before=e.get_state()
    args={'clip_id':v['id'],'percentage':percentage,'ripple':ripple,'pitch_correction':False}
    embedded.dispatch('set_clip_speed',args);e.dispatch('set_clip_speed',args)
    video=e._clip(v['id'])[0];audio=e._clip(a['id'])[0]
    for key in ('source_start','source_end','duration_frames','speed_percentage','pitch_correction'):
        assert video[key]==audio[key]
    expected=e.get_state();e.dispatch('undo');assert e.get_state()==before
    e.dispatch('redo');assert e.get_state()==expected
    left,right=tmp_path/'embedded.mov',tmp_path/'linked.mov'
    leftwav,rightwav=tmp_path/'embedded.wav',tmp_path/'linked.wav'
    embedded.dispatch('render',{'output':str(left)});e.dispatch('render',{'output':str(right)})
    embedded.dispatch('render',{'output':str(leftwav)});e.dispatch('render',{'output':str(rightwav)})
    assert rgb(left)==rgb(right) and pcm(leftwav)==pcm(rightwav)


def test_linked_interior_freeze_partitions_groups_and_mutes_only_tails(linked_project,tmp_path):
    e,v,a=linked_project
    baseline=tmp_path/'before.wav';e.dispatch('render',{'output':str(baseline)})
    before=e.get_state()
    tail=e.dispatch('set_clip_speed',{'clip_id':v['id'],'percentage':0,'freeze_frame':18})
    prefix=e._clip(v['id'])[0]
    assert prefix['speed_percentage']==100 and prefix['duration_frames']==18
    assert tail['id']!=v['id'] and tail['duration_frames']==30
    assert prefix['link_group_id']!=tail['link_group_id']
    for peer,track in e._link_members(tail['id']):
        assert peer['speed_percentage']==0 and peer['in_frame']==30 and peer['start_frame']==18
    rendered=tmp_path/'after.wav';e.dispatch('render',{'output':str(rendered)})
    data=pcm(rendered)
    from test_audio_boundaries import assert_native_edges_pcm16
    assert_native_edges_pcm16(pcm(baseline)[:18*2000*4],data[:18*2000*4],tail=True)
    assert not any(data[18*2000*4:])
    e.dispatch('ripple_delete',{'clip_id':tail['id']})
    assert len(e._timeline()['tracks'][0]['clips'])==1
    assert len(e._timeline()['tracks'][1]['clips'])==1
    e.dispatch('undo');e.dispatch('undo');assert e.get_state()==before


def test_linked_freeze_peer_range_failure_rolls_back(linked_project):
    e,v,a=linked_project
    e.dispatch('unlink_clips',{'clip_id':v['id']})
    e.dispatch('trim_clip',{'clip_id':a['id'],'out_frame':24})
    e.dispatch('link_clips',{'clip_ids':[v['id'],a['id']]})
    before=e.get_state()
    with pytest.raises(ValueError,match='every member'):
        e.dispatch('set_clip_speed',{'clip_id':v['id'],'percentage':0,'freeze_frame':18})
    assert e.get_state()==before


def test_linked_ripple_speed_moves_future_audio_video_and_transition(linked_project):
    e,v,a=linked_project
    following=[]
    for _ in range(2):
        clip=e.dispatch('append_clip',{'media_id':v['media_id'],'in_frame':12,'out_frame':60})
        following.append(clip)
        e.dispatch('detach_audio',{'clip_id':clip['id'],'linked':True})
    transition=e.dispatch('add_transition',{'clip_id':following[0]['id']})
    before=e.get_state()
    e.dispatch('set_clip_speed',{'clip_id':v['id'],'percentage':50,'ripple':True})
    for track in e._timeline()['tracks']:
        assert [(c['start_frame'],c['duration_frames']) for c in track['clips']]==[(0,96),(96,48),(144,48)]
    moved=e._timeline()['transitions'][0]
    assert moved['id']==transition['id']
    assert (moved['start_frame'],moved['cut_frame'],moved['end_frame'])==(138,144,150)
    after=e.get_state();e.dispatch('undo');assert e.get_state()==before
    e.dispatch('redo');assert e.get_state()==after
