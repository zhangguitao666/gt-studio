"""Native generator observations plus timing/precision composition invariants."""
import json
from pathlib import Path
import pytest

from test_fusion import real_project, add, connect, pixels, pixel
from test_fusion_frames import rgba, sample
from test_transitions import colored_sources


REFERENCE = json.loads((Path(__file__).parent/'fixtures/fusion-alpha-ramp.json').read_text())
GENERATORS = [c for c in REFERENCE['cases'] if c['spec'].get('back') != 'media']


@pytest.mark.parametrize('case', GENERATORS, ids=[c['name'] for c in GENERATORS])
def test_captured_native_generator_alpha_blend_and_lower_tracks(tmp_path, colored_sources, case):
    e, clip = real_project(tmp_path, colored_sources)
    spec = case['spec']
    if spec.get('lower'):
        lower = add(e, clip, 'Background', Green=1 if spec['lower'] == 'green' else 0)
        connect(e, clip, 'MediaOut1', 'Input', lower)
        track = e.dispatch('add_track', {'kind': 'video'})
        clip = e.dispatch('append_clip', {'media_id': e.project['media'][0]['id'], 'track_id': track['id'], 'out_frame': 12})['id']
    target = add(e, clip, 'Background', Blue=1, Alpha=spec['alpha'])
    if 'blend' in spec:
        back = add(e, clip, 'Background', Red=1)
        merge = add(e, clip, 'Merge', Blend=spec['blend'])
        connect(e, clip, merge, 'Background', back); connect(e, clip, merge, 'Foreground', target); target = merge
    connect(e, clip, 'MediaOut1', 'Input', target)
    output = tmp_path/'actual.mov'; e.dispatch('render', {'output': str(output)})
    raw = pixels(output); assert len(raw) == 12*32*32*3
    for frame in (0, 5, 11):
        assert pixel(raw, 16, 16, frame) == pytest.approx(case['native_rgb_center'], abs=6)


def test_zero_alpha_rgb_survives_only_inside_offset_clip_interval(tmp_path, colored_sources):
    e, lower = real_project(tmp_path, colored_sources)
    e.dispatch('trim_clip', {'clip_id': lower, 'out_frame': 24})
    green = add(e, lower, 'Background', Green=1); connect(e, lower, 'MediaOut1', 'Input', green)
    track = e.dispatch('add_track', {'kind': 'video'})
    top = e.dispatch('append_clip', {'media_id': e.project['media'][0]['id'], 'track_id': track['id'], 'out_frame': 12, 'start_frame': 6})['id']
    blue = add(e, top, 'Background', Blue=1, Alpha=0); connect(e, top, 'MediaOut1', 'Input', blue)
    output = tmp_path/'offset.mov'; e.dispatch('render', {'output': str(output)})
    raw = pixels(output); assert len(raw) == 24*32*32*3
    for frame in (0, 5, 18, 23): assert pixel(raw, 16, 16, frame) == pytest.approx((0, 253, 0), abs=6)
    for frame in (6, 11, 17): assert pixel(raw, 16, 16, frame) == pytest.approx((0, 253, 253), abs=6)


def test_opacity_and_fades_scale_associated_rgb_even_when_alpha_is_zero(tmp_path, colored_sources):
    e, clip = real_project(tmp_path, colored_sources)
    blue = add(e, clip, 'Background', Blue=1, Alpha=0); connect(e, clip, 'MediaOut1', 'Input', blue)
    e.dispatch('set_clip_properties', {'clip_id': clip, 'opacity': .5, 'fade_in_frames': 4, 'fade_out_frames': 4})
    output = tmp_path/'fades.mov'; e.dispatch('render', {'output': str(output)})
    raw = pixels(output)
    for frame, blue_value in ((0, 0), (2, 64), (4, 128), (8, 128), (10, 64)):
        assert pixel(raw, 16, 16, frame) == pytest.approx((0, 0, blue_value), abs=6)


@pytest.mark.parametrize('graph_on_left,graph_on_right', [(True,False), (False,True), (True,True), (False,False)])
def test_cross_dissolve_preserves_glowing_rgb_and_mixed_legacy_side(tmp_path, colored_sources, graph_on_left, graph_on_right):
    e, left = real_project(tmp_path, colored_sources)
    e.dispatch('trim_clip', {'clip_id': left, 'in_frame': 12, 'out_frame': 36})
    media = e.dispatch('import_media', {'path': str(colored_sources[1])})
    right = e.dispatch('append_clip', {'media_id': media['id'], 'in_frame': 12, 'out_frame': 36})['id']
    if graph_on_left:
        red = add(e, left, 'Background', Red=1, Alpha=0); connect(e, left, 'MediaOut1', 'Input', red)
    if graph_on_right:
        blue = add(e, right, 'Background', Blue=1, Alpha=0); connect(e, right, 'MediaOut1', 'Input', blue)
    if not graph_on_left and not graph_on_right:
        track = e.dispatch('add_track', {'kind':'video'})
        top = e.dispatch('append_clip', {'media_id':media['id'], 'track_id':track['id'], 'out_frame':48})['id']
        transparent = add(e, top, 'Background', Alpha=0)
        connect(e, top, 'MediaOut1', 'Input', transparent)
    e.dispatch('add_transition', {'clip_id': left, 'duration_frames': 12})
    output = tmp_path/'dissolve.mov'; e.dispatch('render', {'output': str(output)})
    raw = pixels(output); assert len(raw) == 48*32*32*3
    for frame, expected in ((17,(253,0,0)), (18,(244,0,10)), (24,(117,0,136)), (29,(10,0,244)), (30,(0,0,253))):
        actual = pixel(raw, 16, 16, frame)
        assert actual == pytest.approx(expected, abs=7), f'frame={frame}, actual={actual}, expected={expected}, graph_sides={(graph_on_left,graph_on_right)}'
    for frame in (*range(18), *range(30,48)):
        expected = (253,0,0) if frame < 18 else (0,0,253)
        assert pixel(raw,16,16,frame) == pytest.approx(expected,abs=7), f'Outside transition at frame {frame}'


def test_transform_and_merge_retain_more_than_eight_bit_channel_precision(tmp_path, colored_sources):
    e, clip = real_project(tmp_path, colored_sources)
    back = add(e, clip, 'Background', Red=.12345)
    front = add(e, clip, 'Background', Blue=.54321, Alpha=.25)
    transform = add(e, clip, 'Transform'); connect(e, clip, transform, 'Input', front)
    merge = add(e, clip, 'Merge', Blend=.33335)
    connect(e, clip, merge, 'Background', back); connect(e, clip, merge, 'Foreground', transform)
    connect(e, clip, 'MediaOut1', 'Input', merge)
    output = tmp_path/'precise.png'; e.dispatch('render_fusion_frame', {'clip_id': clip, 'output': str(output)})
    assert sample(rgba(output)) == pytest.approx((.12345*(1-.25*.33335)*65535, 0, .54321*.33335*65535, 65535), abs=4)
