"""Project-frame clocks preserve numbered media through processed graph paths."""
import subprocess
import pytest

from frameforge.engine import Engine, ffmpeg_executable
from test_fusion import add, connect, pixels, pixel


@pytest.mark.parametrize('rate', [24, {'num':30000,'den':1001}])
@pytest.mark.parametrize('speed', [100,200,-100])
def test_processed_graph_preserves_every_numbered_source_frame_after_gap(tmp_path, rate, speed):
    rate_text = str(rate) if isinstance(rate,int) else f'{rate["num"]}/{rate["den"]}'
    source = tmp_path/'numbered.mkv'
    subprocess.run([ffmpeg_executable(),'-v','error','-y','-f','lavfi','-i',
                    f'nullsrc=s=32x32:r={rate_text}:d=1,format=gbrp,geq=r=N*8:g=N*8:b=N*8',
                    '-c:v','ffv1',str(source)],check=True)
    e=Engine(tmp_path/'project');e.dispatch('create_project',{'width':32,'height':32,'fps':rate})
    media=e.dispatch('import_media',{'path':str(source)})
    clip=e.dispatch('append_clip',{'media_id':media['id'],'out_frame':24,'start_frame':5})['id']
    if speed!=100:e.dispatch('set_clip_speed',{'clip_id':clip,'percentage':speed,'ripple':True})
    transform=add(e,clip,'Transform');connect(e,clip,transform,'Input','MediaIn1');connect(e,clip,'MediaOut1','Input',transform)
    output=tmp_path/'clock.mov';e.dispatch('render',{'output':str(output)})
    raw=pixels(output);length=12 if speed==200 else 24
    assert len(raw)==(5+length)*32*32*3
    for frame in range(5):assert max(pixel(raw,16,16,frame))<=3
    for local in range(length):
        source_frame=23-local if speed<0 else local*(2 if speed==200 else 1)
        assert pixel(raw,16,16,local+5)==pytest.approx((source_frame*8,)*3,abs=3), f'frame={local}, source={source_frame}'
