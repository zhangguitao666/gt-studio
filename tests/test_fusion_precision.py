import copy
import hashlib
import json
from pathlib import Path
import struct
import subprocess

import pytest

from frameforge.engine import Engine, ffmpeg_executable
from frameforge.fusion import rgba8_to_rgba16, rgba16_to_float, rgb16_without_alpha
from scripts.verify_fusion_image_precision import FIXTURE, make_source, build_case
from test_fusion import model, add
from test_fusion_frames import rgba


REFERENCE=json.loads(FIXTURE.read_text())


@pytest.fixture(scope='module')
def precision_source(tmp_path_factory):
    work=tmp_path_factory.mktemp('precision-source')
    return {'argb':make_source(work),'rgb24':make_source(work,has_alpha=False)}


@pytest.mark.parametrize('case',REFERENCE['cases'],ids=lambda c:c['name'])
def test_native_image_precision_entire_rgba16_planes(tmp_path,precision_source,case):
    e=Engine(tmp_path/'project')
    def call(action,**arguments):return e.dispatch(action,arguments)
    clip=build_case(call,case,precision_source[case.get('source_pixel_format','argb')])
    saved=e.dispatch('save_project')['path'];e.dispatch('open_project',{'path':saved})
    before=copy.deepcopy((e.project,e._undo,e._redo))
    for frame in (0,case['frames']-1):
        output=tmp_path/(str(frame)+'.png')
        e.dispatch('render_fusion_frame',{'clip_id':clip,'frame':frame,'output':str(output)})
        raw=rgba(output)
        assert hashlib.sha256(raw).hexdigest()==case['native_rgba64le_frame0_sha256'],(case['name'],frame)
    assert (e.project,e._undo,e._redo)==before


@pytest.mark.parametrize('depth',[-1,5,1.5,True,float('nan'),'4'])
def test_invalid_depth_is_transactional(tmp_path,depth):
    e,clip=model(tmp_path);before=copy.deepcopy((e.project,e._undo,e._redo))
    with pytest.raises(ValueError):add(e,clip,'Background',Depth=depth)
    assert (e.project,e._undo,e._redo)==before


def test_legacy_implicit_depth_is_read_pure_and_survives_save_reopen(tmp_path):
    e,clip=model(tmp_path);bg=add(e,clip,'Background',Alpha=.5)
    graph=e.get_fusion_graph(clip)['graph'];node=next(n for n in graph['nodes'] if n['id']==bg)
    assert 'Depth' not in node['parameters']
    before=copy.deepcopy((e.project,e._undo,e._redo))
    assert e.get_fusion_graph(clip)['node_catalog']['Background']['parameters']['Depth'][0]==0
    assert (e.project,e._undo,e._redo)==before
    p=e.dispatch('save_project')['path'];raw=Path(p).read_bytes();e.dispatch('open_project',{'path':p})
    assert e.project==before[0] and Path(p).read_bytes()==raw


@pytest.mark.parametrize('has_alpha',[False,True])
@pytest.mark.parametrize('rgb_tagged',[False,True])
def test_rgb8_and_alpha_expand_as_unorm_without_channel_bias(has_alpha,rgb_tagged):
    pixels=[(i,(i*7)%256,255-i,(i*13)%256) for i in range(256)]*2
    raw=bytes(v for pixel in pixels for v in (pixel if has_alpha else pixel[:3]))
    filters=(["[0:v]setparams=colorspace=gbr[tagged]"] if rgb_tagged else [])
    filters+=rgba8_to_rgba16('tagged' if rgb_tagged else '0:v','integer',has_alpha=has_alpha)
    def run(graph,label,fmt):
        return subprocess.run([ffmpeg_executable(),'-v','error','-filter_complex_threads','1','-f','rawvideo',
            '-pixel_format','rgba' if has_alpha else 'rgb24','-video_size','256x2','-i','pipe:0','-filter_complex',';'.join(graph),
            '-map','['+label+']','-frames:v','1','-pix_fmt',fmt,'-f','rawvideo','pipe:1'],
            input=raw,capture_output=True,check=True).stdout
    actual=struct.unpack('<2048H',run(filters,'integer','gbrap16le'))
    expected=[(pixel[c] if has_alpha or c!=3 else 255)*257 for c in (1,2,0,3) for pixel in pixels]
    assert actual==tuple(expected)
    floats=struct.unpack('<2048f',run(filters+rgba16_to_float('integer','floating'),'floating','gbrapf32le'))
    expected_float=[struct.unpack('<f',struct.pack('<f',v/65535))[0] for v in expected]
    # zimg's reciprocal conversion can differ from scalar division by one ULP.
    bits=lambda v:struct.unpack('<I',struct.pack('<f',v))[0]
    assert all(abs(bits(a)-bits(b))<=1 for a,b in zip(floats,expected_float))
    assert max(floats)==1 and min(floats)==0


@pytest.mark.parametrize('size',[(640,360),(34,18)])
def test_drop_alpha_preserves_each_rgb_code_at_every_pixel(size):
    # Distinct, spatially varying planes include endpoints and non-opaque
    # alpha, so swapping planes, rescaling codes or losing an edge is visible.
    width,height=size;count=width*height
    planes=[struct.pack('<'+'H'*count,*((i*step+offset)%65536 for i in range(count)))
            for step,offset in [(257,0),(521,65535),(1031,7),(13,128)]]
    result=subprocess.run([ffmpeg_executable(),'-v','error','-filter_complex_threads','1',
        '-f','rawvideo','-pixel_format','gbrap16le','-video_size',f'{width}x{height}','-i','pipe:0',
        '-filter_complex',';'.join(rgb16_without_alpha('0:v','rgb')),'-map','[rgb]',
        '-frames:v','1','-pix_fmt','gbrp16le','-f','rawvideo','pipe:1'],
        input=b''.join(planes),capture_output=True,check=True)
    assert result.stdout==b''.join(planes[:3])
