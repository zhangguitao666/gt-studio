"""Editing transactions, persistence, and actual encoded frame/audio behavior."""
from pathlib import Path
import subprocess
import pytest
from frameforge.engine import Engine, ffmpeg_executable


@pytest.fixture
def media(tmp_path):
    try:
        ffmpeg = ffmpeg_executable()
    except ValueError:
        pytest.skip('FFmpeg unavailable')
    sources = []
    for color, freq in [('red', 440), ('blue', 880)]:
        path = tmp_path / (color + '.mp4')
        proc = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', f'color=c={color}:s=160x90:r=24:d=1', '-f', 'lavfi', '-i', f'sine=frequency={freq}:sample_rate=48000:duration=1', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)], capture_output=True)
        assert proc.returncode == 0, proc.stderr.decode()
        sources.append(path)
    return sources


def setup_project(tmp_path, media):
    e = Engine(tmp_path)
    e.dispatch('create_project', {'name': 'Test', 'width': 160, 'height': 90})
    m = e.dispatch('import_media', {'path': str(media[0])})
    c = e.dispatch('append_clip', {'media_id': m['id']})
    return e, m, c


def test_edit_transactions_and_persistence(tmp_path, media):
    e, m, clip = setup_project(tmp_path, media)
    split = e.dispatch('split_clip', {'clip_id': clip['id'], 'frame': 12})
    assert split['first']['out_frame'] == split['second']['in_frame'] == 12
    assert split['second']['start_frame'] == 12
    state = e.get_state()
    with pytest.raises(ValueError, match='overlap'):
        e.dispatch('move_clip', {'clip_id': split['second']['id'], 'start_frame': 5})
    assert e.get_state() == state
    e.dispatch('delete_clip', {'clip_id': split['second']['id']})
    e.dispatch('undo')
    assert e.get_state() == state
    e.dispatch('redo')
    assert len(e._timeline()['tracks'][0]['clips']) == 1
    e.dispatch('add_marker', {'frame': 6, 'name': 'Cut'})
    target = e.dispatch('save_project')['path']
    reopened = Engine(tmp_path)
    reopened.dispatch('open_project', {'path': target})
    assert reopened.get_state() == e.get_state()
    with pytest.raises(ValueError):
        e.dispatch('append_clip', {'media_id': m['id'], 'out_frame': 10000, 'start_frame': 100})
    with pytest.raises(ValueError):
        e.dispatch('set_clip_properties', {'clip_id': clip['id'], 'properties': {'gamma': float('nan')}})


