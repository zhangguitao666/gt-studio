"""Compare captured native exports with independently rendered MCP projects.

No quality threshold constitutes a pass. Raw decoded RGB and PCM metrics,
length differences and heuristic source-frame matches are retained. Native
source-boundary getters are never equated to our exclusive rational intervals.
"""
from __future__ import annotations
import argparse
import array
import hashlib
import json
import math
from pathlib import Path
import re
import selectors
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from frameforge.engine import ffmpeg_executable
from frameforge.service import Controller, EditorServer


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def command(args, *, timeout=180):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError(result.stderr.decode('utf8', errors='replace')[-6000:])
    return result


def decode_video(path, width=320, height=180, fps=24, max_frames=1000):
    """Bound memory; an observed extra frame explicitly marks truncation."""
    result = command([ffmpeg_executable(), '-v', 'error', '-i', str(path), '-map', '0:v:0', '-an', '-vf', f'fps={fps},scale={width}:{height}:flags=bicubic', '-frames:v', str(max_frames + 1), '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
    size = width * height * 3
    if len(result.stdout) % size:
        raise ValueError('Decoder returned an incomplete RGB frame')
    count = len(result.stdout) // size
    frames = [result.stdout[index*size:(index+1)*size] for index in range(min(count, max_frames))]
    return {'frames': frames, 'observed_frame_count': count, 'complete': count <= max_frames, 'width': width, 'height': height, 'fps': fps, 'limit_frames': max_frames}



def stream_descriptions(path):
    result = subprocess.run([ffmpeg_executable(), '-hide_banner', '-i', str(path)], capture_output=True, text=True, timeout=30)
    return [line.strip() for line in result.stderr.splitlines() if line.lstrip().startswith('Stream #')]


def count_original_frames(path):
    result = command([ffmpeg_executable(), '-v', 'error', '-nostats', '-i', str(path), '-map', '0:v:0', '-an', '-fps_mode', 'passthrough', '-progress', 'pipe:1', '-f', 'null', '-'])
    counts = re.findall(rb'^frame=(\d+)\s*$', result.stdout, re.MULTILINE)
    if not counts:
        raise ValueError('Decoder did not report an original frame count')
    return int(counts[-1])


def image_metrics(native_frames, own_frames):
    details, absolute_sum, squared_sum, channel_count, exact_channels, exact_frames = [], 0, 0, 0, 0, 0
    for index, (native, own) in enumerate(zip(native_frames, own_frames)):
        if len(native) != len(own):
            raise ValueError('Comparison frames must use the same dimensions')
        absolute, squared, exact, maximum = 0, 0, 0, 0
        for a, b in zip(native, own):
            difference = abs(a-b)
            absolute += difference
            squared += difference*difference
            exact += difference == 0
            maximum = max(maximum, difference)
        size = len(native)
        frame_exact = native == own
        details.append({'frame': index, 'mae_rgb_0_255': absolute/size, 'mse_rgb_0_255_squared': squared/size, 'maximum_channel_error': maximum, 'exact_channel_fraction': exact/size, 'exact_rgb_bytes': frame_exact})
        absolute_sum += absolute
        squared_sum += squared
        channel_count += size
        exact_channels += exact
        exact_frames += frame_exact
    return {'aligned_frame_pairs': len(details), 'native_frame_count': len(native_frames), 'independent_frame_count': len(own_frames), 'frame_count_equal': len(native_frames) == len(own_frames), 'unmatched_native_frames': max(0, len(native_frames)-len(own_frames)), 'unmatched_independent_frames': max(0, len(own_frames)-len(native_frames)), 'mae_rgb_0_255': absolute_sum/channel_count if channel_count else None, 'mse_rgb_0_255_squared': squared_sum/channel_count if channel_count else None, 'exact_channel_fraction': exact_channels/channel_count if channel_count else None, 'exact_frame_count': exact_frames, 'all_decoded_frames_byte_equal': bool(details) and exact_frames == len(native_frames) == len(own_frames), 'per_frame': details}


def frame_feature(frame, width=320, height=180, cols=32, rows=18):
    values = []
    for row in range(rows):
        y = min(height-1, int((row+.5)*height/rows))
        for col in range(cols):
            x = min(width-1, int((col+.5)*width/cols))
            index = (y*width+x)*3
            r, g, b = frame[index:index+3]
            values.append((r+2*g+b)//4)
    return values


def estimate_source_sequence(frames, source_features, width=320, height=180):
    """Nearest small luma-grid MSE is an estimate, with no identity pass threshold."""
    observations = []
    for index, frame in enumerate(frames):
        feature = frame_feature(frame, width, height)
        distances = [sum((a-b)**2 for a, b in zip(feature, source))/len(feature) for source in source_features]
        ordered = sorted(range(len(distances)), key=lambda i: distances[i])
        best, second = ordered[:2] if len(ordered) > 1 else (ordered[0], ordered[0])
        observations.append({'output_frame': index, 'estimated_source_frame': best, 'best_feature_mse': distances[best], 'second_best_source_frame': second, 'second_best_feature_mse': distances[second], 'separation_mse': distances[second]-distances[best], 'mean_luma': sum(feature)/len(feature)})
    return {'method': 'Nearest MSE of a 32x18 sampled integer luma grid against normalized source frames; black gaps and retime interpolation may match poorly. No confidence threshold or ground-truth identity claim.', 'source_frame_count': len(source_features), 'estimated_sequence': [x['estimated_source_frame'] for x in observations], 'frames': observations}


def decode_audio(path, sample_rate=48000, channels=2):
    result = subprocess.run([ffmpeg_executable(), '-v', 'error', '-i', str(path), '-map', '0:a:0', '-vn', '-ar', str(sample_rate), '-ac', str(channels), '-c:a', 'pcm_s16le', '-f', 's16le', '-'], capture_output=True, timeout=180)
    if result.returncode:
        error = result.stderr.decode('utf8', errors='replace')
        if 'matches no streams' in error or 'does not contain any stream' in error:
            return {'present': False, 'samples': array.array('h'), 'sample_rate': sample_rate, 'channels': channels, 'decoder_message': error.strip()}
        raise ValueError(error[-6000:])
    if len(result.stdout) % (2*channels):
        raise ValueError('Decoder returned an incomplete PCM sample frame')
    samples = array.array('h', result.stdout)
    if sys.byteorder != 'little':
        samples.byteswap()
    return {'present': True, 'samples': samples, 'sample_rate': sample_rate, 'channels': channels}


def correlation(a, b):
    count = min(len(a), len(b))
    if not count:
        return None
    mean_a, mean_b = sum(a[:count])/count, sum(b[:count])/count
    covariance = sum((x-mean_a)*(y-mean_b) for x,y in zip(a[:count],b[:count]))
    variance_a = sum((x-mean_a)**2 for x in a[:count])
    variance_b = sum((x-mean_b)**2 for x in b[:count])
    return covariance/math.sqrt(variance_a*variance_b) if variance_a and variance_b else None


def audio_summary(audio):
    samples = audio['samples']
    count = len(samples)
    result = {key: value for key,value in audio.items() if key != 'samples'}
    result.update(sample_frames=count//audio['channels'], duration_seconds=count/audio['channels']/audio['sample_rate'], rms_pcm16=math.sqrt(sum(x*x for x in samples)/count) if count else 0, peak_pcm16=max((abs(x) for x in samples), default=0), nonzero_samples=sum(x != 0 for x in samples))
    return result


def audio_metrics(native, own):
    if native['sample_rate'] != own['sample_rate'] or native['channels'] != own['channels']:
        raise ValueError('PCM audio must use common rate and channels')
    a, b = native['samples'], own['samples']
    count = min(len(a), len(b))
    mae = sum(abs(x-y) for x,y in zip(a,b))/count if count else None
    mse = sum((x-y)**2 for x,y in zip(a,b))/count if count else None
    corr = correlation(a,b)
    # Diagnostic only: decimated first-channel windows and +/-25 ms bounded lag.
    stride = 12
    first_a, first_b = a[::native['channels']*stride], b[::own['channels']*stride]
    window = min(len(first_a), len(first_b), 4000)
    best = None
    if window >= 200:
        for lag in range(-100,101):
            left, right = max(0,-lag), max(0,lag)
            value = correlation(first_a[left:left+window],first_b[right:right+window])
            if value is not None and (best is None or value > best['correlation']):
                best = {'lag_independent_minus_native_sample_frames': lag*stride, 'lag_seconds': lag*stride/native['sample_rate'], 'correlation': value, 'decimation_stride': stride, 'comparison_window_decimated_samples': window}
    return {'native': audio_summary(native), 'independent': audio_summary(own), 'aligned_interleaved_samples_compared': count, 'sample_frame_count_equal': len(a) == len(b), 'mae_pcm16': mae, 'mse_pcm16': mse, 'pearson_correlation_aligned': corr, 'aligned_pcm_byte_equal': bool(count) and a == b, 'best_bounded_lag_diagnostic': best, 'lag_limitation': 'First-channel decimation without antialiasing, at most one second and +/-25ms; periodic audio creates ambiguous lag peaks. This is diagnostic, never an automatic alignment or equivalence verdict.'}


class MCPProjectClient:
    """Real stdio MCP client backed by an isolated local editor controller."""
    def __init__(self, workspace):
        self.server = EditorServer(('127.0.0.1', 0), Controller(workspace))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.process = subprocess.Popen([sys.executable, str(ROOT/'frameforge_entry.py'), 'mcp', '--workspace', str(workspace), '--port', str(self.server.server_port)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.sequence = 0
        self.calls = []
        self.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'native-media-comparison', 'version': '1'}})

    def request(self, method, params):
        self.sequence += 1
        self.process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': self.sequence, 'method': method, 'params': params})+'\n')
        self.process.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=180):
                raise ValueError('MCP response timed out')
        line = self.process.stdout.readline()
        if not line:
            raise ValueError('MCP process closed output')
        response = json.loads(line)
        if 'error' in response:
            raise ValueError(str(response['error']))
        return response['result']

    def tool(self, action, **params):
        result = self.request('tools/call', {'name': action, 'arguments': params})
        self.calls.append({'action': action, 'params': params, 'is_error': result.get('isError', False)})
        if result.get('isError'):
            raise ValueError(str(result))
        return result['structuredContent']

    def close(self):
        self.process.terminate()
        try:
            self.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def load_cases(root=ROOT):
    cases = []
    for name in ('retime-runtime-v2.json','freeze-all-runtime-v3.json'):
        path = root/'research'/name
        evidence = json.loads(path.read_text())
        for record in evidence['records']:
            case = record['case']
            if name.startswith('freeze') and 'all' not in case['after']:
                continue
            cases.append({'case': case, 'evidence_path': str(path), 'evidence_sha256': sha256(path), 'snapshot': evidence['snapshot'], 'json_occurrence_hashes': [item['sha256'] for item in record['json_occurrences']]})
    if len(cases) != 10 or len({item['case']['timeline'] for item in cases}) != 10:
        raise ValueError('Expected exactly ten unique captured native cases')
    return cases


def recreate_case(client, case, source, own_dir, width=320, height=180):
    start_call = len(client.calls)
    client.tool('create_project', name=case['timeline'], width=width, height=height, fps=24)
    media = client.tool('import_media', path=str(source))
    first = client.tool('append_clip', media_id=media['id'], in_frame=0, out_frame=47, start_frame=0)
    client.tool('append_clip', media_id=media['id'], in_frame=0, out_frame=47, start_frame=47)
    note = 'Recreated captured action parameters through MCP.'
    if 'seek_frame' in case:
        client.tool('set_playhead', frame=case['seek_frame'])
    params = {'clip_id': first['id'], 'percentage': case['percentage'], 'ripple': case['ripple']}
    if case['percentage'] == 0 and 'seek_frame' not in case:
        native_frame = case['after']['first']['source_start']
        client.tool('set_clip_speed', **params, freeze_frame=0)
        client.tool('trim_clip', clip_id=first['id'], in_frame=native_frame, out_frame=native_frame+1)
        note = f'Selected-state reconstruction: native older whole-clip freeze selected source frame {native_frame}; explicitly froze whole independent clip at frame0 then trimmed frozen source to [{native_frame},{native_frame+1}). This does not establish equivalence of out-of-clip/default playhead action behavior.'
    else:
        client.tool('set_clip_speed', **params)
    own_dir.mkdir(parents=True, exist_ok=True)
    project = own_dir/(case['timeline']+'.json')
    client.tool('save_project', path=str(project))
    output = own_dir/(case['timeline']+'.mov')
    client.tool('render', output=str(output), format='mov')
    return output, {'note': note, 'render_geometry': {'width':width,'height':height,'fps':24}, 'mcp_calls': client.calls[start_call:], 'project': {'path': str(project), 'sha256': sha256(project)}}


def compare_paths(native_path, own_path, source_features, max_frames=1000):
    native = decode_video(native_path, max_frames=max_frames)
    own = decode_video(own_path, max_frames=max_frames)
    images = image_metrics(native['frames'], own['frames'])
    return {'native': {'path': str(native_path), 'sha256': sha256(native_path), 'bytes': native_path.stat().st_size, 'stream_descriptions': stream_descriptions(native_path), 'original_decoded_frame_count': count_original_frames(native_path), 'normalized_decode': {k:v for k,v in native.items() if k != 'frames'}}, 'independent': {'path': str(own_path), 'sha256': sha256(own_path), 'bytes': own_path.stat().st_size, 'stream_descriptions': stream_descriptions(own_path), 'original_decoded_frame_count': count_original_frames(own_path), 'normalized_decode': {k:v for k,v in own.items() if k != 'frames'}}, 'images': images, 'native_source_identity_estimate': estimate_source_sequence(native['frames'], source_features), 'independent_source_identity_estimate': estimate_source_sequence(own['frames'], source_features), 'audio': audio_metrics(decode_audio(native_path), decode_audio(own_path))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-dir', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT/'workspace/demo-media/motion.mp4')
    parser.add_argument('--workspace', type=Path, default=ROOT/'workspace/native-media-comparison')
    parser.add_argument('--report', type=Path, default=ROOT/'research/native-media-comparison.json')
    parser.add_argument('--max-frames', type=int, default=1000)
    parser.add_argument('--independent-width', type=int, default=320)
    parser.add_argument('--independent-height', type=int, default=180)
    args = parser.parse_args(argv)
    if args.max_frames < 1:
        parser.error('--max-frames must be positive')
    if any(value < 2 or value % 2 for value in (args.independent_width,args.independent_height)):
        parser.error('Independent render dimensions must be positive even integers')
    source, native_dir = args.source.resolve(), args.native_dir.resolve()
    source_decode = decode_video(source, max_frames=args.max_frames)
    if not source_decode['complete'] or not source_decode['frames']:
        raise ValueError('Source reference decode must be complete and nonempty')
    features = [frame_feature(frame) for frame in source_decode['frames']]
    executable = Path(ffmpeg_executable()).resolve()
    report = {'schema_version': 1, 'status': 'measured', 'created_unix_seconds': time.time(), 'comparison_scope': 'Actual captured native export files versus isolated independent projects recreated and rendered through stdio MCP; video normalized to320x180 RGB24 at24fps; audio normalized to48000Hz stereo PCM16. No approximate metric is treated as parity.', 'independent_render_geometry': {'width':args.independent_width,'height':args.independent_height,'fps':24}, 'normalization': {'width':320,'height':180,'fps':24,'filter_order':'fps then scale','scale_flags':'bicubic','audio_sample_rate':48000,'audio_channels':2,'maximum_analyzed_frames':args.max_frames}, 'source': {'path':str(source),'sha256':sha256(source),'normalized_frame_count':len(features),'stream_descriptions':stream_descriptions(source)}, 'ffmpeg': {'path':str(executable),'sha256':sha256(executable),'version':command([str(executable),'-version']).stdout.decode().splitlines()[0]}, 'cases': [], 'limitations': ['Source identity is a low-resolution nearest-feature estimate, never exact ground truth.', 'The common320x180 RGB8 normalization is a derived measurement and doesnot establish exactnative-resolution ormanagedcolorpipeline equivalence; originalexportgeometry andstreamdescriptions are retained.', 'Per-frame images compare matching frame indices and retain unmatched frame counts; no temporal realignment is performed.', 'Audio is resampled/downmixed to stereo PCM16; original sample precision/layout and routing require separate validation.', 'Black frames, interpolation and visually repeated patterns make source identity estimates ambiguous.', 'Render settings and codecs can cause differences distinct from retime semantics; both full-file hashes and unthresholded errors are retained.', 'Captured state, mutation semantics, native source-boundary getters and rendered sampling are separate evidence scopes.'], 'full_resolve_parity':False}
    client = MCPProjectClient(args.workspace.resolve())
    try:
        for item in load_cases():
            case = item['case']
            native_path = native_dir/(case['timeline']+'.mov')
            observation = {'native_timeline':case['timeline'],'reference_evidence':{k:v for k,v in item.items() if k != 'case'},'native_case':case}
            if not native_path.is_file():
                observation.update(status='missing_native_export', expected_native_path=str(native_path))
                report['cases'].append(observation)
                continue
            try:
                observation['native_export'] = {'path':str(native_path),'sha256':sha256(native_path),'bytes':native_path.stat().st_size}
                own_path, reconstruction = recreate_case(client, case, source, args.workspace.resolve()/'independent-exports',args.independent_width,args.independent_height)
                observation['reconstruction'] = reconstruction
                observation['independent_export'] = {'path':str(own_path),'sha256':sha256(own_path),'bytes':own_path.stat().st_size}
                observation.update(status='measured', comparison=compare_paths(native_path, own_path, features,args.max_frames))
            except Exception as exc:
                observation.update(status='comparison_failed', error=f'{type(exc).__name__}: {exc}')
            report['cases'].append(observation)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps({'timeline':case['timeline'],'status':observation['status']}), flush=True)
    finally:
        client.close()
    report['measured_cases'] = sum(case['status']=='measured' for case in report['cases'])
    report['missing_cases'] = sum(case['status']=='missing_native_export' for case in report['cases'])
    report['failed_cases'] = sum(case['status']=='comparison_failed' for case in report['cases'])
    report['status'] = 'measured_all_cases' if report['measured_cases']==10 else 'incomplete'
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ('status','measured_cases','missing_cases','failed_cases')}),flush=True)
    return 0 if report['measured_cases']==10 else 1


if __name__ == '__main__':
    raise SystemExit(main())
