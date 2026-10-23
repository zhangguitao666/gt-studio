import copy
import json
from pathlib import Path
import subprocess

import pytest

from frameforge.engine import Engine, ffmpeg_executable
from frameforge.fusion import default_graph, validate_graph
from test_transitions import colored_sources


def model(tmp_path):
    engine = Engine(tmp_path)
    engine.dispatch('create_project', {'name': 'Compositing', 'width': 32, 'height': 32})
    engine.project['media'].append({'id': 'source', 'path': str(tmp_path/'not-opened.mov'), 'name': 'Source', 'video': True, 'audio': True, 'audio_channels': 2, 'still': False, 'duration_seconds': 3})
    clip = engine.dispatch('append_clip', {'media_id': 'source', 'out_frame': 24})
    return engine, clip['id']


def connect(engine, clip, target, port, source=None):
    return engine.dispatch('connect_fusion_nodes', {'clip_id': clip, 'target_node_id': target, 'input': port, **({'source_node_id': source} if source is not None else {})})


def add(engine, clip, kind, **parameters):
    return engine.dispatch('add_fusion_node', {'clip_id': clip, 'type': kind, 'parameters': parameters})['id']


def test_graph_read_is_pure_and_edits_undo_persist_and_split(tmp_path):
    e, clip = model(tmp_path)
    state, history = copy.deepcopy(e.project), copy.deepcopy(e._undo)
    assert e.dispatch('get_fusion_graph', {'clip_id': clip})['graph'] == default_graph()
    assert (e.project, e._undo) == (state, history)
    bg = add(e, clip, 'Background', Blue=1)
    connect(e, clip, 'MediaOut1', 'Input', bg)
    e.dispatch('undo')
    assert e.dispatch('get_fusion_graph', {'clip_id': clip})['graph']['nodes'][1]['inputs']['Input'] == 'MediaIn1'
    e.dispatch('redo')
    saved = e.dispatch('save_project')['path']
    fresh = Engine(tmp_path/'fresh'); fresh.dispatch('open_project', {'path': saved})
    assert fresh.project == e.project
    halves = e.dispatch('split_clip', {'clip_id': clip, 'frame': 12})
    clips = e.project['timelines'][0]['tracks'][0]['clips']
    assert len(clips) == 2 and clips[0]['fusion_graph'] == clips[1]['fusion_graph']
    assert clips[0]['fusion_graph'] is not clips[1]['fusion_graph']
    audio = e.dispatch('detach_audio', {'clip_id': clip})['audio']
    assert 'fusion_graph' not in audio
    with pytest.raises(ValueError, match='video'):
        e.dispatch('get_fusion_graph', {'clip_id': audio['id']})


def test_cycle_and_locked_graph_changes_are_atomic(tmp_path):
    e, clip = model(tmp_path)
    a, b = add(e, clip, 'Transform'), add(e, clip, 'Transform')
    connect(e, clip, a, 'Input', b)
    before = copy.deepcopy((e.project, e._undo, e._redo))
    with pytest.raises(ValueError, match='cycle'):
        connect(e, clip, b, 'Input', a)
    assert (e.project, e._undo, e._redo) == before
    track = e.project['timelines'][0]['tracks'][0]
    e.dispatch('set_track_state', {'track_id': track['id'], 'locked': True})
    before = copy.deepcopy((e.project, e._undo, e._redo))
    with pytest.raises(ValueError, match='locked'):
        e.dispatch('update_fusion_node', {'clip_id': clip, 'node_id': a, 'parameters': {'Size': 0.5}})
    assert (e.project, e._undo, e._redo) == before