def pixel(path, time):
    p = subprocess.run([ffmpeg_executable(), '-hide_banner', '-loglevel', 'error', '-ss', str(time), '-i', str(path), '-frames:v', '1', '-vf', 'scale=1:1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], capture_output=True)
    assert p.returncode == 0, p.stderr.decode()
    assert len(p.stdout) == 3
    return tuple(p.stdout)


def test_render_composites_tracks_and_retains_underlying_video(tmp_path, media):
    e, _, red = setup_project(tmp_path, media)
    blue = e.dispatch('import_media', {'path': str(media[1])})
    upper = e.dispatch('add_track', {'kind': 'video'})
    e.dispatch('append_clip', {'media_id': blue['id'], 'track_id': upper['id'], 'start_frame': 6, 'out_frame': 12})
    output = tmp_path / 'final.mp4'
    result = e.dispatch('render', {'output': str(output)})
    assert result['duration_frames'] == 24
    probe = e.dispatch('probe_media', {'path': str(output)})
    assert probe['video'] and probe['audio']
    assert probe['duration_seconds'] == pytest.approx(1, abs=.05)
    before, during, after = (pixel(output, t) for t in (.1, .4, .9))
    assert before[0] > 200 and before[2] < 50
    assert during[2] > 200 and during[0] < 50
    assert after[0] > 200 and after[2] < 50
    # Actual PCM energy proves a source audio signal survives mixing/encoding.
    audio = subprocess.run([ffmpeg_executable(), '-v', 'error', '-i', str(output), '-vn', '-f', 's16le', '-ac', '1', '-'], capture_output=True)
    import array
    samples = array.array('h', audio.stdout)
    assert len(samples) >= 47000
    assert max(abs(s) for s in samples) > 1000
    with pytest.raises(ValueError, match='overwrite'):
        e.dispatch('render', {'output': str(media[0])})


def test_audio_only_timeline_with_gap(tmp_path, media):
    e = Engine(tmp_path)
    e.dispatch('create_project', {'width': 160, 'height': 90})
    m = e.dispatch('import_media', {'path': str(media[0])})
    audio_track = e._timeline()['tracks'][1]
    e.dispatch('append_clip', {'media_id': m['id'], 'track_id': audio_track['id'], 'start_frame': 12, 'out_frame': 12})
    output = tmp_path / 'audio-only.mp4'
    e.dispatch('render', {'output': str(output)})
    assert max(pixel(output, .1)) < 10
    assert e.probe_media(output)['audio']


def test_render_applies_color_gain_and_muting(tmp_path, media):
    e, _, clip = setup_project(tmp_path, media)
    e.dispatch('set_clip_properties', {'clip_id': clip['id'], 'properties': {'exposure': -2, 'volume': 0}})
    output = tmp_path / 'graded-muted.mp4'
    e.dispatch('render', {'output': str(output)})
    r, g, b = pixel(output, .5)
    assert 45 < r < 90 and g < 20 and b < 20
    audio = subprocess.run([ffmpeg_executable(), '-v', 'error', '-i', str(output), '-vn', '-f', 's16le', '-ac', '1', '-'], capture_output=True)
    import array
    assert audio.returncode == 0
    samples = array.array('h', audio.stdout)
    assert max(abs(s) for s in samples) < 5
    # The full permitted exposure range must encode, including gains above 2.
    e.dispatch('set_clip_properties', {'clip_id': clip['id'], 'properties': {'exposure': 3}})
    e.dispatch('render', {'output': str(tmp_path / 'bright.mp4')})


def test_trim_reads_source_frames_and_rational_rate(tmp_path):
    source = tmp_path / 'two-colors.mp4'
    ffmpeg = ffmpeg_executable()
    result = subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=red:s=160x90:r=30000/1001:d=1.001', '-f', 'lavfi', '-i', 'color=blue:s=160x90:r=30000/1001:d=1.001', '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v]', '-map', '[v]', '-c:v', 'libx264', str(source)], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    e = Engine(tmp_path)
    e.dispatch('create_project', {'width': 160, 'height': 90, 'fps': {'num': 30000, 'den': 1001}})
    media = e.dispatch('import_media', {'path': str(source)})
    clip = e.dispatch('append_clip', {'media_id': media['id'], 'out_frame': 60})
    e.dispatch('trim_clip', {'clip_id': clip['id'], 'in_frame': 30, 'out_frame': 60})
    output = tmp_path / 'trimmed.mp4'
    rendered = e.dispatch('render', {'output': str(output)})
    assert rendered['duration_frames'] == 30
    assert rendered['duration_seconds'] == pytest.approx(1.001, abs=1e-10)
    for time in (.05, .5, .95):
        r, _, b = pixel(output, time)
        assert b > 220 and r < 20
    raw = subprocess.run([ffmpeg, '-v', 'error', '-i', str(output), '-an', '-vf', 'scale=1:1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], capture_output=True)
    assert raw.returncode == 0
    assert len(raw.stdout) // 3 == 30
    e.dispatch('set_clip_properties', {'clip_id': clip['id'], 'saturation': 0})
    gray = tmp_path / 'gray.mp4'
    e.dispatch('render', {'output': str(gray)})
    values = pixel(gray, .5)
    assert max(values) - min(values) < 5


def test_rejects_malformed_projects_without_losing_current_state(tmp_path, media):
    import copy
    import json
    e, _, clip = setup_project(tmp_path, media)
    valid = e.get_state()
    malformed = []
    duplicate = copy.deepcopy(valid)
    duplicate['timelines'][0]['tracks'][1]['id'] = duplicate['timelines'][0]['tracks'][0]['id']
    malformed.append(duplicate)
    properties = copy.deepcopy(valid)
    properties['timelines'][0]['tracks'][0]['clips'][0]['properties']['gamma'] = -1
    malformed.append(properties)
    missing = copy.deepcopy(valid)
    del missing['timelines'][0]['tracks'][0]['clips'][0]['properties']['volume']
    malformed.append(missing)
    for index, bad in enumerate(malformed):
        path = tmp_path / f'bad-{index}.json'
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            e.dispatch('open_project', {'path': str(path)})
        assert e.get_state() == valid
    marker = e.dispatch('add_marker', {'frame': 0, 'label': 'Start'})
    assert marker['name'] == marker['label'] == 'Start'
    with pytest.raises(ValueError):
        e.dispatch('create_timeline', {'namme': 'typo'})


def pixel_at(path, time, x, y, width=160, height=90):
    p = subprocess.run([ffmpeg_executable(), '-v', 'error', '-ss', str(time), '-i', str(path), '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], capture_output=True)
    assert p.returncode == 0, p.stderr.decode()
    offset = (y * width + x) * 3
    assert len(p.stdout) == width * height * 3
    return tuple(p.stdout[offset:offset + 3])


def test_transform_opacity_rotation_and_fades(tmp_path, media):
    e, _, lower = setup_project(tmp_path, media)
    blue = e.dispatch('import_media', {'path': str(media[1])})
    upper = e.dispatch('add_track', {'kind': 'video'})
    clip = e.dispatch('append_clip', {'media_id': blue['id'], 'track_id': upper['id']})
    e.dispatch('set_clip_properties', {'clip_id': lower['id'], 'volume': 0})
    e.dispatch('set_clip_properties', {'clip_id': clip['id'], 'properties': {'scale': .5, 'x': 40, 'opacity': .5}})
    output = tmp_path / 'transform.mp4'
    e.dispatch('render', {'output': str(output)})
    assert pixel_at(output, .5, 20, 45)[0] > 220
    blend = pixel_at(output, .5, 120, 45)
    assert 90 < blend[0] < 160 and 90 < blend[2] < 160
    assert pixel_at(output, .5, 120, 10)[0] > 220
    e.dispatch('set_clip_properties', {'clip_id': clip['id'], 'rotation': 90})
    rotated = tmp_path / 'rotated.mp4'
    e.dispatch('render', {'output': str(rotated)})
    assert pixel_at(rotated, .5, 85, 45)[0] > 220
    blend_rotated = pixel_at(rotated, .5, 120, 10)
    assert 90 < blend_rotated[0] < 160 and 90 < blend_rotated[2] < 160
    e.dispatch('set_clip_properties', {'clip_id': clip['id'], 'properties': {'scale': 1, 'x': 0, 'rotation': 0, 'opacity': 1, 'fade_in_frames': 12, 'fade_out_frames': 12}})
    faded = tmp_path / 'faded.mp4'
    e.dispatch('render', {'output': str(faded)})
    start, middle, end = (pixel_at(faded, t, 80, 45) for t in (0, .5, .95))
    assert start[0] > 220 and start[2] < 20
    assert middle[2] > 220 and middle[0] < 20
    assert end[0] > 180 and end[2] < 70
    audio = subprocess.run([ffmpeg_executable(), '-v', 'error', '-i', str(faded), '-vn', '-f', 's16le', '-ac', '1', '-'], capture_output=True)
    import array
    samples = array.array('h', audio.stdout)
    def rms(begin, end):
        window = samples[int(begin * 48000):int(end * 48000)]
        return (sum(x*x for x in window) / len(window)) ** .5
    assert rms(.02, .06) < rms(.45, .5) * .25
    assert rms(.94, .98) < rms(.45, .5) * .25


def test_ripple_delete_only_changes_target_track_and_undo(tmp_path, media):
    e, m, first = setup_project(tmp_path, media)
    second = e.dispatch('append_clip', {'media_id': m['id']})
    third = e.dispatch('append_clip', {'media_id': m['id'], 'start_frame': 60})
    other = e.dispatch('add_track', {'kind': 'video'})
    parallel = e.dispatch('append_clip', {'media_id': m['id'], 'track_id': other['id'], 'start_frame': 60})
    before = e.get_state()
    with pytest.raises(ValueError):
        e.dispatch('ripple_delete', {'clip_id': 'missing'})
    assert e.get_state() == before
    result = e.dispatch('ripple_delete', {'clip_id': second['id']})
    assert result['shift_frames'] == 24
    assert result['shifted_clip_ids'] == [third['id']]
    assert e._clip(third['id'])[0]['start_frame'] == 36
    assert e._clip(first['id'])[0]['start_frame'] == 0
    assert e._clip(parallel['id'])[0]['start_frame'] == 60
    e.dispatch('undo')
    assert e.get_state() == before
    for properties in ({'opacity': 2}, {'scale': 0}, {'fade_in_frames': .5}, {'rotation': float('nan')}):
        with pytest.raises(ValueError):
            e.dispatch('set_clip_properties', {'clip_id': first['id'], 'properties': properties})
        assert e.get_state() == before


def test_old_clip_properties_migrate_transform_defaults(tmp_path, media):
    import json
    e, _, clip = setup_project(tmp_path, media)
    state = e.get_state()
    props = state['timelines'][0]['tracks'][0]['clips'][0]['properties']
    state['timelines'][0]['tracks'][0]['clips'][0]['properties'] = {k: props[k] for k in ('exposure', 'contrast', 'saturation', 'gamma', 'volume')}
    old = tmp_path / 'old.json'
    old.write_text(json.dumps(state))
    e.dispatch('open_project', {'path': str(old)})
    migrated = e._clip(clip['id'])[0]['properties']
    assert migrated['opacity'] == migrated['scale'] == 1
    assert migrated['fade_in_frames'] == migrated['fade_out_frames'] == 0


def test_transformed_letterbox_padding_is_transparent(tmp_path, media):
    e, _, _ = setup_project(tmp_path, media)
    portrait = tmp_path / 'portrait.mp4'
    result = subprocess.run([ffmpeg_executable(), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=blue:s=40x90:r=24:d=1', '-c:v', 'libx264', str(portrait)], capture_output=True)
    assert result.returncode == 0
    m = e.dispatch('import_media', {'path': str(portrait)})
    track = e.dispatch('add_track', {'kind': 'video'})
    clip = e.dispatch('append_clip', {'media_id': m['id'], 'track_id': track['id']})
    default = tmp_path / 'letterbox.mp4'
    e.dispatch('render', {'output': str(default)})
    assert max(pixel_at(default, .5, 10, 45)) < 15
    e.dispatch('set_clip_properties', {'clip_id': clip['id'], 'scale': .5})
    transformed = tmp_path / 'transparent-padding.mp4'
    e.dispatch('render', {'output': str(transformed)})
    assert pixel_at(transformed, .5, 50, 45)[0] > 220
    assert pixel_at(transformed, .5, 80, 45)[2] > 220
    assert pixel_at(transformed, .5, 80, 10)[0] > 220


def test_still_image_import_defaults_and_looped_render(tmp_path):
    ffmpeg = ffmpeg_executable()
    image = tmp_path / 'still.png'
    created = subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=green:s=160x90', '-frames:v', '1', str(image)], capture_output=True)
    assert created.returncode == 0, created.stderr.decode()
    e = Engine(tmp_path)
    e.dispatch('create_project', {'width': 160, 'height': 90})
    imported = e.dispatch('import_media', {'path': str(image)})
    assert imported['still'] is True
    assert imported['duration_seconds'] == 5
    clip = e.dispatch('append_clip', {'media_id': imported['id']})
    assert clip['out_frame'] == 120
    output = tmp_path / 'still-video.mp4'
    result = e.dispatch('render', {'output': str(output)})
    assert result['duration_frames'] == 120
    for time in (0, 2.5, 4.9):
        r, g, b = pixel(output, time)
        assert g > 90 and r < 20 and b < 20
    raw = subprocess.run([ffmpeg, '-v', 'error', '-i', str(output), '-an', '-vf', 'scale=1:1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], capture_output=True)
    assert len(raw.stdout) == 120 * 3


def test_render_actual_prores_mov_and_pcm_wave(tmp_path, media):
    import wave
    import array
    e, _, _ = setup_project(tmp_path, media)
    mov = tmp_path / 'master.mov'
    result = e.dispatch('render', {'output': str(mov)})
    assert result['format'] == 'mov'
    info = subprocess.run([ffmpeg_executable(), '-hide_banner', '-i', str(mov)], capture_output=True, text=True)
    assert 'Video: prores' in info.stderr
    assert 'Audio: pcm_s16le' in info.stderr
    assert pixel(mov, .5)[0] > 220
    wav = tmp_path / 'sound.wav'
    e.dispatch('render', {'output': str(wav), 'format': 'wav'})
    with wave.open(str(wav), 'rb') as reader:
        assert reader.getnchannels() == 2
        assert reader.getsampwidth() == 2
        assert reader.getframerate() == 48000
        assert reader.getnframes() == 48000
        samples = array.array('h', reader.readframes(reader.getnframes()))
        assert max(abs(x) for x in samples) > 1000
    before = mov.read_bytes()
    with pytest.raises(ValueError, match='format'):
        e.dispatch('render', {'output': str(mov), 'format': 'fake'})
    assert mov.read_bytes() == before


def numbered_source(tmp_path, fps='24', count=8):
    # Lossless source frames carry distinct red intensities, allowing sequence tests.
    path = tmp_path / ('numbered-' + fps.replace('/', '-') + '.mov')
    values = [20 + (47 * i % 210) for i in range(count)]
    raw = b''.join(bytes([v, 0, 0]) * (160 * 90) for v in values)
    made = subprocess.run([ffmpeg_executable(), '-v', 'error', '-y', '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', '160x90', '-framerate', fps, '-i', '-', '-c:v', 'qtrle', str(path)], input=raw, capture_output=True)
    assert made.returncode == 0, made.stderr.decode()
    return path, values


def frame_values(path):
    result = subprocess.run([ffmpeg_executable(), '-v', 'error', '-i', str(path), '-an', '-vf', 'scale=1:1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    return list(result.stdout[::3])


@pytest.mark.parametrize('percentage,indices', [(50, [i for i in range(8) for _ in range(2)]), (200, [0, 2, 4, 6]), (-100, list(reversed(range(8)))), (0, [0] * 8)])
def test_actual_retime_frame_sequence(tmp_path, percentage, indices):
    source, values = numbered_source(tmp_path)
    e = Engine(tmp_path)
    e.dispatch('create_project', {'width': 160, 'height': 90})
    m = e.dispatch('import_media', {'path': str(source)})
    # Frame labels are full-range RGB values, independent of Auto decoding.
    e.dispatch('set_media_data_level', {'media_id': m['id'], 'mode': 'Full'})
    c = e.dispatch('append_clip', {'media_id': m['id'], 'out_frame': 8})
    speed = e.dispatch('set_clip_speed', {'clip_id': c['id'], 'percentage': percentage, 'ripple': True})
    assert speed['duration_frames'] == len(indices)
    output = tmp_path / 'retime.mp4'
    rendered = e.dispatch('render', {'output': str(output)})
    assert rendered['duration_frames'] == len(indices)
    decoded = frame_values(output)
    assert len(decoded) == len(indices)
    assert decoded == pytest.approx([values[i] for i in indices], abs=6)


@pytest.mark.parametrize('percentage', [50, -50, 150, -150])
def test_fractional_retime_split_preserves_sequence_and_reopen(tmp_path, percentage):
    source, _ = numbered_source(tmp_path, '30000/1001')
    e = Engine(tmp_path)
    e.dispatch('create_project', {'width': 160, 'height': 90, 'fps': {'num': 30000, 'den': 1001}})
    m = e.dispatch('import_media', {'path': str(source)})
    clip = e.dispatch('append_clip', {'media_id': m['id'], 'out_frame': 8})
    e.dispatch('set_clip_speed', {'clip_id': clip['id'], 'percentage': percentage, 'ripple': True})
    before = tmp_path / 'before-split.mp4'
    e.dispatch('render', {'output': str(before)})
    split = e.dispatch('split_clip', {'clip_id': clip['id'], 'frame': 1})
    relevant = split['first']['source_end'] if percentage > 0 else split['first']['source_start']
    assert relevant['den'] == 2
    after = tmp_path / 'after-split.mp4'
    e.dispatch('render', {'output': str(after)})
    assert frame_values(after) == pytest.approx(frame_values(before), abs=6)
    project = e.dispatch('save_project')['path']
    restored = Engine(tmp_path)
    restored.dispatch('open_project', {'path': project})
    assert restored.get_state() == e.get_state()


def test_retime_ripple_collision_undo_and_freeze_audio(tmp_path, media):
    e, m, first = setup_project(tmp_path, media)
    second = e.dispatch('append_clip', {'media_id': m['id']})
    state = e.get_state()
    with pytest.raises(ValueError):
        e.dispatch('set_clip_speed', {'clip_id': first['id'], 'percentage': float('nan')})
    assert e.get_state() == state
    e.dispatch('set_clip_speed', {'clip_id': first['id'], 'percentage': 50, 'ripple': True})
    assert e._clip(second['id'])[0]['start_frame'] == 48
    e.dispatch('undo')
    assert e.get_state() == state
    e.dispatch('delete_clip', {'clip_id': second['id']})
    e.dispatch('set_clip_speed', {'clip_id': first['id'], 'percentage': 0})
    frozen = tmp_path / 'freeze.wav'
    e.dispatch('render', {'output': str(frozen)})
    import wave, array
    with wave.open(str(frozen)) as w:
        assert w.getnframes() == 48000
        assert max(abs(s) for s in array.array('h', w.readframes(w.getnframes()))) == 0


def test_retime_audio_pitch_preservation_and_unpreserved_pitch(tmp_path, media):
    import wave, array
    e, _, c = setup_project(tmp_path, media)
    def frequency(output):
        with wave.open(str(output)) as w:
            samples = array.array('h', w.readframes(w.getnframes()))[::2]
            rate = w.getframerate()
        samples = samples[int(.05*rate):int(.4*rate)]
        crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
        return crossings / (len(samples) / rate)
    e.dispatch('set_clip_speed', {'clip_id': c['id'], 'percentage': 200, 'ripple': True})
    preserved = tmp_path / 'preserved.wav'
    e.dispatch('render', {'output': str(preserved)})
    assert frequency(preserved) == pytest.approx(440, abs=10)
    e.dispatch('set_clip_speed', {'clip_id': c['id'], 'percentage': 200, 'ripple': True, 'pitch_correction': False})
    pitched = tmp_path / 'pitched.wav'
    e.dispatch('render', {'output': str(pitched)})
    assert frequency(pitched) == pytest.approx(880, abs=10)


def test_retime_audio_cadence_reverse_and_slow_boundaries(tmp_path):
    import wave, array
    source = tmp_path / 'two-tones.wav'
    command = [ffmpeg_executable(), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1', '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:duration=1', '-filter_complex', '[0:a][1:a]concat=n=2:v=0:a=1[a]', '-map', '[a]', '-c:a', 'pcm_s16le', str(source)]
    assert subprocess.run(command, capture_output=True).returncode == 0
    e = Engine(tmp_path)
    e.dispatch('create_project', {'width': 160, 'height': 90})
    m = e.dispatch('import_media', {'path': str(source)})
    c = e.dispatch('append_clip', {'media_id': m['id']})
    for speed, duration, times, expected in [(200, 1, (.1, .7), (440, 880)), (50, 4, (.5, 2.5), (440, 880)), (-100, 2, (.4, 1.4), (880, 440))]:
        e.dispatch('set_clip_speed', {'clip_id': c['id'], 'percentage': speed, 'ripple': True})
        output = tmp_path / f'cadence-{speed}.wav'
        e.dispatch('render', {'output': str(output)})
        with wave.open(str(output)) as w:
            assert w.getnframes() == duration * 48000
            samples = array.array('h', w.readframes(w.getnframes()))[::2]
        for time, wanted in zip(times, expected):
            window = samples[round(time*48000):round((time+.2)*48000)]
            crossings = sum(a <= 0 < b for a, b in zip(window, window[1:]))
            assert crossings / .2 == pytest.approx(wanted, abs=15)


def test_retime_extremes_freeze_selection_and_trim_duration(tmp_path):
    source, values = numbered_source(tmp_path)
    e = Engine(tmp_path)
    e.dispatch('create_project', {'width': 160, 'height': 90})
    m = e.dispatch('import_media', {'path': str(source)})
    # Frame labels are full-range RGB values, independent of Auto decoding.
    e.dispatch('set_media_data_level', {'media_id': m['id'], 'mode': 'Full'})
    c = e.dispatch('append_clip', {'media_id': m['id'], 'out_frame': 8})
    e.dispatch('set_clip_speed', {'clip_id': c['id'], 'percentage': .01, 'ripple': True})
    assert e._clip(c['id'])[0]['duration_frames'] == 80000
    e.dispatch('set_clip_speed', {'clip_id': c['id'], 'percentage': 1600, 'ripple': True})
    assert e._clip(c['id'])[0]['duration_frames'] == 1
    e.dispatch('set_clip_speed', {'clip_id': c['id'], 'percentage': 50, 'ripple': True})
    trimmed = e.dispatch('trim_clip', {'clip_id': c['id'], 'in_frame': 3, 'out_frame': 8})
    assert trimmed['duration_frames'] == 10
    e.dispatch('set_clip_speed', {'clip_id': c['id'], 'percentage': 0})
    output = tmp_path / 'selected-freeze.mp4'
    e.dispatch('render', {'output': str(output)})
    decoded = frame_values(output)
    assert len(decoded) == 10
    assert decoded == pytest.approx([values[3]] * 10, abs=6)


@pytest.mark.parametrize('percentage,ripple', [(100, False), (200, False), (50, False), (200, True), (50, True), (-100, False)])
def test_reference_v2_observed_speed_durations_and_real_frames(tmp_path, percentage, ripple):
    import json
    evidence = json.loads((Path(__file__).resolve().parents[1] / 'research' / 'retime-runtime-v2.json').read_text())
    assert evidence['snapshot']['sha256'] == '022e9aca082b2e6f5e60c363d851480e66d3056f4f88714e1d5fd7dd101dcfb7'
    case = next(row['case'] for row in evidence['records'] if row['case']['percentage'] == percentage and row['case']['ripple'] is ripple)
    assert case['set_speed']['success'] and case['set_speed']['value'] is True
    source, values = numbered_source(tmp_path, count=72)
    e = Engine(tmp_path)
    e.dispatch('create_project', {'width': 160, 'height': 90})
    m = e.dispatch('import_media', {'path': str(source)})
    # Frame labels are full-range RGB values, independent of Auto decoding.
    e.dispatch('set_media_data_level', {'media_id': m['id'], 'mode': 'Full'})
    first = e.dispatch('append_clip', {'media_id': m['id'], 'out_frame': 47})
    second = e.dispatch('append_clip', {'media_id': m['id'], 'out_frame': 47})
    changed = e.dispatch('set_clip_speed', {'clip_id': first['id'], 'percentage': percentage, 'ripple': ripple})
    expected_duration = case['after']['first']['duration']
    expected_next = case['after']['second']['start'] - case['before']['first']['start']
    assert changed['duration_frames'] == expected_duration
    assert e._clip(second['id'])[0]['start_frame'] == expected_next
    if percentage == 50 and not ripple:
        assert changed['source_end'] == {'num': 47, 'den': 2}
    output = tmp_path / 'reference-duration.mp4'
    e.dispatch('render', {'output': str(output)})
    decoded = frame_values(output)
    if percentage > 0:
        indices = [int(i * percentage / 100) for i in range(expected_duration)]
    else:
        indices = [46 - i for i in range(expected_duration)]
    assert decoded[:expected_duration] == pytest.approx([values[i] for i in indices], abs=7)
    if expected_next > expected_duration:
        assert max(decoded[expected_duration:expected_next]) < 8
    assert decoded[expected_next:expected_next+47] == pytest.approx(values[:47], abs=7)
    saved = e.dispatch('save_project')['path']
    reopened = Engine(tmp_path)
    reopened.dispatch('open_project', {'path': saved})
    assert reopened.get_state() == e.get_state()


@pytest.mark.parametrize('freeze_frame', [0, 12, 46])
def test_reference_v3_freeze_at_playhead_splits_tail_and_renders(tmp_path, freeze_frame):
    import json
    evidence = json.loads((Path(__file__).resolve().parents[1] / 'research' / 'freeze-all-runtime-v3.json').read_text())
    assert evidence['snapshot']['sha256'] == 'b3204ee82522293c4ab0a69bb9361e0ba1b648d06cdb12938c3a828f060e096b'
    case = next(row['case'] for row in evidence['records'] if row['case'].get('seek_frame') == freeze_frame and row['case']['timeline'].startswith('REA_FREEZE_20261021_143926'))
    assert case['seek_result'] and case['set_speed']['success'] and case['set_speed']['value'] is True
    source, values = numbered_source(tmp_path, count=72)
    e = Engine(tmp_path)
    e.dispatch('create_project', {'width': 160, 'height': 90})
    m = e.dispatch('import_media', {'path': str(source)})
    # Frame labels are full-range RGB values, independent of Auto decoding.
    e.dispatch('set_media_data_level', {'media_id': m['id'], 'mode': 'Full'})
    first = e.dispatch('append_clip', {'media_id': m['id'], 'out_frame': 47})
    second = e.dispatch('append_clip', {'media_id': m['id'], 'out_frame': 47})
    before = e.get_state()
    frozen = e.dispatch('set_clip_speed', {'clip_id': first['id'], 'percentage': 0, 'freeze_frame': freeze_frame})
    assert frozen['start_frame'] == freeze_frame
    assert frozen['duration_frames'] == 47 - freeze_frame
    assert frozen['in_frame'] == freeze_frame
    assert frozen['speed_percentage'] == 0
    assert e._clip(second['id'])[0]['start_frame'] == 47
    if freeze_frame:
        assert frozen['id'] != first['id']
        prefix = e._clip(first['id'])[0]
        assert prefix['duration_frames'] == freeze_frame
        assert prefix['speed_percentage'] == 100
    actual_items = sorted(e._timeline()['tracks'][0]['clips'], key=lambda c: c['start_frame'])
    reference_items = case['after']['all']
    baseline = case['before']['first']['start']
    assert [(c['start_frame'], c['duration_frames'], c['speed_percentage']) for c in actual_items] == [(c['start'] - baseline, c['duration'], c['speed']['Percentage']) for c in reference_items]
    output = tmp_path / 'freeze-split.mp4'
    e.dispatch('render', {'output': str(output)})
    assert frame_values(output)[:47] == pytest.approx(values[:freeze_frame] + [values[freeze_frame]] * (47-freeze_frame), abs=7)
    e.dispatch('undo')
    assert e.get_state() == before
    for invalid in (-1, 47, 48):
        with pytest.raises(ValueError):
            e.dispatch('set_clip_speed', {'clip_id': first['id'], 'percentage': 0, 'freeze_frame': invalid})
        assert e.get_state() == before


def test_nonripple_speed_consumes_source_handles_without_moving_audio_edits(tmp_path):
    import wave, array
    source = tmp_path / 'source-handles.wav'
    made = subprocess.run([ffmpeg_executable(), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1', '-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:duration=1', '-filter_complex', '[0:a][1:a]concat=n=2:v=0:a=1[a]', '-map', '[a]', '-c:a', 'pcm_s16le', str(source)], capture_output=True)
    assert made.returncode == 0
    e = Engine(tmp_path)
    e.dispatch('create_project', {'width': 160, 'height': 90})
    m = e.dispatch('import_media', {'path': str(source)})
    first = e.dispatch('append_clip', {'media_id': m['id'], 'out_frame': 24})
    second = e.dispatch('append_clip', {'media_id': m['id'], 'out_frame': 24})
    changed = e.dispatch('set_clip_speed', {'clip_id': first['id'], 'percentage': 200, 'ripple': False})
    assert changed['duration_frames'] == 24 and changed['source_end'] == {'num': 48, 'den': 1}
    assert e._clip(second['id'])[0]['start_frame'] == 24
    output = tmp_path / 'handles.wav'
    e.dispatch('render', {'output': str(output)})
    with wave.open(str(output)) as w:
        assert w.getnframes() == 96000
        samples = array.array('h', w.readframes(w.getnframes()))[::2]
    for time, expected in ((.1, 440), (.7, 880), (1.4, 440)):
        window = samples[round(time*48000):round((time+.2)*48000)]
        crossings = sum(a <= 0 < b for a, b in zip(window, window[1:]))
        assert crossings / .2 == pytest.approx(expected, abs=15)
    e.dispatch('undo')
    slowed = e.dispatch('set_clip_speed', {'clip_id': first['id'], 'percentage': 50, 'ripple': False})
    assert slowed['duration_frames'] == 24 and slowed['source_end'] == {'num': 12, 'den': 1}
    assert e._clip(second['id'])[0]['start_frame'] == 24


@pytest.mark.parametrize('channels', [1, 2])
def test_audio_channel_mapping_and_limiter_preserve_unity_pcm(tmp_path, channels):
    import wave, array
    source = tmp_path / f'channels-{channels}.wav'
    generator = 'sine=frequency=440:sample_rate=48000:duration=1' if channels == 1 else 'aevalsrc=0.1*sin(2*PI*440*t)|0.2*sin(2*PI*660*t):s=48000:d=1'
    made = subprocess.run([ffmpeg_executable(), '-v', 'error', '-y', '-f', 'lavfi', '-i', generator, '-c:a', 'pcm_s16le', str(source)], capture_output=True)
    assert made.returncode == 0, made.stderr.decode()
    e = Engine(tmp_path)
    e.dispatch('create_project', {'width': 160, 'height': 90})
    m = e.dispatch('import_media', {'path': str(source)})
    assert m['audio_channels'] == channels
    e.dispatch('append_clip', {'media_id': m['id']})
    output = tmp_path / 'unity.wav'
    # Legacy projects lack channel metadata; render must inspect it without
    # changing authoritative project state.
    del e.project['media'][0]['audio_channels']
    del e.project['media'][0]['audio_layout']
    before = e.get_state()
    e.dispatch('render', {'output': str(output)})
    assert e.get_state() == before
    with wave.open(str(source)) as reader:
        original = array.array('h', reader.readframes(reader.getnframes()))
    with wave.open(str(output)) as reader:
        assert reader.getnchannels() == 2 and reader.getnframes() == 48000
        rendered = array.array('h', reader.readframes(reader.getnframes()))
    if channels == 1:
        assert rendered[::2] == rendered[1::2]
        expected = array.array('h', (value for sample in original for value in (sample, sample)))
    else:
        expected = original
    assert max(abs(a-b) for a,b in zip(expected,rendered)) <= 1
    original_energy = sum(value*value for value in expected)
    rendered_energy = sum(value*value for value in rendered)
    assert rendered_energy / original_energy == pytest.approx(1, abs=.0005)


@pytest.mark.parametrize('percentage', [100, 50, -100, 150])
def test_detached_audio_preserves_pcm_and_survives_video_delete(tmp_path, media, percentage):
    e, _, clip = setup_project(tmp_path, media)
    e.dispatch('set_clip_speed', {'clip_id': clip['id'], 'percentage': percentage, 'ripple': True})
    e.dispatch('set_clip_properties', {'clip_id': clip['id'], 'properties': {'volume': .7, 'fade_in_frames': 3, 'fade_out_frames': 3}})
    before = e.get_state()
    baseline = tmp_path/'embedded.wav'
    e.dispatch('render', {'output': str(baseline)})
    detached = e.dispatch('detach_audio', {'clip_id': clip['id']})
    assert detached['video']['audio_enabled'] is False
    assert detached['audio']['audio_enabled'] is True
    assert detached['audio']['id'] != clip['id']
    after = e.get_state()
    for key in ('source_start', 'source_end', 'duration_frames', 'speed_percentage', 'properties'):
        assert detached['audio'][key] == detached['video'][key]
    e.dispatch('undo')
    assert e.get_state() == before
    e.dispatch('redo')
    assert e.get_state() == after
    result = tmp_path/'detached.wav'
    e.dispatch('render', {'output': str(result)})
    import wave
    def pcm(path):
        with wave.open(str(path)) as stream:
            return stream.readframes(stream.getnframes())
    assert pcm(baseline) == pcm(result)
    saved = tmp_path/'detached.json'
    e.dispatch('save_project', {'path': str(saved)})
    e.dispatch('open_project', {'path': str(saved)})
    e.dispatch('delete_clip', {'clip_id': clip['id']})
    assert e._clip(detached['audio']['id'])[0]['audio_enabled'] is True
    video = tmp_path/'audio-remains.mov'
    e.dispatch('render', {'output': str(video)})
    assert max(pixel(video, .25)) < 10
    remaining = tmp_path/'remaining.wav'
    e.dispatch('render', {'output': str(remaining)})
    assert pcm(baseline) == pcm(remaining)


def test_detach_destination_validation_is_atomic(tmp_path, media):
    e, _, clip = setup_project(tmp_path, media)
    first = e.dispatch('detach_audio', {'clip_id': clip['id']})
    state = e.get_state()
    with pytest.raises(ValueError, match='already'):
        e.dispatch('detach_audio', {'clip_id': clip['id']})
    assert e.get_state() == state
    e.dispatch('undo')
    assert 'audio_enabled' not in e._clip(clip['id'])[0]
    e.dispatch('append_clip', {'media_id': clip['media_id'], 'track_id': first['audio_track_id']})
    state = e.get_state()
    with pytest.raises(ValueError, match='overlap'):
        e.dispatch('detach_audio', {'clip_id': clip['id'], 'track_id': first['audio_track_id']})
    assert e.get_state() == state
    other = e.dispatch('create_timeline', {'name': 'Other'})
    destination = next(t['id'] for t in other['tracks'] if t['kind'] == 'audio')
    state = e.get_state()
    with pytest.raises(ValueError, match='same timeline'):
        e.dispatch('detach_audio', {'clip_id': clip['id'], 'track_id': destination})
    assert e.get_state() == state
    result = e.dispatch('detach_audio', {'clip_id': clip['id']})
    assert result['audio_track_id'] != first['audio_track_id']
    assert e._clip(result['audio']['id'])[1]['kind'] == 'audio'


def test_linked_ripple_delete_matches_native_audio_video_readback(tmp_path, media):
    import json
    native=json.loads((Path(__file__).resolve().parents[1]/'research/transition-deletion-runtime.json').read_text())
    case=next(r['case'] for r in native['records'] if r['case']['ripple'])
    e=Engine(tmp_path)
    e.dispatch('create_project',{'name':'Linked ripple','width':160,'height':90})
    # Native ranges span 48 frames; test sources are 24 frames, loop only fixture generation.
    source=tmp_path/'long.mp4'
    subprocess.run([ffmpeg_executable(),'-v','error','-y','-stream_loop','2','-i',str(media[0]),'-c','copy',str(source)],check=True)
    m=e.dispatch('import_media',{'path':str(source)})
    first=e.dispatch('append_clip',{'media_id':m['id'],'in_frame':12,'out_frame':60})
    second=e.dispatch('append_clip',{'media_id':m['id'],'in_frame':12,'out_frame':60})
    e.dispatch('add_transition',{'clip_id':first['id']})
    detached=e.dispatch('detach_audio',{'clip_id':first['id'],'linked':True})
    later=e.dispatch('detach_audio',{'clip_id':second['id'],'linked':True})
    before=e.get_state()
    result=e.dispatch('ripple_delete',{'clip_id':first['id']})
    assert set(result['deleted_clip_ids'])=={first['id'],detached['audio']['id']}
    assert set(result['shifted_clip_ids'])=={second['id'],later['audio']['id']}
    origin=case['before']['audio'][0]['start']
    for kind in ('video','audio'):
        actual=[(c['start_frame'],c['duration_frames']) for t in e._timeline()['tracks'] if t['kind']==kind for c in t['clips']]
        expected=[(c['start']-origin,c['duration']) for c in case['after'][kind]]
        assert actual==expected
    assert not e._timeline()['transitions']
    after=e.get_state()
    e.dispatch('undo'); assert e.get_state()==before
    e.dispatch('redo'); assert e.get_state()==after
    saved=tmp_path/'linked.json'
    e.dispatch('save_project',{'path':str(saved)})
    e.dispatch('open_project',{'path':str(saved)})
    assert e._clip(second['id'])[0]['link_group_id']==e._clip(later['audio']['id'])[0]['link_group_id']
    e.dispatch('delete_clip',{'clip_id':second['id']})
    assert 'link_group_id' not in e._clip(later['audio']['id'])[0]


def test_link_unlink_constraints_and_ripple_group_ranges(tmp_path, media):
    from frameforge.control import validate
    e,m,first=setup_project(tmp_path,media)
    audio=e.dispatch('detach_audio',{'clip_id':first['id'],'linked':True})['audio']
    second=e.dispatch('append_clip',{'media_id':m['id'],'start_frame':48})
    third=e.dispatch('append_clip',{'media_id':m['id'],'start_frame':72})
    second_audio=e.dispatch('detach_audio',{'clip_id':second['id'],'linked':True})['audio']
    third_audio=e.dispatch('detach_audio',{'clip_id':third['id']})['audio']
    # Relink four clips spanning a gap. Each involved track closes exactly its deleted ranges.
    ids=[first['id'],audio['id'],second['id'],second_audio['id']]
    e.dispatch('link_clips',{'clip_ids':ids})
    before=e.get_state()
    for bad in ([first['id']], [first['id'],first['id']], 'bad', [first['id'],{}]):
        with pytest.raises(ValueError):validate('link_clips',{'clip_ids':bad})
        with pytest.raises(ValueError):e.dispatch('link_clips',{'clip_ids':bad})
        assert e.get_state()==before
    e.dispatch('unlink_clips',{'clip_id':first['id']})
    assert all('link_group_id' not in e._clip(i)[0] for i in ids)
    e.dispatch('undo'); assert e.get_state()==before
    e.dispatch('ripple_delete',{'clip_id':first['id']})
    assert e._clip(third['id'])[0]['start_frame']==24
    assert e._clip(third_audio['id'])[0]['start_frame']==24
