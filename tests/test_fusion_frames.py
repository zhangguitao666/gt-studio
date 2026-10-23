import copy
import struct
import subprocess

import pytest

from frameforge.engine import Engine, ffmpeg_executable
from test_fusion import model, add, connect


def rgba(path):
    return subprocess.run([ffmpeg_executable(), '-v', 'error', '-i', str(path), '-pix_fmt', 'rgba64le', '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout


def sample(raw, x=16, y=16):
    offset=(y*32+x)*8
    return struct.unpack('<4H', raw[offset:offset+8])


def test_checkpoint_preserves_rgba16_and_is_independent_of_grade_and_history(tmp_path):
    e,clip=model(tmp_path)
    bg=add(e,clip,'Background',Red=0.125,Green=0.375,Blue=0.625,Alpha=0.5)
    e.dispatch('set_clip_properties',{'clip_id':clip,'exposure':-5,'opacity':0,'scale':0.5})
    e.dispatch('set_track_state',{'track_id':e.project['timelines'][0]['tracks'][0]['id'],'locked':True})
    before=copy.deepcopy((e.project,e._undo,e._redo))
    path=tmp_path/'node.png'
    result=e.dispatch('render_fusion_frame',{'clip_id':clip,'node_id':bg,'frame':23,'output':str(path)})
    assert result['channels']=='RGBA16' and result['width']==result['height']==32
    assert len(rgba(path))==32*32*8
    assert sample(rgba(path))==pytest.approx((8191,24575,40959,32767),abs=1)
    assert (e.project,e._undo,e._redo)==before
    # The source is deliberately absent: the selected generator has no MediaIn dependency.
    assert not (tmp_path/'not-opened.mov').exists()


def test_selected_branch_can_render_when_the_main_output_is_incomplete(tmp_path):
    e,clip=model(tmp_path)
    bg=add(e,clip,'Background',Blue=1,Alpha=0.5)
    connect(e,clip,'MediaOut1','Input')
    image=tmp_path/'branch.png'
    e.dispatch('render_fusion_frame',{'clip_id':clip,'node_id':bg,'output':str(image)})
    assert sample(rgba(image))==(0,0,65535,32768)
    before=image.read_bytes()
    with pytest.raises(ValueError,match='Incomplete'):
        e.dispatch('render_fusion_frame',{'clip_id':clip,'output':str(image)})
    assert image.read_bytes()==before


@pytest.mark.parametrize('arguments',[{'frame':24},{'frame':-1},{'frame':0.5},{'frame':True},{'node_id':'missing'}])
def test_checkpoint_failure_preserves_state_history_and_existing_file(tmp_path,arguments):
    e,clip=model(tmp_path);path=tmp_path/'keep.png';path.write_bytes(b'keep')
    before=copy.deepcopy((e.project,e._undo,e._redo))
    with pytest.raises(ValueError):e.dispatch('render_fusion_frame',{'clip_id':clip,'output':str(path),**arguments})
    assert path.read_bytes()==b'keep' and (e.project,e._undo,e._redo)==before


def test_source_collision_and_invalid_output_extension_are_rejected(tmp_path):
    e,clip=model(tmp_path);source=tmp_path/'original.png';source.write_bytes(b'original')
    e.project['media'][0]['path']=str(source)
    bg=add(e,clip,'Background',Blue=1)
    for path in (source,tmp_path/'unsupported.mov'):
        with pytest.raises(ValueError):e.dispatch('render_fusion_frame',{'clip_id':clip,'node_id':bg,'output':str(path)})
    assert source.read_bytes()==b'original'


def test_failed_decoder_preserves_existing_file_and_cleans_temporary(tmp_path):
    e,clip=model(tmp_path);image=tmp_path/'keep.png';image.write_bytes(b'keep')
    with pytest.raises(ValueError,match='checkpoint render failed'):
        e.dispatch('render_fusion_frame',{'clip_id':clip,'output':str(image)})
    assert image.read_bytes()==b'keep'
    assert not list(tmp_path.glob('.gt-node-*'))


@pytest.mark.parametrize('speed,frame,source_frame',[(100,5,5),(200,5,10),(-100,5,18)])
def test_media_in_frame_obeys_source_mapping_after_retime(tmp_path,speed,frame,source_frame):
    source=tmp_path/'coded.mkv'
    subprocess.run([ffmpeg_executable(),'-v','error','-y','-f','lavfi','-i','nullsrc=s=32x32:r=24:d=1,format=gbrp,geq=r=N*8:g=0:b=0','-c:v','ffv1',str(source)],check=True)
    e=Engine(tmp_path/'project');e.dispatch('create_project',{'width':32,'height':32})
    media=e.dispatch('import_media',{'path':str(source)})
    clip=e.dispatch('append_clip',{'media_id':media['id'],'out_frame':24})['id']
    if speed!=100:e.dispatch('set_clip_speed',{'clip_id':clip,'percentage':speed,'ripple':True})
    path=tmp_path/'frame.png';e.dispatch('render_fusion_frame',{'clip_id':clip,'frame':frame,'output':str(path)})
    red,green,blue,alpha=sample(rgba(path))
    assert red==pytest.approx(source_frame*8*257,abs=257)
    # Source/format negotiation can quantize the opaque endpoint by a few
    # 16-bit levels; it must remain opaque to at least 12-bit precision.
    assert green<=16 and blue<=16 and alpha>=65520
