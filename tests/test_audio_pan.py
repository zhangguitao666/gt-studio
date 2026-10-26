"""Complete native PCM streams constrain the independent pan renderer."""
import array
import base64
import copy
import json
from pathlib import Path
import struct
import subprocess
import wave
import zlib

import pytest
from frameforge.audio_pan import f32, gain_prefix, targets
from frameforge.engine import Engine, ffmpeg_executable

REFERENCE = json.loads((Path(__file__).parents[1]/'research/audio-pan-fixtures.json').read_text())


def native(case):
    return zlib.decompress(base64.b64decode(case['pcm_s32le_zlib']))


def compare(case, actual):
    expected = native(case)
    if actual!=expected:
        a,b = array.array('i'),array.array('i')
        a.frombytes(expected);b.frombytes(actual)
        changed = [(i,x,y) for i,(x,y) in enumerate(zip(a,b)) if x!=y]
        pytest.fail(json.dumps({'case': case['name'], 'bits': case['bits'],
            'expected_bytes': len(expected), 'actual_bytes': len(actual),
            'changed_scalars': len(changed), 'first': changed[:6],
            'max_delta': max((abs(x-y) for _,x,y in changed), default=0)}))


@pytest.mark.parametrize('case',[c for c in REFERENCE['cases'] if c['bits']==24],ids=lambda c:c['name'])
def test_native_pan_pcm24_full_stream(tmp_path,case):
    source = tmp_path/'source.wav'
    values = REFERENCE['sources'][case['source']]
    with wave.open(str(source),'wb') as w:
        w.setparams((len(values),2,48000,96000,'NONE','not compressed'))
        w.writeframes(struct.pack('<'+'h'*len(values),*values)*96000)
    e=Engine(tmp_path/'project');e.dispatch('create_project',{'width':16,'height':16})
    media=e.dispatch('import_media',{'path':str(source)})
    track=next(t for t in e._timeline()['tracks'] if t['kind']=='audio')
    clip=e.dispatch('append_clip',{'media_id':media['id'],'track_id':track['id'],'out_frame':48})
    e.dispatch('set_clip_properties',{'clip_id':clip['id'],'properties':{'pan':case['pan']}})
    project=tmp_path/'pan.json';e.dispatch('save_project',{'path':str(project)})
    e.dispatch('open_project',{'path':str(project)})
    output=tmp_path/'pan.mov';e.dispatch('render',{'output':str(output)})
    compare(case,subprocess.check_output([ffmpeg_executable(),'-v','error','-i',str(output),
        '-vn','-c:a','pcm_s32le','-f','s32le','-']))


@pytest.mark.parametrize('case',[c for c in REFERENCE['cases'] if c['bits']==32],ids=lambda c:c['name'])
def test_native_pan_float_kernel_full_pcm32(tmp_path,case):
    # The renderer exports PCM24 MOV; PCM32 references separately constrain
    # kernel arithmetic before final export quantization.
    curves=[gain_prefix(t,96000) for t in targets(case['pan'])]
    output=bytearray()
    for n in range(96000):
        edge=f32(min(1,n/72,(96000-n)/72))
        for curve in curves:
            gain=curve[min(n,len(curve)-1)]
            value=f32(f32(.125*gain)*edge)
            output.extend(struct.pack('<i',round(value*2147483648)))
    compare(case,bytes(output))


def test_pan_validation():
    for value in [-101,101,True,float('nan')]:
        with pytest.raises(ValueError):Engine._validate_properties({'pan':value})
    for value in [-100,0,100]:Engine._validate_properties({'pan':value})


def test_pan_envelope_rejects_uncalibrated_rate(tmp_path):
    from frameforge.audio_pan import write_envelope
    with pytest.raises(ValueError,match='48000'):
        write_envelope(tmp_path/'unsupported.wav',100,96000,44100)
    assert not (tmp_path/'unsupported.wav').exists()


def test_pan_legacy_default_undo_and_atomic_validation(tmp_path):
    source=tmp_path/'source.wav'
    with wave.open(str(source),'wb') as w:
        w.setparams((1,2,48000,96000,'NONE','not compressed'));w.writeframes(b'\0\x10'*96000)
    e=Engine(tmp_path/'project');e.dispatch('create_project',{})
    media=e.dispatch('import_media',{'path':str(source)})
    track=next(t for t in e._timeline()['tracks'] if t['kind']=='audio')
    clip=e.dispatch('append_clip',{'media_id':media['id'],'track_id':track['id'],'out_frame':48})
    project=tmp_path/'legacy.json';e.dispatch('save_project',{'path':str(project)})
    legacy=json.loads(project.read_text())
    next(t for t in legacy['timelines'][0]['tracks'] if t['kind']=='audio')['clips'][0]['properties'].pop('pan')
    project.write_text(json.dumps(legacy));original=project.read_bytes()
    e.dispatch('open_project',{'path':str(project)})
    assert e._clip(clip['id'])[0]['properties']['pan']==0
    assert project.read_bytes()==original
    e.dispatch('set_clip_properties',{'clip_id':clip['id'],'properties':{'pan':100}})
    e.dispatch('undo',{});assert e._clip(clip['id'])[0]['properties']['pan']==0
    e.dispatch('redo',{});assert e._clip(clip['id'])[0]['properties']['pan']==100
    before=copy.deepcopy(e.project)
    with pytest.raises(ValueError):
        e.dispatch('set_clip_properties',{'clip_id':clip['id'],'properties':{'volume':2,'pan':101}})
    assert e.project==before


def test_multiple_pan_inputs_keep_media_input_indices(tmp_path):
    e=Engine(tmp_path/'project');e.dispatch('create_project',{'width':16,'height':16})
    tracks=[next(t for t in e._timeline()['tracks'] if t['kind']=='audio'),e.dispatch('add_track',{'kind':'audio'})]
    for i,values in enumerate([(4096,),(4096,8192)]):
        source=tmp_path/f'source{i}.wav'
        with wave.open(str(source),'wb') as w:
            w.setparams((len(values),2,48000,96000,'NONE','not compressed'))
            w.writeframes(struct.pack('<'+'h'*len(values),*values)*96000)
        media=e.dispatch('import_media',{'path':str(source)})
        clip=e.dispatch('append_clip',{'media_id':media['id'],'track_id':tracks[i]['id'],'out_frame':48})
        e.dispatch('set_clip_properties',{'clip_id':clip['id'],'properties':{'pan':100 if i==0 else -100}})
    output=tmp_path/'mix.mov';e.dispatch('render',{'output':str(output)})
    raw=subprocess.check_output([ffmpeg_executable(),'-v','error','-i',str(output),'-vn','-c:a','pcm_s32le','-f','s32le','-'])
    assert len(raw)==96000*2*4
    left,right=targets(100)
    expected=[round(f32(f32(.125*left)+f32(.125*right))*8388608)*256,
              round(f32(f32(.125*right)+f32(.25*left))*8388608)*256]
    assert list(struct.unpack_from('<ii',raw,5000*8))==expected
