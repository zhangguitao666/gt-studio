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

REFERENCE=json.loads((Path(__file__).parent/'fixtures/audio-gain.json').read_text())


def create_source(path,name):
    amp=REFERENCE['sources'][name]
    samples=[round(amp*math.sin(2*math.pi*440*i/48000)) if name=='sine' else amp for i in range(96000)]
    with wave.open(str(path),'wb') as w:
        w.setparams((1,2,48000,len(samples),'NONE','not compressed'))
        w.writeframes(struct.pack('<'+'h'*len(samples),*samples))


@pytest.mark.parametrize('case',REFERENCE['cases'],ids=[c['name'] for c in REFERENCE['cases']])
def test_native_audio_gain_pcm24_full_stream(tmp_path,case):
    e=Engine(tmp_path/'project');e.dispatch('create_project',{'width':16,'height':16,'fps':24,'sample_rate':48000})
    media={}
    for name in {i['source'] for i in case['items']}:
        source=tmp_path/(name+'.wav');create_source(source,name)
        media[name]=e.dispatch('import_media',{'path':str(source)})
    tracks=[t for t in e._timeline()['tracks'] if t['kind']=='audio']
    while len(tracks)<max(i['track'] for i in case['items']):tracks.append(e.dispatch('add_track',{'kind':'audio'}))
    for item in case['items']:
        clip=e.dispatch('append_clip',{'media_id':media[item['source']]['id'],'track_id':tracks[item['track']-1]['id'],'in_frame':0,'out_frame':48,'start_frame':item['start']})
        e.dispatch('set_clip_properties',{'clip_id':clip['id'],'properties':{'volume':10**(item['gain']/20)}})
    output=tmp_path/'gain.mov';e.dispatch('render',{'output':str(output)})
    own=subprocess.check_output([ffmpeg_executable(),'-v','error','-i',str(output),'-vn','-c:a','pcm_s32le','-f','s32le','-'])
    native=zlib.decompress(base64.b64decode(case['native_pcm_s32le_zlib']))
    assert len(native)==case['native_pcm_s32le_bytes'] and hashlib.sha256(native).hexdigest()==case['native_pcm_s32le_sha256']
    if own!=native:
        a=array.array('i');a.frombytes(native);b=array.array('i');b.frombytes(own)
        changed=[(i,x,y) for i,(x,y) in enumerate(zip(a,b)) if x!=y]
        pytest.fail(json.dumps({'case':case['name'],'native_samples':len(a),'own_samples':len(b),'changed_scalars':len(changed),'first':changed[:8],'max_delta':max((abs(x-y) for _,x,y in changed),default=0),'own_sha256':hashlib.sha256(own).hexdigest()}))