@pytest.mark.parametrize('change', ['unknown_type', 'nan', 'bad_port', 'missing_source', 'output_source', 'bad_param', 'delete_output', 'empty_name'])
def test_invalid_edits_reject_without_creating_graph(tmp_path, change):
    e, clip = model(tmp_path)
    before = copy.deepcopy((e.project, e._undo, e._redo))
    with pytest.raises(ValueError):
        if change == 'unknown_type': add(e, clip, 'NativeMagic')
        elif change == 'nan': add(e, clip, 'Background', Red=float('nan'))
        elif change == 'bad_port': connect(e, clip, 'MediaIn1', 'Input', 'MediaOut1')
        elif change == 'missing_source': connect(e, clip, 'MediaOut1', 'Input', 'missing')
        elif change == 'output_source': connect(e, clip, 'MediaOut1', 'Input', 'MediaOut1')
        elif change == 'bad_param': add(e, clip, 'Transform', Blend=0.5)
        elif change == 'delete_output': e.dispatch('delete_fusion_node', {'clip_id': clip, 'node_id': 'MediaOut1'})
        else: e.dispatch('update_fusion_node', {'clip_id': clip, 'node_id': 'MediaIn1', 'name': ''})
    assert (e.project, e._undo, e._redo) == before


def test_incomplete_graph_is_persistable_and_delete_disconnects(tmp_path):
    e, clip = model(tmp_path)
    merge = add(e, clip, 'Merge')
    connect(e, clip, 'MediaOut1', 'Input', merge)
    description = e.dispatch('get_fusion_graph', {'clip_id': clip})
    assert not description['render_ready'] and len(description['errors']) == 2
    saved = e.dispatch('save_project')['path']
    e.dispatch('open_project', {'path': saved})
    assert not e.dispatch('get_fusion_graph', {'clip_id': clip})['render_ready']
    result = e.dispatch('delete_fusion_node', {'clip_id': clip, 'node_id': merge})
    assert len(result['errors']) == 1
    e.dispatch('clear_fusion_graph', {'clip_id': clip})
    assert 'fusion_graph' not in e._clip(clip)[0]


@pytest.mark.parametrize('mutation', ['cycle', 'extra_key', 'duplicate_id', 'bool_version', 'bad_parameter', 'audio_graph'])
def test_corrupt_saved_graph_is_rejected_transactionally(tmp_path, mutation):
    e, clip = model(tmp_path)
    e._clip(clip)[0]['fusion_graph'] = default_graph()
    bad = copy.deepcopy(e.project)
    graph = bad['timelines'][0]['tracks'][0]['clips'][0]['fusion_graph']
    if mutation == 'cycle': graph['nodes'][0]['inputs']['Input'] = 'MediaOut1'
    elif mutation == 'extra_key': graph['lua'] = 'run()'
    elif mutation == 'duplicate_id': graph['nodes'].append(copy.deepcopy(graph['nodes'][0]))
    elif mutation == 'bool_version': graph['version'] = True
    elif mutation == 'bad_parameter': graph['nodes'][0]['parameters']['Value'] = 1
    else: bad['timelines'][0]['tracks'][0]['kind'] = 'audio'
    path = tmp_path/'bad.json'; path.write_text(json.dumps(bad))
    before = copy.deepcopy(e.project)
    with pytest.raises(ValueError): e.dispatch('open_project', {'path': str(path)})
    assert e.project == before


def real_project(tmp_path, colored_sources):
    e = Engine(tmp_path/'project'); e.dispatch('create_project', {'width': 32, 'height': 32})
    media = e.dispatch('import_media', {'path': str(colored_sources[0])})
    clip = e.dispatch('append_clip', {'media_id': media['id'], 'out_frame': 12})
    return e, clip['id']


