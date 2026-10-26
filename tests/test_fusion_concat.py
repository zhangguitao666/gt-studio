"""Adjacent Transform behavior observed in native texture exports."""
import array
import copy
import hashlib
import json
from pathlib import Path
import struct
import subprocess

import pytest

from frameforge.engine import Engine, ffmpeg_executable
from frameforge.fusion import compile_graph
from test_fusion import model, add, connect, pixels
from test_fusion_frames import rgba


REFERENCE = json.loads((Path(__file__).parent/'fixtures/fusion-concat-reference.json').read_text())
RESTORED = [c for c in REFERENCE['cases'] if c['name'] != 'identity' and 'flattened' not in c['name']]


@pytest.mark.parametrize('case', RESTORED, ids=lambda c: c['name'])
def test_native_default_chains_restore_all_texture_frames(tmp_path, case):
    baseline = next(c for c in REFERENCE['cases'] if c['name']=='identity')
    assert case['status']['JobStatus'] == 'Complete' and case['identity_rgb_exact']
    assert case['native_rgb24_full_sha256'] == baseline['native_rgb24_full_sha256']
    source = tmp_path/'texture.mov'
    subprocess.run([ffmpeg_executable(), '-v', 'error', '-f', 'lavfi', '-i',
        "nullsrc=s=32x32:r=24:d=0.5,format=gbrp,geq=r='16+mod(X*7+Y*3,220)':g='16+mod(X*3+Y*5,220)':b='16+mod(X*5+Y*11,220)'",
        '-c:v', 'qtrle', str(source)], check=True)
    e = Engine(tmp_path/'project'); e.dispatch('create_project', {'width':32, 'height':32})
    media = e.dispatch('import_media', {'path':str(source)})
    clip = e.dispatch('append_clip', {'media_id':media['id'], 'out_frame':12})['id']
    identity = add(e, clip, 'Transform'); connect(e, clip, identity, 'Input', 'MediaIn1')
    connect(e, clip, 'MediaOut1', 'Input', identity)
    direct = tmp_path/'identity.mov'; e.dispatch('render', {'output':str(direct)})
    e.dispatch('clear_fusion_graph', {'clip_id':clip})
    target = 'MediaIn1'
    for native_node in sorted((n for n in case['native_nodes'] if n['class']=='Transform'), key=lambda n:n['name']):
        p = native_node['inputs']
        assert p['FlattenTransform'] == 0 and p['FilterMethod'] == 2
        current = add(e, clip, 'Transform', Size=p['Size'], Angle=p['Angle'], CenterX=p['Center'][0], CenterY=p['Center'][1])
        connect(e, clip, current, 'Input', target); target = current
    connect(e, clip, 'MediaOut1', 'Input', target)
    saved = e.dispatch('save_project')['path']; e.dispatch('open_project', {'path':saved})
    before = copy.deepcopy((e.project, e._undo, e._redo))
    actual = tmp_path/'chain.mov'; e.dispatch('render', {'output':str(actual)})
    assert pixels(actual) == pixels(direct)
    assert (e.project, e._undo, e._redo) == before


def test_noncommuting_scale_rotation_and_translation_order(tmp_path):
    e, clip = model(tmp_path)
    blue = add(e, clip, 'Background', Blue=1, Alpha=.5)
    first = add(e, clip, 'Transform', Size=.5, CenterX=.75, CenterY=.75)
    second = add(e, clip, 'Transform', Size=2, CenterX=.625, Angle=90)
    connect(e, clip, first, 'Input', blue); connect(e, clip, second, 'Input', first)
    a = tmp_path/'chain.png'; e.dispatch('render_fusion_frame', {'clip_id':clip, 'node_id':second, 'output':str(a)})
    # On the 32px canvas: (8,-8) rotates to (-8,-8), scales to
    # (-16,-16), then translates by (4,0), giving (-12,-16).
    single = add(e, clip, 'Transform', CenterX=.125, CenterY=1, Angle=90)
    connect(e, clip, single, 'Input', blue)
    b = tmp_path/'single.png'; e.dispatch('render_fusion_frame', {'clip_id':clip, 'node_id':single, 'output':str(b)})
    assert rgba(a) == rgba(b)


def test_branched_intermediate_and_composed_output_remain_independent(tmp_path):
    e, clip = model(tmp_path)
    bg = add(e, clip, 'Background', Blue=.8, Alpha=.5)
    first = add(e, clip, 'Transform', Size=.5, CenterX=.75, CenterY=.75)
    second = add(e, clip, 'Transform', Angle=90)
    connect(e, clip, first, 'Input', bg); connect(e, clip, second, 'Input', first)
    merge = add(e, clip, 'Merge', Blend=.5)
    connect(e, clip, merge, 'Background', first); connect(e, clip, merge, 'Foreground', second)
    planes = []
    before = copy.deepcopy(e.project)
    for name, node in [('first',first), ('second',second), ('merged',merge)]:
        p = tmp_path/(name+'.png'); e.dispatch('render_fusion_frame', {'clip_id':clip, 'node_id':node, 'output':str(p)})
        samples = array.array('H'); samples.frombytes(rgba(p)); planes.append(samples)
    assert e.project == before
    back, front, combined = planes
    expected = [back[i]*(1-.5*front[i//4*4+3]/65535)+.5*front[i] for i in range(len(back))]
    assert list(combined) == pytest.approx(expected, abs=3)


@pytest.mark.parametrize('size', [.01, 8])
def test_maximum_length_chain_has_bounded_sampling_work(tmp_path, size):
    e, clip = model(tmp_path)
    target = add(e, clip, 'Background', Blue=1)
    for _ in range(61):
        current = add(e, clip, 'Transform', Size=size)
        connect(e, clip, current, 'Input', target); target = current
    connect(e, clip, 'MediaOut1', 'Input', target)
    graph = e.get_fusion_graph(clip)['graph']
    filters, output = compile_graph(graph, '[0:v]null', e.project, 1, 'probe', force_output=True)
    result = subprocess.run([ffmpeg_executable(), '-v', 'error', '-filter_complex_threads', '1',
        '-filter_complex', ';'.join(filters), '-map', '['+output+']', '-frames:v', '1',
        '-pix_fmt', 'gbrapf32le', '-f', 'rawvideo', 'pipe:1'], capture_output=True, check=True, timeout=10)
    actual = struct.unpack('<4096f', result.stdout)
    expected = ([0.]*4096 if size<1 else [0.]*1024+[1.]*1024+[0.]*1024+[1.]*1024)
    assert actual == tuple(expected)


def test_captured_native_sequential_rotation_alpha_plane(tmp_path):
    e, clip = model(tmp_path); e.project.update(width=640, height=360)
    bg = add(e, clip, 'Background', Blue=1)
    first = add(e, clip, 'Transform', Size=.5, CenterX=.75, CenterY=.75)
    second = add(e, clip, 'Transform', Angle=90)
    connect(e, clip, first, 'Input', bg); connect(e, clip, second, 'Input', first)
    p = tmp_path/'rotated.png'; e.dispatch('render_fusion_frame', {'clip_id':clip, 'node_id':second, 'output':str(p)})
    samples = array.array('H'); samples.frombytes(rgba(p))
    carrier = b''.join(struct.pack('<H', (round(v*255/65535)*257)&0xfff0) for v in samples[3::4])
    assert hashlib.sha256(carrier).hexdigest() == REFERENCE['previous_rotation_alpha']['alpha16le_frame0_sha256']
