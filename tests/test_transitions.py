"""Transition integrity and actual captured native Cross Dissolve cases."""
import copy
import pytest
from frameforge.engine import clip_duration
from frameforge.transitions import validate_transitions


@pytest.fixture
def transition_model():
    return {'tracks': [{'id':'video1','kind':'video','clips':[
        {'id':'left','start_frame':0,'in_frame':12,'out_frame':60,'duration_frames':48},
        {'id':'right','start_frame':48,'in_frame':12,'out_frame':60,'duration_frames':48}]}],
        'transitions':[{'id':'dissolve1','type':'Cross Dissolve','track_id':'video1',
                        'left_clip_id':'left','right_clip_id':'right','alignment':'center',
                        'duration_frames':12,'cut_frame':48,'start_frame':42,'end_frame':54}]}


def test_transition_validation_is_pure_and_legacy_missing_list_is_empty(transition_model):
    before = copy.deepcopy(transition_model)
    result = validate_transitions(transition_model,clip_duration)
    assert result == transition_model['transitions']
    result[0]['duration_frames'] = 99
    assert transition_model == before
    assert validate_transitions({'tracks':[]},clip_duration) == []


@pytest.mark.parametrize('mutation', ['missing_clip','different_track','nonadjacent','invalid_duration','duplicate_id','duplicate_cut','unknown_type','window_mismatch','bool_frame'])
def test_transition_integrity_rejects_corrupt_records(transition_model, mutation):
    t = transition_model['transitions'][0]
    if mutation == 'missing_clip':
        t['right_clip_id'] = 'missing'
    elif mutation == 'different_track':
        t['track_id'] = 'missing'
    elif mutation == 'nonadjacent':
        transition_model['tracks'][0]['clips'][1]['start_frame'] = 49
    elif mutation == 'invalid_duration':
        t['duration_frames'] = 0
    elif mutation == 'duplicate_id':
        transition_model['transitions'].append(dict(t))
    elif mutation == 'duplicate_cut':
        transition_model['transitions'].append(dict(t,id='second'))
    elif mutation == 'unknown_type':
        t['type'] = 'Not Implemented'
    elif mutation == 'window_mismatch':
        t['end_frame'] += 1
    elif mutation == 'bool_frame':
        t['start_frame'] = True
    before = copy.deepcopy(transition_model)
    with pytest.raises(ValueError):
        validate_transitions(transition_model,clip_duration)
    assert transition_model == before


@pytest.fixture
def colored_sources(tmp_path):
    from frameforge.engine import ffmpeg_executable
    import subprocess
    paths=[]
    for color in ('red','blue','lime','yellow'):
        path=tmp_path/(color+'.mov')
        made=subprocess.run([ffmpeg_executable(),'-v','error','-y','-f','lavfi','-i',f'color={color}:s=160x90:r=24:d=3','-c:v','qtrle',str(path)],capture_output=True)
        assert made.returncode == 0, made.stderr.decode()
        paths.append(path)
    return paths


def editing_pair(tmp_path, sources):
    from frameforge.engine import Engine
    e=Engine(tmp_path/'project')
    e.dispatch('create_project',{'width':160,'height':90})
    media=[e.dispatch('import_media',{'path':str(path)}) for path in sources]
    first=e.dispatch('append_clip',{'media_id':media[0]['id'],'in_frame':12,'out_frame':60})
    second=e.dispatch('append_clip',{'media_id':media[1]['id'],'in_frame':12,'out_frame':60})
    return e,media,first,second


