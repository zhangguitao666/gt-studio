"""Retain a minimal straight-alpha diagnostic for the bundled FFmpeg."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from frameforge.engine import ffmpeg_executable
from frameforge.fusion import default_graph, make_node, compile_graph


def main():
    graph = default_graph()
    bg = make_node('Background', 'bg', parameters={'Blue': 1, 'Alpha': 0.5})
    transform = make_node('Transform', 'tr', parameters={'Size': 0.5, 'CenterX': 0.75, 'CenterY': 0.75})
    transform['inputs']['Input'] = 'bg'
    graph['nodes'] += [bg, transform]; graph['nodes'][1]['inputs']['Input'] = 'tr'
    filters, out = compile_graph(graph, '[0:v]null', {'width': 32, 'height': 32, 'fps': {'num': 24, 'den': 1}}, 12, 'probe')
    ffmpeg = Path(ffmpeg_executable())
    observations = []
    for mode in ('auto', 'rgb'):
        selected = ';'.join(filters).replace('format=rgb:alpha=straight:shortest=1', f'format={mode}:alpha=straight:shortest=1')
        command = [str(ffmpeg), '-v', 'error', '-filter_complex_threads', '1', '-f', 'lavfi', '-i', 'color=red:s=32x32:r=24:d=0.5', '-filter_complex', selected, '-map', '['+out+']', '-frames:v', '1', '-pix_fmt', 'rgba64le', '-f', 'rawvideo', '-']
        result = subprocess.run(command, capture_output=True, check=True)
        at = (8*32+24)*8
        pixel = list(struct.unpack('<4H', result.stdout[at:at+8]))
        observations.append({'overlay_format': mode, 'command': command, 'output_sha256': hashlib.sha256(result.stdout).hexdigest(), 'rgba16': pixel})
    assert observations[0]['rgba16'][2] < 20000
    assert observations[1]['rgba16'][2] > 65000
    report = {'ffmpeg': {'path': str(ffmpeg), 'sha256': hashlib.sha256(ffmpeg.read_bytes()).hexdigest()},
              'expected_straight_rgba16': [0, 0, 65535, 32767], 'observations': observations,
              'conclusion': 'Explicit RGB preserves straight blue better for this transparent transform in this FFmpeg build, with an 8-bit compositing boundary.',
              'native_fusion_comparison': False}
    target = ROOT/'research/fusion-alpha-diagnostic.json'; target.write_text(json.dumps(report, indent=2)+'\n'); print(target)


if __name__ == '__main__': main()