def pixels(path):
    return subprocess.run([ffmpeg_executable(), '-v', 'error', '-i', str(path), '-an', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout


def pixel(raw, x, y, frame=0):
    index = (frame*32*32 + y*32 + x)*3
    return tuple(raw[index:index+3])


def test_actual_transform_merge_and_bottom_left_coordinates(tmp_path, colored_sources):
    e, clip = real_project(tmp_path, colored_sources)
    bg = add(e, clip, 'Background', Blue=1, Alpha=0.5)
    transform = add(e, clip, 'Transform', Size=0.5, CenterX=0.75, CenterY=0.75)
    merge = add(e, clip, 'Merge', Blend=0.5)
    connect(e, clip, transform, 'Input', bg)
    connect(e, clip, merge, 'Background', 'MediaIn1')
    connect(e, clip, merge, 'Foreground', transform)
    connect(e, clip, 'MediaOut1', 'Input', merge)
    output = tmp_path/'graph.mov'; result = e.dispatch('render', {'output': str(output)})
    assert result['duration_frames'] == 12
    raw = pixels(output)
    assert len(raw) == 12*32*32*3
    for frame in (0, 5, 11):
        # Native generator evidence uses associated over: Blend scales RGB
        # once, while alpha controls the surviving background contribution.
        assert pixel(raw, 24, 8, frame) == pytest.approx((191, 0, 128), abs=6)
        assert pixel(raw, 8, 8, frame) == pytest.approx((253, 0, 0), abs=6)
        assert pixel(raw, 24, 24, frame) == pytest.approx((253, 0, 0), abs=6)


def test_shared_node_fanout_and_alpha_over(tmp_path, colored_sources):
    e, clip = real_project(tmp_path, colored_sources)
    bg = add(e, clip, 'Background', Blue=1, Alpha=0.5)
    merge = add(e, clip, 'Merge')
    connect(e, clip, merge, 'Background', bg)
    connect(e, clip, merge, 'Foreground', bg)
    connect(e, clip, 'MediaOut1', 'Input', merge)
    output = tmp_path/'fanout.mov'; e.dispatch('render', {'output': str(output)})
    assert pixel(pixels(output), 16, 16) == pytest.approx((0, 0, 253), abs=6)


def test_identity_and_disconnected_nodes_leave_decoded_media_exact(tmp_path, colored_sources):
    e, clip = real_project(tmp_path, colored_sources)
    baseline = tmp_path/'baseline.mov'; e.dispatch('render', {'output': str(baseline)})
    add(e, clip, 'Merge')  # Disconnected and incomplete, excluded from output path.
    identity = tmp_path/'identity.mov'; e.dispatch('render', {'output': str(identity)})
    assert pixels(identity) == pixels(baseline)
    connect(e, clip, 'MediaOut1', 'Input')
    before = identity.read_bytes()
    with pytest.raises(ValueError, match='Incomplete Fusion'):
        e.dispatch('render', {'output': str(identity)})
    assert identity.read_bytes() == before


def test_counterclockwise_rotation_moves_asymmetric_shape(tmp_path, colored_sources):
    e, clip = real_project(tmp_path, colored_sources)
    blue = add(e, clip, 'Background', Blue=1)
    small = add(e, clip, 'Transform', Size=0.5, CenterX=0.75, CenterY=0.75)
    rotate = add(e, clip, 'Transform', Angle=90)
    connect(e, clip, small, 'Input', blue)
    connect(e, clip, rotate, 'Input', small)
    connect(e, clip, 'MediaOut1', 'Input', rotate)
    path = tmp_path/'rotated.mov'; e.dispatch('render', {'output': str(path)})
    raw = pixels(path)
    assert pixel(raw, 8, 8) == pytest.approx((0, 0, 255), abs=6)
    assert pixel(raw, 24, 8) == pytest.approx((0, 0, 0), abs=6)
    assert pixel(raw, 8, 24) == pytest.approx((0, 0, 0), abs=6)


def test_rational_fps_and_nonzero_timeline_start_keep_graph_duration(tmp_path, colored_sources):
    e, clip = real_project(tmp_path, colored_sources)
    # A retime keeps the graph generator on the resulting clip duration.
    e.dispatch('set_clip_speed', {'clip_id': clip, 'percentage': 200, 'ripple': True})
    e.dispatch('move_clip', {'clip_id': clip, 'start_frame': 8})
    e.project['fps'] = {'num': 30000, 'den': 1001}
    blue = add(e, clip, 'Background', Blue=1)
    connect(e, clip, 'MediaOut1', 'Input', blue)
    path = tmp_path/'rational.mov'; result = e.dispatch('render', {'output': str(path)})
    raw = pixels(path)
    assert result['duration_frames'] == 14 and len(raw) == 14*32*32*3
    assert pixel(raw, 16, 16, 7) == pytest.approx((0, 0, 0), abs=5)
    for frame in (8, 10, 13):
        assert pixel(raw, 16, 16, frame) == pytest.approx((0, 0, 255), abs=6)
