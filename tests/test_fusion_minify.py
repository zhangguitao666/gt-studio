"""Captured shrink coverage plus a float reference for the generalized sampler."""
import array
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess

import pytest

from frameforge.engine import ffmpeg_executable
from frameforge.fusion import transform_float_image
from test_fusion import model, add, connect
from test_fusion_frames import rgba


@pytest.mark.parametrize('size', [.01, .37, .5, .99])
def test_shrink_float_footprint_black_edges_and_independent_channels(size):
    width = height = 8
    angle, x, y = 21, .3, -.7
    # g,b,r,a plane order. Include negative/superwhite RGB and zero-alpha RGB.
    planes = [[(i % 8)/7-.5 for i in range(64)],
              [2-(i // 8)/7 for i in range(64)],
              [(i % 5)/4 for i in range(64)],
              [0 if i % 3 else .5 for i in range(64)]]
    raw = struct.pack('<256f', *(v for plane in planes for v in plane))
    graph = ';'.join(transform_float_image('0:v', 'out', width, height, x, y, size, angle))
    result = subprocess.run([ffmpeg_executable(), '-v', 'error', '-filter_complex_threads', '1',
        '-f', 'rawvideo', '-pixel_format', 'gbrapf32le', '-video_size', '8x8', '-i', 'pipe:0',
        '-filter_complex', graph, '-map', '[out]', '-frames:v', '1', '-pix_fmt', 'gbrapf32le',
        '-f', 'rawvideo', 'pipe:1'], input=raw, capture_output=True, check=True)
    actual = struct.unpack('<256f', result.stdout)
    radius, theta = 1/size, math.radians(angle)
    expected = []
    for plane in planes:
        for oy in range(height):
            for ox in range(width):
                dx, dy = ox-3.5-x, oy-3.5-y
                sx = (math.cos(theta)*dx-math.sin(theta)*dy)/size+3.5
                sy = (math.sin(theta)*dx+math.cos(theta)*dy)/size+3.5
                def weights(center):
                    return [(i, max(0, 1-abs(i-center)/radius))
                            for i in range(math.ceil(center-radius), math.floor(center+radius)+1)]
                horizontal, vertical = weights(sx), weights(sy)
                numerator = sum(plane[iy*width+ix]*wx*wy for ix, wx in horizontal
                                for iy, wy in vertical if 0 <= ix < width and 0 <= iy < height)
                expected.append(numerator/(sum(w for _, w in horizontal)*sum(w for _, w in vertical)))
    assert actual == pytest.approx(expected, abs=3e-7)
    # Smallest supported Size must not expand into a command-line sized tap grid.
    assert len(graph) < 10000


def test_captured_native_half_size_full_alpha_plane(tmp_path):
    fixture = json.loads((Path(__file__).parent/'fixtures/fusion-shrink-alpha.json').read_text())
    e, clip = model(tmp_path)
    e.project['width'], e.project['height'] = fixture['width'], fixture['height']
    bg = add(e, clip, 'Background', Blue=1, Alpha=.5)
    transform = add(e, clip, 'Transform', Size=.5, CenterX=.75, CenterY=.75)
    connect(e, clip, transform, 'Input', bg)
    connect(e, clip, 'MediaOut1', 'Input', transform)
    output = tmp_path/'shrink.png'
    e.dispatch('render_fusion_frame', {'clip_id': clip, 'output': str(output)})
    samples = array.array('H'); samples.frombytes(rgba(output))
    # Match the captured native export's alpha precision, not its RGB encoder.
    carrier = b''.join(struct.pack('<H', (round(v*255/65535)*257) & 0xfff0)
                       for v in samples[3::4])
    assert hashlib.sha256(carrier).hexdigest() == fixture['alpha16le_frame0_sha256']
