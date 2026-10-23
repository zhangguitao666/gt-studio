"""Native source-bound linkage oracle and actual linked-split render behavior."""
import hashlib
import json
from pathlib import Path
import subprocess
import wave

import pytest
from frameforge.engine import Engine, ffmpeg_executable

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def linked_project(tmp_path):
    source=tmp_path/'motion.mp4'
    subprocess.run([ffmpeg_executable(),'-v','error','-y','-f','lavfi','-i','testsrc2=s=160x90:r=24:d=3','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],check=True)
    e=Engine(tmp_path/'editor');e.dispatch('create_project',{'name':'Linked blade','width':160,'height':90})
    m=e.dispatch('import_media',{'path':str(source)})
    v=e.dispatch('append_clip',{'media_id':m['id'],'in_frame':12,'out_frame':60})
    a=e.dispatch('detach_audio',{'clip_id':v['id'],'linked':True})['audio']
    return e,v,a


def normalized_items(e):
    result=[]
    for track in e._timeline()['tracks']:
        for clip in track['clips']:
            linked=[{'kind':other_track['kind'],'start':other['start_frame'],'duration':other['duration_frames']}
                    for other,other_track in e._link_members(clip['id']) if other['id']!=clip['id']]
            result.append({'kind':track['kind'],'start':clip['start_frame'],'duration':clip['duration_frames'],'links':sorted(linked,key=lambda x:(x['kind'],x['start']))})
    return sorted(result,key=lambda x:(x['kind'],x['start']))


def pcm(path):
    with wave.open(str(path)) as f:return f.readframes(f.getnframes())


def rgb(path):
    return subprocess.run([ffmpeg_executable(),'-v','error','-i',str(path),'-an','-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True,check=True).stdout


def test_split_matches_native_links_and_preserves_all_decoded_frames(linked_project,tmp_path):
    e,v,a=linked_project
    reference=json.loads((ROOT/'research/linked-split-runtime.json').read_text())
    assert reference['snapshot']['sha256']=='4c7fff47476cb35ef27d668817dd6193a568612fcd56171015a39eaa1fb3b626'
    native=next(r['case'] for r in reference['records'] if r['case']['action']=='linked_split_after')
    expected=[]
    for item in native['items']:
        links=[{'kind':link['kind'],'start':link['start']-native['origin'],'duration':link['duration']} for link in item['links']]
        expected.append({'kind':item['kind'],'start':item['start']-native['origin'],'duration':item['duration'],'links':sorted(links,key=lambda x:(x['kind'],x['start']))})
    baseline=tmp_path/'before.mov';e.dispatch('render',{'output':str(baseline)})
    before=e.get_state()
    result=e.dispatch('split_clip',{'clip_id':v['id'],'frame':24})
    assert normalized_items(e)==sorted(expected,key=lambda x:(x['kind'],x['start']))
    assert len(result['linked_splits'])==2
    assert result['first']['link_group_id']!=result['second']['link_group_id']
    after=e.get_state()
    e.dispatch('undo');assert e.get_state()==before
    e.dispatch('redo');assert e.get_state()==after
    project=tmp_path/'split.json';e.dispatch('save_project',{'path':str(project)});e.dispatch('open_project',{'path':str(project)})
    rendered=tmp_path/'after.mov';e.dispatch('render',{'output':str(rendered)})
    baseline_rgb, rendered_rgb = rgb(baseline), rgb(rendered)
    if baseline_rgb != rendered_rgb:
        # Keep strict byte equality, but bound diagnostics even under pytest's
        # CI assertion formatter (multi-megabyte difflib can take minutes).
        first = next((i for i, (a, b) in enumerate(zip(baseline_rgb, rendered_rgb)) if a != b), None)
        differences = [abs(a-b) for a,b in zip(baseline_rgb, rendered_rgb)]
        pytest.fail(json.dumps({'baseline_bytes':len(baseline_rgb),'rendered_bytes':len(rendered_rgb),
                                'first_byte':first,'first_frame':first//(160*90*3) if first is not None else None,
                                'first_values':[baseline_rgb[first],rendered_rgb[first]] if first is not None else None,
                                'changed_bytes':sum(d != 0 for d in differences),'max_abs':max(differences,default=0),
                                'mae':sum(differences)/len(differences) if differences else None,
                                'baseline_sha256':hashlib.sha256(baseline_rgb).hexdigest(),
                                'rendered_sha256':hashlib.sha256(rendered_rgb).hexdigest()}))
    basewav=tmp_path/'before.wav'
    e.dispatch('render',{'output':str(basewav)})
    # Delete only the linked tail: prefix A/V survive, with their own group.
    deleted=e.dispatch('ripple_delete',{'clip_id':result['second']['id']})
    assert len(deleted['deleted_clip_ids'])==2
    assert len(normalized_items(e))==2
    assert all(item['start']==0 and item['duration']==24 for item in normalized_items(e))
    prefix=tmp_path/'prefix.wav';e.dispatch('render',{'output':str(prefix)})
    assert pcm(prefix)==pcm(basewav)[:24*2000*4]


@pytest.mark.parametrize('speed,frame',[(50,37),(-100,17),(150,11),(0,19)])
def test_linked_split_rational_timing_and_group_partition(linked_project,speed,frame):
    e,v,a=linked_project
    for clip in (v,a):e.dispatch('set_clip_speed',{'clip_id':clip['id'],'percentage':speed,'ripple':True})
    before=e.get_state()
    result=e.dispatch('split_clip',{'clip_id':a['id'],'frame':frame})
    assert result['first']['id']==a['id']
    assert len(result['linked_splits'])==2
    for item in normalized_items(e):
        assert len(item['links'])==1
        assert item['links'][0]['start']==item['start']
        assert item['links'][0]['duration']==item['duration']
    e.dispatch('undo');assert e.get_state()==before
    for bad in (0,999):
        with pytest.raises(ValueError,match='inside'):e.dispatch('split_clip',{'clip_id':v['id'],'frame':bad})
        assert e.get_state()==before


def test_linked_move_matches_native_nudge_and_keeps_decoded_payload(linked_project,tmp_path):
    e,v,a=linked_project
    reference=json.loads((ROOT/'research/linked-move-runtime.json').read_text())
    assert reference['snapshot']['sha256']=='a64df762f926e208b1298ba2e6cbde0aa48338aed5e358807512ab11fff2e133'
    native={r['case']['action']:r['case'] for r in reference['records']}
    e.dispatch('move_clip',{'clip_id':v['id'],'start_frame':48})
    before=e.get_state()
    baseline=tmp_path/'move-before.mov';e.dispatch('render',{'output':str(baseline)})
    before_wav=tmp_path/'move-before.wav';e.dispatch('render',{'output':str(before_wav)})
    e.dispatch('move_clip',{'clip_id':v['id'],'start_frame':49})
    actual=normalized_items(e)
    original=native['linked_move_after']
    expected=sorted([{'kind':c['kind'],'start':c['start']-original['origin'],'duration':c['duration'],
                      'links':[{'kind':l['kind'],'start':l['start']-original['origin'],'duration':l['duration']} for l in c['links']]}
                     for c in original['items']],key=lambda i:(i['kind'],i['start']))
    assert actual==expected
    after=e.get_state()
    e.dispatch('undo');assert e.get_state()==before
    e.dispatch('redo');assert e.get_state()==after
    moved=tmp_path/'move-after.mov';e.dispatch('render',{'output':str(moved)})
    moved_wav=tmp_path/'move-after.wav';e.dispatch('render',{'output':str(moved_wav)})
    assert rgb(baseline)[48*160*90*3:]==rgb(moved)[49*160*90*3:]
    assert pcm(before_wav)[48*2000*4:]==pcm(moved_wav)[49*2000*4:]
    assert not any(pcm(moved_wav)[:49*2000*4])


def test_linked_move_preserves_offsets_and_rolls_back_peer_conflicts(linked_project):
    e,v,a=linked_project
    e.dispatch('unlink_clips',{'clip_id':v['id']})
    e.dispatch('move_clip',{'clip_id':a['id'],'start_frame':6})
    e.dispatch('link_clips',{'clip_ids':[v['id'],a['id']]})
    e.dispatch('move_clip',{'clip_id':v['id'],'start_frame':10})
    assert e._clip(a['id'])[0]['start_frame']==16
    before=e.get_state()
    with pytest.raises(ValueError):e.dispatch('move_clip',{'clip_id':a['id'],'start_frame':0})
    assert e.get_state()==before
    audio_track=e._clip(a['id'])[1]
    e.dispatch('append_clip',{'media_id':v['media_id'],'track_id':audio_track['id'],'start_frame':70,'in_frame':0,'out_frame':12})
    before=e.get_state()
    with pytest.raises(ValueError,match='overlap'):
        e.dispatch('move_clip',{'clip_id':v['id'],'start_frame':24})
    assert e.get_state()==before
    e.dispatch('undo')
    assert len(e._clip(a['id'])[1]['clips'])==1  # Rejected move did not consume the prior undo entry.
    video_track=e.dispatch('add_track',{'kind':'video'})
    e.dispatch('move_clip',{'clip_id':v['id'],'start_frame':20,'track_id':video_track['id']})
    assert e._clip(v['id'])[1]['id']==video_track['id']
    assert e._clip(a['id'])[0]['start_frame']==26
    before=e.get_state()
    with pytest.raises(ValueError,match='same-kind'):
        e.dispatch('move_clip',{'clip_id':v['id'],'start_frame':20,'track_id':audio_track['id']})
    assert e.get_state()==before


def test_linked_move_updates_transition_only_when_both_endpoints_follow(linked_project):
    e,v,a=linked_project
    second=e.dispatch('append_clip',{'media_id':v['media_id'],'in_frame':12,'out_frame':60})
    audio=e.dispatch('detach_audio',{'clip_id':second['id'],'linked':True})['audio']
    transition=e.dispatch('add_transition',{'clip_id':v['id']})
    before=e.get_state()
    with pytest.raises(ValueError,match='transition'):
        e.dispatch('move_clip',{'clip_id':v['id'],'start_frame':120})
    assert e.get_state()==before
    e.dispatch('link_clips',{'clip_ids':[v['id'],a['id'],second['id'],audio['id']]})
    e.dispatch('move_clip',{'clip_id':v['id'],'start_frame':12})
    shifted=e._timeline()['transitions'][0]
    assert shifted['id']==transition['id']
    assert (shifted['start_frame'],shifted['cut_frame'],shifted['end_frame'])==(54,60,66)
    saved=e.get_state()
    e.dispatch('undo');e.dispatch('redo');assert e.get_state()==saved
