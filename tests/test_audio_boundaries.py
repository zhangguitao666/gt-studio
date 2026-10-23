"""Full-stream native PCM fixtures from controlled, owned source signals."""
import array
import base64
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import wave
import zlib

import pytest
from frameforge.engine import Engine,ffmpeg_executable

REFERENCE=json.loads((Path(__file__).parent/'fixtures/audio-boundaries.json').read_text())


def create_source(path,name):
    samples=[4096 if name=='dc' else -4096 if name=='negative' else round(4096*math.sin(2*math.pi*440*i/48000)) for i in range(96000)]
    with wave.open(str(path),'wb') as w:
        w.setparams((1,2,48000,len(samples),'NONE','not compressed'))
        w.writeframes(struct.pack('<'+'h'*len(samples),*samples))


@pytest.mark.parametrize('case',REFERENCE['cases'],ids=[c['name'] for c in REFERENCE['cases']])
def test_native_audio_boundary_pcm24_full_stream(tmp_path,case):
    source=tmp_path/(case['source']+'.wav');create_source(source,case['source'])
    e=Engine(tmp_path/'project');e.dispatch('create_project',{'width':16,'height':16,'fps':24,'sample_rate':48000})
    media=e.dispatch('import_media',{'path':str(source)})
    tracks=[t for t in e._timeline()['tracks'] if t['kind']=='audio']
    while len(tracks)<max(i['track'] for i in case['items']):tracks.append(e.dispatch('add_track',{'kind':'audio'}))
    for item in case['items']:
        e.dispatch('append_clip',{'media_id':media['id'],'track_id':tracks[item['track']-1]['id'],'in_frame':item['source_start'],'out_frame':item['source_end'],'start_frame':item['start']})
    output=tmp_path/'boundary.mov';e.dispatch('render',{'output':str(output)})
    own=subprocess.check_output([ffmpeg_executable(),'-v','error','-i',str(output),'-vn','-c:a','pcm_s32le','-f','s32le','-'])
    native=zlib.decompress(base64.b64decode(case['native_pcm_s32le_zlib']))
    assert len(native)==case['native_pcm_s32le_bytes'] and hashlib.sha256(native).hexdigest()==case['native_pcm_s32le_sha256']
    if own!=native:
        a=array.array('i');a.frombytes(native);b=array.array('i');b.frombytes(own)
        changed=[(i,x,y) for i,(x,y) in enumerate(zip(a,b)) if x!=y]
        pytest.fail(json.dumps({'case':case['name'],'native_samples':len(a),'own_samples':len(b),'changed_scalars':len(changed),'first':changed[:8],'max_delta':max((abs(x-y) for _,x,y in changed),default=0),'own_sha256':hashlib.sha256(own).hexdigest()}))


def assert_native_edges_pcm16(reference,actual,*,head=False,tail=False,channels=2,body_tolerance=0):
    """Retained payload stays exact; new edges follow measured native DC gains.

    The boundary allows one PCM16 unit because its input reference has already
    been quantized once; the full PCM24 fixture comparisons above stay exact.
    """
    original=array.array('h');original.frombytes(reference)
    rendered=array.array('h');rendered.frombytes(actual)
    assert len(original)==len(rendered)
    dc=next(c for c in REFERENCE['cases'] if c['name']=='dc_contiguous')
    measured=array.array('i');measured.frombytes(zlib.decompress(base64.b64decode(dc['native_pcm_s32le_zlib'])))
    expected=array.array('h',original);frames=len(expected)//channels
    touched=set()
    for begin,offset in ((head,0),(tail,frames-72)):
        if not begin:continue
        capture_offset=0 if offset==0 and head else len(measured)//2-72
        for i in range(72):
            gain=measured[(capture_offset+i)*2]/(4096*65536)
            for channel in range(channels):
                at=(offset+i)*channels+channel;touched.add(at)
                expected[at]=round(original[at]*gain)
    unchanged=[i for i in range(len(original)) if i not in touched]
    assert max((abs(original[i]-rendered[i]) for i in unchanged),default=0)<=body_tolerance
    assert max((abs(expected[i]-rendered[i]) for i in touched),default=0)<=1
    return expected