def center_pixels(path):
    from frameforge.engine import ffmpeg_executable
    import subprocess
    result=subprocess.run([ffmpeg_executable(),'-v','error','-i',str(path),'-an','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    size=160*90*3
    offset=(45*160+80)*3
    return [tuple(result.stdout[i+offset:i+offset+3]) for i in range(0,len(result.stdout),size)]


@pytest.mark.parametrize('name,alignment,duration,position', [('center12','center',12,'end'),('left12','left',12,'end'),('right12','right',12,'end'),('center11','center',11,'end'),('startcenter12','center',12,'start')])
def test_native_window_actions_midpoint_curve_and_persistence(tmp_path,colored_sources,name,alignment,duration,position):
    import json
    from pathlib import Path
    from frameforge.engine import Engine
    evidence=json.loads((Path(__file__).resolve().parents[1]/'research/transition-runtime-v1.json').read_text())
    assert evidence['snapshot']['sha256']=='371dc0a30fb478581048e3def0cc0ed7587c8d839871c66283a3a3592299c7dc'
    native=next(row['case'] for row in evidence['records'] if row['case']['timeline'].endswith('_'+name))
    native_transition=next(item for item in native['after']['items'] if item['kind']=='transition')
    baseline=native['after']['first']['start']
    e,media,left,right=editing_pair(tmp_path,colored_sources)
    before=e.get_state()
    transition=e.dispatch('add_transition',{'clip_id':left['id'] if position=='end' else right['id'],'position':position,'alignment':alignment,'duration_frames':duration})
    assert transition['start_frame']==native_transition['start']-baseline
    assert transition['end_frame']==native_transition['finish']-baseline
    assert e._clip(left['id'])[0]['duration_frames']==48
    assert e._clip(right['id'])[0]['start_frame']==48
    output=tmp_path/'dissolve.mov'
    e.dispatch('render',{'output':str(output)})
    pixels=center_pixels(output)
    assert len(pixels)==96
    start,end=transition['start_frame'],transition['end_frame']
    assert pixels[start-1][0]>245 and pixels[end][2]>245
    for i,(r,g,b) in enumerate(pixels[start:end]):
        weight=(i+.5)/duration
        assert r==pytest.approx(253*(1-weight),abs=6)
        assert b==pytest.approx(253*weight,abs=6)
        assert g<8
    path=e.dispatch('save_project')['path']
    reopened=Engine(tmp_path/'reopened')
    reopened.dispatch('open_project',{'path':path})
    assert reopened.get_state()==e.get_state()
    e.dispatch('undo')
    assert e.get_state()==before
    e.dispatch('redo')
    assert e._timeline()['transitions'][0]['id']==transition['id']
    e.dispatch('delete_transition',{'transition_id':transition['id']})
    assert e._timeline()['transitions']==[]


def test_insufficient_handles_and_structural_edits_rollback(tmp_path,colored_sources):
    from frameforge.engine import Engine
    e,media,left,right=editing_pair(tmp_path,colored_sources)
    transition=e.dispatch('add_transition',{'clip_id':left['id']})
    before=e.get_state()
    undo_count=len(e._undo)
    for action,args in [('move_clip',{'clip_id':right['id'],'start_frame':60}),('split_clip',{'clip_id':left['id'],'frame':20}),('set_clip_speed',{'clip_id':left['id'],'percentage':200,'ripple':True}),('add_transition',{'clip_id':left['id']})]:
        with pytest.raises(ValueError):e.dispatch(action,args)
        assert e.get_state()==before and len(e._undo)==undo_count
    e.dispatch('delete_transition',{'transition_id':transition['id']})
    e.dispatch('move_clip',{'clip_id':right['id'],'start_frame':60})
    hard=Engine(tmp_path/'nohandles')
    hard.dispatch('create_project',{'width':160,'height':90})
    imported=hard.dispatch('import_media',{'path':str(colored_sources[0])})
    first=hard.dispatch('append_clip',{'media_id':imported['id'],'out_frame':72})
    hard.dispatch('append_clip',{'media_id':imported['id'],'out_frame':72})
    state=hard.get_state()
    with pytest.raises(ValueError,match='handles'):hard.dispatch('add_transition',{'clip_id':first['id']})
    assert hard.get_state()==state


@pytest.mark.parametrize('ripple',[False,True])
def test_native_video_clip_deletion_cascades_transition_and_undo(tmp_path,colored_sources,ripple):
    import json
    from pathlib import Path
    evidence=json.loads((Path(__file__).resolve().parents[1]/'research/transition-deletion-runtime.json').read_text())
    assert len(evidence['records'])==3
    native=next(row['case'] for row in evidence['records'] if row['case']['action']=='clip' and row['case']['ripple'] is ripple)
    assert native['completed'] and native['after']['delete_return'] is True
    e,media,left,right=editing_pair(tmp_path,colored_sources)
    transition=e.dispatch('add_transition',{'clip_id':left['id']})
    before=e.get_state()
    e.dispatch('ripple_delete' if ripple else 'delete_clip',{'clip_id':left['id']})
    assert e._timeline()['transitions']==[]
    baseline=native['before']['video'][0]['start']
    remaining=e._clip(right['id'])[0]
    assert (remaining['start_frame'],remaining['duration_frames'])==(native['after']['video'][0]['start']-baseline,native['after']['video'][0]['duration'])
    e.dispatch('undo')
    assert e.get_state()==before
    e.dispatch('redo')
    assert e._timeline()['transitions']==[]


def test_dissolve_uses_moving_source_handles_not_repeated_edge_frames(tmp_path):
    from frameforge.engine import Engine,ffmpeg_executable
    import subprocess
    paths=[]
    red=[20+(47*i%210) for i in range(72)]
    blue=[20+(53*i%210) for i in range(72)]
    for name,values in [('red',red),('blue',blue)]:
        path=tmp_path/(name+'.mov')
        raw=b''.join(bytes((v,0,0) if name=='red' else (0,0,v))*(160*90) for v in values)
        made=subprocess.run([ffmpeg_executable(),'-v','error','-y','-f','rawvideo','-pixel_format','rgb24','-video_size','160x90','-framerate','24','-i','-','-c:v','qtrle',str(path)],input=raw,capture_output=True)
        assert made.returncode==0,made.stderr.decode()
        paths.append(path)
    e,media,left,right=editing_pair(tmp_path,paths)
    e.dispatch('add_transition',{'clip_id':left['id']})
    output=tmp_path/'moving-handles.mov'
    e.dispatch('render',{'output':str(output)})
    pixels=center_pixels(output)
    for i,(r,g,b) in enumerate(pixels[42:54]):
        weight=(i+.5)/12
        assert r==pytest.approx(red[54+i]*(1-weight),abs=6)
        assert b==pytest.approx(blue[6+i]*weight,abs=6)
        assert g<8


def test_pair_blends_before_lower_background_and_upper_track(tmp_path,colored_sources):
    from frameforge.engine import Engine
    e=Engine(tmp_path/'layers')
    e.dispatch('create_project',{'width':160,'height':90})
    red,blue,lime,yellow=[e.dispatch('import_media',{'path':str(path)}) for path in colored_sources]
    e.dispatch('append_clip',{'media_id':lime['id'],'out_frame':72})
    e.dispatch('append_clip',{'media_id':lime['id'],'out_frame':24})
    pair=e.dispatch('add_track',{'kind':'video'})
    left=e.dispatch('append_clip',{'media_id':red['id'],'track_id':pair['id'],'in_frame':12,'out_frame':60})
    right=e.dispatch('append_clip',{'media_id':blue['id'],'track_id':pair['id'],'in_frame':12,'out_frame':60})
    for c in (left,right):e.dispatch('set_clip_properties',{'clip_id':c['id'],'opacity':.5})
    e.dispatch('add_transition',{'clip_id':left['id']})
    upper=e.dispatch('add_track',{'kind':'video'})
    e.dispatch('append_clip',{'media_id':yellow['id'],'track_id':upper['id'],'out_frame':2,'start_frame':44})
    output=tmp_path/'layers.mov'
    e.dispatch('render',{'output':str(output)})
    pixels=center_pixels(output)
    for frame in range(42,54):
        r,g,b=pixels[frame]
        if frame in (44,45):
            assert r>240 and g>240 and b<10
        else:
            assert g==pytest.approx(127,abs=6)
            weight=(frame-42+.5)/12
            assert r==pytest.approx(126*(1-weight),abs=8)
            assert b==pytest.approx(126*weight,abs=8)


def test_dissolve_preserves_fractional_retime_handle_mapping(tmp_path,colored_sources):
    e,media,left,right=editing_pair(tmp_path,colored_sources)
    # 50% non-ripple keeps48frames but consumes24sourceframes. Incoming source12
    # has sufficient prehandles for its3source-frame centered extension.
    e.dispatch('set_clip_speed',{'clip_id':left['id'],'percentage':50})
    e.dispatch('set_clip_speed',{'clip_id':right['id'],'percentage':150})
    # Faster right clip is source-boundary limited to40frames; the cut stays48.
    transition=e.dispatch('add_transition',{'clip_id':left['id'],'duration_frames':11})
    first=e._transition_segment(e._clip(left['id'])[0],transition)
    second=e._transition_segment(e._clip(right['id'])[0],transition)
    assert first['source_start']=={'num':33,'den':1}
    assert first['source_end']=={'num':77,'den':2}
    assert second['source_start']=={'num':3,'den':1}
    assert second['source_end']=={'num':39,'den':2}
    output=tmp_path/'retimed-dissolve.mov'
    e.dispatch('render',{'output':str(output)})
    pixels=center_pixels(output)
    assert len(pixels)==88
    assert pixels[42][0]>225 and pixels[52][2]>225


def test_native_upstream_ripple_moves_surviving_transition_window(tmp_path,colored_sources):
    import json
    from pathlib import Path
    from frameforge.engine import Engine
    evidence=json.loads((Path(__file__).resolve().parents[1]/'research/transition-upstream-runtime.json').read_text())
    assert evidence['snapshot']['sha256']=='802ae07a1729d65f20c9d4fa0100d12baa93c7a14f5820cb0ccbfb6ad733e925'
    native=evidence['records'][0]['case']
    assert native['completed'] and native['after']['delete_return'] is True
    e=Engine(tmp_path/'upstream')
    e.dispatch('create_project',{'width':160,'height':90})
    red=e.dispatch('import_media',{'path':str(colored_sources[0])})
    blue=e.dispatch('import_media',{'path':str(colored_sources[1])})
    first=e.dispatch('append_clip',{'media_id':red['id'],'in_frame':12,'out_frame':60})
    second=e.dispatch('append_clip',{'media_id':blue['id'],'in_frame':12,'out_frame':60})
    third=e.dispatch('append_clip',{'media_id':red['id'],'in_frame':12,'out_frame':60})
    transition=e.dispatch('add_transition',{'clip_id':second['id']})
    assert (transition['start_frame'],transition['cut_frame'],transition['end_frame'])==(90,96,102)
    other=e.dispatch('add_track',{'kind':'video'})
    unrelated=e.dispatch('append_clip',{'media_id':blue['id'],'track_id':other['id'],'in_frame':12,'out_frame':60,'start_frame':144})
    e.dispatch('append_clip',{'media_id':red['id'],'track_id':other['id'],'in_frame':12,'out_frame':60,'start_frame':192})
    unaffected=e.dispatch('add_transition',{'clip_id':unrelated['id']})
    before=e.get_state()
    e.dispatch('ripple_delete',{'clip_id':first['id']})
    moved=next(t for t in e._timeline()['transitions'] if t['id']==transition['id'])
    assert (moved['start_frame'],moved['cut_frame'],moved['end_frame'])==(42,48,54)
    assert next(t for t in e._timeline()['transitions'] if t['id']==unaffected['id'])==unaffected
    original_track=e._timeline()['tracks'][0]
    actual=[{'kind':'video','start':c['start_frame'],'duration':c['duration_frames']}for c in original_track['clips']]
    actual.append({'kind':'transition','start':moved['start_frame'],'duration':moved['duration_frames']})
    actual.sort(key=lambda item:item['start'])
    origin=native['before'][0]['start']
    expected=[{'kind':item['kind'],'start':item['start']-origin,'duration':item['duration']}for item in native['after']['items']]
    assert actual==expected
    output=tmp_path/'upstream-dissolve.mov'
    e.dispatch('render',{'output':str(output)})
    pixels=center_pixels(output)
    assert pixels[41][2]>245 and pixels[54][0]>245
    for i,(r,g,b) in enumerate(pixels[42:54]):
        assert r==pytest.approx(253*(i+.5)/12,abs=6)
        assert b==pytest.approx(253*(1-(i+.5)/12),abs=6)
    e.dispatch('undo')
    assert e.get_state()==before
    e.dispatch('redo')
    assert next(t for t in e._timeline()['transitions'] if t['id']==transition['id'])==moved
