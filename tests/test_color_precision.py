"""Decoded precision invariants, independent of internal filter spelling."""
import struct
import subprocess
import pytest
from frameforge.engine import Engine,ffmpeg_executable
from test_transitions import colored_sources,center_pixels


@pytest.mark.parametrize('base',[64,384,768])
def test_prores_retains_dense_ten_bit_luma_steps(tmp_path,base):
    source=tmp_path/'gradient10.mkv'
    subprocess.run([ffmpeg_executable(),'-v','error','-y','-f','lavfi','-i',f'nullsrc=s=128x32:r=24:d=0.25,format=yuv444p10le,geq=lum={base}+X:cb=512:cr=512','-c:v','ffv1','-level','3','-pix_fmt','yuv444p10le',str(source)],check=True)
    e=Engine(tmp_path);e.dispatch('create_project',{'width':128,'height':32})
    media=e.dispatch('import_media',{'path':str(source)});e.dispatch('append_clip',{'media_id':media['id']})
    output=tmp_path/'gradient.mov';e.dispatch('render',{'output':str(output)})
    raw=subprocess.run([ffmpeg_executable(),'-v','error','-i',str(output),'-frames:v','1','-pix_fmt','yuv422p10le','-f','rawvideo','-'],capture_output=True,check=True).stdout
    row=struct.unpack('<128H',raw[16*128*2:17*128*2])
    assert len(set(row))>=120
    assert max(abs(value-(base+x)) for x,value in enumerate(row))<=1


@pytest.mark.parametrize('opacity',[.25,.75])
def test_high_precision_dissolve_retains_transparent_canvas(tmp_path,colored_sources,opacity):
    e=Engine(tmp_path);e.dispatch('create_project',{'width':160,'height':90})
    red,blue,lime=[e.dispatch('import_media',{'path':str(p)}) for p in colored_sources[:3]]
    e.dispatch('append_clip',{'media_id':lime['id'],'out_frame':72})
    e.dispatch('append_clip',{'media_id':lime['id'],'out_frame':24})
    track=e.dispatch('add_track',{'kind':'video'})
    left=e.dispatch('append_clip',{'media_id':red['id'],'track_id':track['id'],'in_frame':12,'out_frame':60})
    right=e.dispatch('append_clip',{'media_id':blue['id'],'track_id':track['id'],'in_frame':12,'out_frame':60})
    for clip in (left,right):e.dispatch('set_clip_properties',{'clip_id':clip['id'],'opacity':opacity})
    e.dispatch('add_transition',{'clip_id':left['id']})
    output=tmp_path/'alpha.mov';e.dispatch('render',{'output':str(output)})
    pixels=center_pixels(output)
    for frame,(r,g,b) in enumerate(pixels[42:54]):
        weight=(frame+.5)/12
        assert g==pytest.approx(253*(1-opacity),abs=6)
        assert r==pytest.approx(253*opacity*(1-weight),abs=6)
        assert b==pytest.approx(253*opacity*weight,abs=6)
