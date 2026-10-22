"""Track stream masks and locked direct/linked edits use real media/state."""
import json
from pathlib import Path
import pytest
from frameforge.engine import Engine
from test_linked_split import linked_project,rgb,pcm
from test_engine import media,setup_project,pixel


@pytest.mark.parametrize('action,params',[
 ('move_clip',{'start_frame':6}),('trim_clip',{'in_frame':18,'out_frame':42}),
 ('trim_clip_edge',{'edge':'end','frame':24}),('set_clip_speed',{'percentage':50,'ripple':True}),
 ('split_clip',{'frame':24}),('ripple_delete',{}),('unlink_clips',{}),
])
def test_locked_audio_blocks_indirect_linked_edits_and_preserves_undo(linked_project,action,params):
    e,v,a=linked_project;track=e._clip(a['id'])[1]
    e.dispatch('set_track_state',{'track_id':track['id'],'locked':True})
    before=e.get_state()
    with pytest.raises(ValueError,match='locked'):
        e.dispatch(action,{'clip_id':v['id'],**params})
    assert e.get_state()==before
    e.dispatch('undo');assert not e._track(track['id'])['locked']
    assert e._clip(v['id'])[0]['link_group_id']==e._clip(a['id'])[0]['link_group_id']


@pytest.mark.parametrize('action', ['delete_clip','set_clip_properties','append_clip','link_clips'])
def test_locked_track_rejects_direct_clip_and_link_mutations(linked_project,action):
    e,v,a=linked_project;track=e._clip(a['id'])[1]
    e.dispatch('set_track_state',{'track_id':track['id'],'locked':True});before=e.get_state()
    args={'delete_clip':{'clip_id':a['id']},'set_clip_properties':{'clip_id':a['id'],'properties':{'volume':.2}},
          'append_clip':{'media_id':v['media_id'],'track_id':track['id'],'start_frame':48,'in_frame':12,'out_frame':60},
          'link_clips':{'clip_ids':[v['id'],a['id']]}}[action]
    with pytest.raises(ValueError,match='locked'):e.dispatch(action,args)
    assert e.get_state()==before


def test_track_masks_keep_picture_and_sound_independent(linked_project,tmp_path):
    e,v,a=linked_project;vt=e._clip(v['id'])[1];at=e._clip(a['id'])[1]
    base=tmp_path/'base.mov';basewav=tmp_path/'base.wav'
    e.dispatch('render',{'output':str(base)});e.dispatch('render',{'output':str(basewav)})
    e.dispatch('set_track_state',{'track_id':at['id'],'enabled':False,'locked':True})
    visible=tmp_path/'visible.mov';silent=tmp_path/'silent.wav'
    e.dispatch('render',{'output':str(visible)});e.dispatch('render',{'output':str(silent)})
    assert rgb(base)==rgb(visible) and not any(pcm(silent))
    # Output enable is adjustable even while editing is locked.
    e.dispatch('set_track_state',{'track_id':at['id'],'enabled':True})
    e.dispatch('set_track_state',{'track_id':vt['id'],'enabled':False})
    black=tmp_path/'black.mov';audible=tmp_path/'audible.wav'
    e.dispatch('render',{'output':str(black)});e.dispatch('render',{'output':str(audible)})
    assert len(rgb(black))==48*160*90*3 and max(rgb(black))<10
    assert pcm(audible)==pcm(basewav)


def test_disabled_video_keeps_embedded_audio_and_hidden_top_reveals_lower(tmp_path,media):
    e,m,v=setup_project(tmp_path,media);track=e._clip(v['id'])[1]
    before=tmp_path/'before.wav';e.dispatch('render',{'output':str(before)})
    e.dispatch('set_track_state',{'track_id':track['id'],'enabled':False})
    after=tmp_path/'after.wav';black=tmp_path/'black.mov'
    e.dispatch('render',{'output':str(after)});e.dispatch('render',{'output':str(black)})
    assert pcm(before)==pcm(after) and max(pixel(black,.5))<10
    e.dispatch('set_track_state',{'track_id':track['id'],'enabled':True})
    upper=e.dispatch('add_track',{'kind':'video'});blue=e.dispatch('import_media',{'path':str(media[1])})
    e.dispatch('append_clip',{'media_id':blue['id'],'track_id':upper['id']})
    e.dispatch('set_track_state',{'track_id':upper['id'],'enabled':False})
    output=tmp_path/'lower.mov';e.dispatch('render',{'output':str(output)})
    assert pixel(output,.5)[0]>240 and pixel(output,.5)[2]<10


def test_disabled_dissolve_is_not_composited_and_lock_covers_transitions(tmp_path,media):
    e=Engine(tmp_path);e.dispatch('create_project',{'name':'Masked dissolve','width':160,'height':90})
    clips=[]
    for path in media:
        m=e.dispatch('import_media',{'path':str(path)})
        clips.append(e.dispatch('append_clip',{'media_id':m['id'],'in_frame':6,'out_frame':18}))
    transition=e.dispatch('add_transition',{'clip_id':clips[0]['id'],'duration_frames':12})
    track=e._clip(clips[0]['id'])[1]
    e.dispatch('set_track_state',{'track_id':track['id'],'enabled':False,'locked':True})
    before=e.get_state()
    with pytest.raises(ValueError,match='locked'):e.dispatch('delete_transition',{'transition_id':transition['id']})
    assert e.get_state()==before
    output=tmp_path/'no-dissolve.mov';e.dispatch('render',{'output':str(output)})
    assert max(rgb(output))<10
    e.dispatch('set_track_state',{'track_id':track['id'],'locked':False})
    e.dispatch('delete_transition',{'transition_id':transition['id']})
    e.dispatch('set_track_state',{'track_id':track['id'],'locked':True})
    before=e.get_state()
    with pytest.raises(ValueError,match='locked'):e.dispatch('add_transition',{'clip_id':clips[0]['id']})
    assert e.get_state()==before


def test_track_flags_migrate_validate_persist_and_skip_unused_sources(linked_project,tmp_path):
    e,v,a=linked_project
    project=tmp_path/'legacy.json';e.dispatch('save_project',{'path':str(project)})
    data=json.loads(project.read_text())
    for t in data['timelines'][0]['tracks']:t.pop('enabled');t.pop('locked')
    project.write_text(json.dumps(data));e.dispatch('open_project',{'path':str(project)})
    assert all(t['enabled'] and not t['locked'] for t in e._timeline()['tracks'])
    for track in e._timeline()['tracks']:e.dispatch('set_track_state',{'track_id':track['id'],'enabled':False})
    # Explicit audio items and their video owner have no enabled contribution.
    Path(e._media(v['media_id'])['path']).unlink()
    output=tmp_path/'offline-disabled.mov';e.dispatch('render',{'output':str(output)})
    assert len(rgb(output))==48*160*90*3 and max(rgb(output))<10
    e.dispatch('save_project',{'path':str(project)});e.dispatch('open_project',{'path':str(project)})
    assert all(not t['enabled'] for t in e._timeline()['tracks'])
    before=e.get_state();bad=json.loads(project.read_text());bad['timelines'][0]['tracks'][0]['locked']=1
    project.write_text(json.dumps(bad))
    with pytest.raises(ValueError,match='flag'):e.dispatch('open_project',{'path':str(project)})
    assert e.get_state()==before
