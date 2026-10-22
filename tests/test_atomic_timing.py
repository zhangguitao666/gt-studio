"""Atomic source-range + position edits, linked retime phase and UI rollback."""
from fractions import Fraction
import pytest
from test_linked_split import linked_project


def test_atomic_timing_validates_final_arrangement_and_undo_once(linked_project):
    e,v,a=linked_project
    next_video=e.dispatch('append_clip',{'media_id':v['media_id'],'in_frame':12,'out_frame':60})
    e.dispatch('detach_audio',{'clip_id':next_video['id'],'linked':True})
    before=e.get_state()
    # Expanding at the old position would collide; the final moved range is free.
    result=e.dispatch('trim_clip',{'clip_id':v['id'],'in_frame':0,'out_frame':72,'start_frame':120})
    assert result['id']==v['id']
    for item in (v,a):
        clip=e._clip(item['id'])[0]
        assert (clip['start_frame'],clip['duration_frames'],clip['in_frame'],clip['out_frame'])==(120,72,0,72)
    after=e.get_state()
    e.dispatch('undo');assert e.get_state()==before
    e.dispatch('redo');assert e.get_state()==after


def test_atomic_timing_peer_conflict_rolls_back_source_position_and_history(linked_project):
    e,v,a=linked_project
    audio_track=e._clip(a['id'])[1]
    e.dispatch('append_clip',{'media_id':v['media_id'],'track_id':audio_track['id'],'start_frame':60,'in_frame':0,'out_frame':12})
    before=e.get_state()
    with pytest.raises(ValueError,match='overlap'):
        e.dispatch('trim_clip',{'clip_id':v['id'],'in_frame':18,'out_frame':42,'start_frame':48})
    assert e.get_state()==before
    e.dispatch('undo');assert len(e._clip(a['id'])[1]['clips'])==1


def test_source_timing_signed_retime_mapping_preserves_peer_offsets(linked_project):
    e,v,a=linked_project
    e.dispatch('unlink_clips',{'clip_id':v['id']})
    e.dispatch('set_clip_speed',{'clip_id':v['id'],'percentage':50,'ripple':True})
    e.dispatch('set_clip_speed',{'clip_id':a['id'],'percentage':-100,'ripple':True})
    e.dispatch('move_clip',{'clip_id':a['id'],'start_frame':6})
    e.dispatch('link_clips',{'clip_ids':[v['id'],a['id']]})
    e.dispatch('trim_clip',{'clip_id':v['id'],'in_frame':18,'out_frame':54,'start_frame':10})
    video=e._clip(v['id'])[0];audio=e._clip(a['id'])[0]
    assert (video['start_frame'],video['duration_frames'],video['in_frame'],video['out_frame'])==(10,72,18,54)
    assert (audio['start_frame'],audio['duration_frames'],audio['in_frame'],audio['out_frame'])==(16,24,24,48)
    # A second trim valid for the longer video would exhaust the shorter peer.
    before=e.get_state()
    with pytest.raises(ValueError):e.dispatch('trim_clip',{'clip_id':v['id'],'in_frame':18,'out_frame':30})
    assert e.get_state()==before


def test_timing_noop_keeps_fractional_split_phase_and_omitted_endpoint(linked_project):
    e,v,a=linked_project
    for item in (v,a):e.dispatch('set_clip_speed',{'clip_id':item['id'],'percentage':50,'ripple':True})
    parts=e.dispatch('split_clip',{'clip_id':v['id'],'frame':37})
    tail=parts['second'];before=e.get_state()
    e.dispatch('trim_clip',{'clip_id':tail['id'],'start_frame':37})
    assert e.get_state()==before
    assert tail['source_start']=={'num':61,'den':2}
    e.dispatch('trim_clip',{'clip_id':tail['id'],'out_frame':58,'start_frame':40})
    for c,_ in e._link_members(tail['id']):
        assert c['source_start']=={'num':61,'den':2}
        assert c['source_end']=={'num':58,'den':1}
        assert c['start_frame']==40 and c['duration_frames']==55


def test_atomic_source_edit_rejects_one_frame_past_actual_media(linked_project):
    e,v,a=linked_project
    before=e.get_state()
    with pytest.raises(ValueError,match='beyond source'):
        e.dispatch('trim_clip',{'clip_id':v['id'],'out_frame':73,'start_frame':100})
    assert e.get_state()==before
    # Frozen source edits cannot determine a moving peer's time mapping.
    e.dispatch('unlink_clips',{'clip_id':v['id']})
    e.dispatch('set_clip_speed',{'clip_id':v['id'],'percentage':0})
    e.dispatch('link_clips',{'clip_ids':[v['id'],a['id']]})
    before=e.get_state()
    with pytest.raises(ValueError,match='Unlink moving peers'):
        e.dispatch('trim_clip',{'clip_id':v['id'],'in_frame':18,'out_frame':19})
    assert e.get_state()==before
