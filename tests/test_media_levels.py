"""Captured native source-level cases and preservation of out-of-range node samples."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import subprocess

import pytest
from frameforge.engine import Engine, ffmpeg_executable
from frameforge.fusion import compile_graph
from test_fusion import real_project, add, connect, pixels
from test_transitions import colored_sources
from scripts.verify_fusion_image_precision import make_source

CASES=json.loads((Path(__file__).parent/'fixtures/fusion-media-levels.json').read_text())['cases']


@pytest.fixture(scope='module')
def native_rgb24_source(tmp_path_factory):
    return make_source(tmp_path_factory.mktemp('native-level-source'),has_alpha=False)


@pytest.mark.parametrize('case',CASES,ids=[c['id'] for c in CASES])
def test_captured_native_media_levels_and_merge_blend(tmp_path,native_rgb24_source,case):
    e=Engine(tmp_path/'project')
    e.dispatch('create_project',{'name':'Native source-level case','width':640,'height':360,'fps':24})
    media=e.dispatch('import_media',{'path':str(native_rgb24_source)})
    clip=e.dispatch('append_clip',{'media_id':media['id'],'out_frame':12})['id']
    assert media['video_codec']=='qtrle' and media['pixel_format']=='rgb24'
    e.dispatch('set_media_data_level',{'media_id':media['id'],'mode':case['mode']})
    blue=add(e,clip,'Background',Blue=1,Alpha=case['alpha'])
    merge=add(e,clip,'Merge',Blend=case['blend'])
    connect(e,clip,merge,'Background','MediaIn1');connect(e,clip,merge,'Foreground',blue);connect(e,clip,'MediaOut1','Input',merge)
    output=tmp_path/'levels.mov';e.dispatch('render',{'output':str(output)})
    raw=pixels(output);assert len(raw)==12*640*360*3
    assert hashlib.sha256(raw).hexdigest()==case['native_decoded_sha256'], f'{case["id"]}: full native RGB sequence differs'


def test_data_level_shared_persistence_undo_and_invalid_rollback(tmp_path,colored_sources):
    e,clip=real_project(tmp_path,colored_sources);media=e.project['media'][0]
    track=e.dispatch('add_track',{'kind':'video'})
    e.dispatch('append_clip',{'media_id':media['id'],'track_id':track['id'],'out_frame':12})
    before=copy.deepcopy(e.get_state())
    e.dispatch('set_media_data_level',{'media_id':media['id'],'mode':'Full'})
    assert e._media(media['id'])['data_level']=='Full'
    e.dispatch('undo');assert e.get_state()==before
    e.dispatch('redo');saved=tmp_path/'saved.json';e.dispatch('save_project',{'path':str(saved)})
    other=Engine(tmp_path/'reopened');other.dispatch('open_project',{'path':str(saved)})
    assert other._media(media['id'])['data_level']=='Full'
    stable=copy.deepcopy((e.project,e._undo,e._redo))
    with pytest.raises(ValueError):e.dispatch('set_media_data_level',{'media_id':media['id'],'mode':'unknown'})
    assert (e.project,e._undo,e._redo)==stable
    malformed=json.loads(saved.read_text());malformed['media'][0]['data_level']='unknown';saved.write_text(json.dumps(malformed))
    with pytest.raises(ValueError):other.dispatch('open_project',{'path':str(saved)})
    assert other._media(media['id'])['data_level']=='Full'


def test_float_node_transform_retains_negative_and_superwhite_video_levels(tmp_path,colored_sources):
    e,clip_id=real_project(tmp_path,colored_sources)
    transform=add(e,clip_id,'Transform',Size=.5,CenterX=.75,CenterY=.75,Angle=90)
    connect(e,clip_id,transform,'Input','MediaIn1');connect(e,clip_id,'MediaOut1','Input',transform)
    clip=e._clip(clip_id)[0];media=e.project['media'][0]
    filters,label=compile_graph(clip['fusion_graph'],'[0:v]'+e._video_selection(clip,e.project),e.project,12,'float_test',media=media)
    raw=subprocess.check_output([ffmpeg_executable(),'-v','error','-i',media['path'],'-filter_complex',';'.join(filters),'-map','['+label+']','-frames:v','1','-f','rawvideo','-pix_fmt','gbrapf32le','-'])
    samples=struct.unpack('<'+'f'*(len(raw)//4),raw);at=8*32+24
    green,blue,red,alpha=[samples[plane*32*32+at] for plane in range(4)]
    assert red>1.05 and green<-.07 and blue<-.07 and alpha==1
    assert all(samples[plane*32*32+31*32]==0 for plane in range(4))
