"""Sine/stereo native streams distinguish anti-click versus pan order."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import wave
import zlib

import pytest

from frameforge.engine import Engine, ffmpeg_executable
from test_audio_pan import compare


REFERENCE = json.loads((Path(__file__).parent/'fixtures/audio-pan-waveforms.json').read_text())


@pytest.mark.parametrize('case', REFERENCE['cases'], ids=lambda c: c['name'])
def test_native_pan_waveform_pcm24_full_stream(tmp_path, case):
    assert case['native_status']['JobStatus'] == 'Complete'
    specification = REFERENCE['sources'][case['source']]
    raw = zlib.decompress(base64.b64decode(specification['pcm_s16le_zlib']))
    assert hashlib.sha256(raw).hexdigest() == specification['pcm_s16le_sha256']
    assert len(raw) == specification['frames']*specification['channels']*2
    source = tmp_path/'waveform.wav'
    with wave.open(str(source), 'wb') as wav:
        wav.setparams((specification['channels'], 2, specification['sample_rate'],
                       specification['frames'], 'NONE', 'not compressed'))
        wav.writeframes(raw)
    e = Engine(tmp_path/'project')
    e.dispatch('create_project', {'width': 16, 'height': 16})
    media = e.dispatch('import_media', {'path': str(source)})
    track = next(t for t in e._timeline()['tracks'] if t['kind']=='audio')
    clip = e.dispatch('append_clip', {'media_id': media['id'], 'track_id': track['id'], 'out_frame': 48})
    e.dispatch('set_clip_properties', {'clip_id': clip['id'], 'properties': {'pan': case['pan']}})
    project = tmp_path/'saved.json'
    e.dispatch('save_project', {'path': str(project)})
    e.dispatch('open_project', {'path': str(project)})
    output = tmp_path/'actual.mov'
    e.dispatch('render', {'output': str(output)})
    expected = zlib.decompress(base64.b64decode(case['pcm_s32le_zlib']))
    assert hashlib.sha256(expected).hexdigest() == case['pcm_s32le_sha256']
    compare(case, subprocess.check_output([ffmpeg_executable(), '-v', 'error', '-i', str(output),
            '-vn', '-c:a', 'pcm_s32le', '-f', 's32le', '-']))
