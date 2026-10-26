"""Capture owned native pan signals, or inspect the portable PCM evidence.

This measures the native reference only. It does not test an independent pan
implementation or turn a fitted transient into a verified DSP algorithm.
"""
import argparse
import array
import base64
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import wave
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pcm_array(raw):
    values = array.array('i')
    values.frombytes(raw)
    if sys.byteorder != 'little':
        values.byteswap()
    return values


def capture():
    from frameforge.engine import ffmpeg_executable
    cases = []
    for bits, label in ((24, 'pan'), (32, 'pan32')):
        runtime = ROOT/'research'/('audio-'+label+'-runtime.json')
        status = ROOT/'research'/('audio-'+label+'-status.json')
        records = json.loads(runtime.read_text())['records']
        statuses = [r['case']['after'] for r in json.loads(status.read_text())['records']
                    if r['case']['after'].get('audio_'+label+'_status')]
        assert len(statuses)==1 and not statuses[0]['rendering']
        jobs = {j['id']: j['status'] for j in statuses[0]['jobs']}
        for record in records:
            row = record['case']; data = row['after']; spec = data['case']
            assert row['completed'] and len(spec['items'])==1
            job = data['jobs'][0]['id']
            assert jobs[job]['JobStatus']=='Complete' and jobs[job]['CompletionPercentage']==100
            item = spec['items'][0]; properties = data['clips'][0]['properties']
            assert properties['AudioPan']==item['pan'] and properties['AudioVolume']==0
            assert properties['AudioPanEnabled'] and data['fps']==24
            source = ROOT/'workspace'/('audio-'+label+'-native')/(item['source']+'.wav')
            values = (4096,) if item['source']=='mono' else (4096, 8192)
            with wave.open(str(source), 'rb') as wav:
                assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes())==(len(values), 2, 48000, 96000)
                assert wav.readframes(96000)==struct.pack('<'+'h'*len(values), *values)*96000
            output = source.parent/(row['timeline']+'.mov')
            diagnostic = subprocess.run([ffmpeg_executable(), '-hide_banner', '-i', str(output)],
                                        capture_output=True, text=True).stderr
            codec = 'pcm_s'+str(bits)+'le'
            audio_lines = [line.strip() for line in diagnostic.splitlines() if 'Audio:' in line]
            assert len(audio_lines)==1 and codec in audio_lines[0] and '48000 Hz, stereo' in audio_lines[0]
            raw = subprocess.check_output([ffmpeg_executable(), '-v', 'error', '-i', str(output),
                '-vn', '-c:a', 'pcm_s32le', '-f', 's32le', '-'])
            assert len(raw)==96000*2*4
            cases.append({'name': spec['name'], 'source': item['source'], 'pan': item['pan'],
                'bits': bits, 'job': job, 'native_status': jobs[job], 'version': data['version'],
                'timeline': row['timeline'], 'properties': properties,
                'source_sha256': sha(source.read_bytes()), 'container_sha256': sha(output.read_bytes()),
                'codec_readback': audio_lines[0], 'runtime_sha256': sha(runtime.read_bytes()),
                'status_sha256': sha(status.read_bytes()), 'pcm_s32le_bytes': len(raw),
                'pcm_s32le_sha256': sha(raw),
                'pcm_s32le_zlib': base64.b64encode(zlib.compress(raw, 9)).decode()})
    assert len(cases)==17
    return {'schema_version': 1, 'sample_rate': 48000, 'source_frames': 96000,
        'sources': {'mono': [4096], 'stereo': [4096, 8192]},
        'source_format': 'Owned constant S16LE WAV; no vendor media or database contents.',
        'scope': 'Measured native pan export evidence, not an independent implementation.',
        'cases': cases, 'full_resolve_parity': False}


def analyze(fixture):
    results, decoded = [], {}
    for case in fixture['cases']:
        raw = zlib.decompress(base64.b64decode(case['pcm_s32le_zlib']))
        assert len(raw)==case['pcm_s32le_bytes'] and sha(raw)==case['pcm_s32le_sha256']
        samples = pcm_array(raw)
        assert len(samples)==192000
        source = fixture['sources'][case['source']]
        channels = []
        for channel in (0, 1):
            signal = samples[channel::2]
            baseline = source[min(channel, len(source)-1)]*65536
            target = signal[10000]
            assert all(v==target for v in signal[5000:-72])
            changing = [n for n in range(72, len(signal)-72) if signal[n]!=target]
            departures = [n for n in range(72, 5000) if signal[n]!=baseline]
            target_gain = target/baseline
            channels.append({'target_pcm_s32le': target, 'target_gain': target_gain,
                'target_db': 20*math.log10(target_gain),
                'first_nonunity_after_head': departures[0] if departures else None,
                'last_unsettled_after_head': changing[-1] if changing else None,
                'gain_at_sample_1000': signal[1000]/baseline})
        results.append({'name': case['name'], 'bits': case['bits'], 'pan': case['pan'],
                        'channels': channels})
        decoded[(case['name'], case['bits'])] = samples
    cross_precision, candidate_models = [], []
    for (name, bits), fine in decoded.items():
        if bits!=32:
            continue
        coarse = decoded[(name, 24)]
        expected = [round(v/256)*256 for v in fine]
        mismatches = sum(a!=b for a,b in zip(expected, coarse))
        cross_precision.append({'name': name, 'nearest_even_32_to_24_changed_scalars': mismatches})
        # Explicitly retain the failed hypothesis. Targets come from measured
        # settled samples; this fit is never used by the production renderer.
        for channel in (0, 1):
            baseline = fixture['sources']['mono'][0]*65536
            target = fine[20000+channel]/baseline
            gain, changed, peak = 1., 0, 0
            first = []
            for n in range(129, 5000):
                gain = target if abs(target-gain)<.001 else gain+(target-gain)*.00200801
                value = struct.unpack('<f', struct.pack('<f', .125*gain))[0]
                own, native = round(value*2147483648), fine[n*2+channel]
                if own!=native:
                    changed += 1
                    peak = max(peak, abs(own-native))
                    if len(first)<4:
                        first.append([n, native, own])
            candidate_models.append({'name': name, 'channel': channel,
                'model': 'Measured target, unity through n=128, double one-pole alpha=.00200801, snap below .001, float32 product.',
                'compared_sample_frames': 4871, 'changed': changed,
                'max_delta_s32': peak, 'first_differences': first,
                'equivalent': changed==0})
    # Bounds are observations of selected PCM payloads, not general DSP rules.
    return {'cases': results, 'case_count': len(results), 'cross_precision': cross_precision,
        'candidate_transient_models': candidate_models,
        'native_jobs_complete': 17, 'full_resolve_parity': False,
        'implementation_status': 'Native pan curve and startup smoothing remain under calibration; GT Studio pan is not implemented.',
        'limitations': ['DC only, default stereo bus, 48kHz, 24fps, two-second clips, selected pan values.',
            'A one-pole approximation leaves sample residuals; its coefficient and arithmetic are not established.',
            'Different clip starts, contiguous joins, gain changes, sine/music, multichannel and automation remain unmeasured.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true', help='Read completed local native exports and replace the portable fixture')
    parser.add_argument('--fixture', type=Path, default=ROOT/'research/audio-pan-fixtures.json')
    parser.add_argument('--output', type=Path, default=ROOT/'research/audio-pan-observations.json')
    args = parser.parse_args()
    if args.capture:
        args.fixture.write_text(json.dumps(capture(), ensure_ascii=False, indent=2)+'\n')
    raw = args.fixture.read_bytes()
    report = analyze(json.loads(raw))
    report['fixture_sha256'] = sha(raw)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'case_count': report['case_count'], 'cross_precision': report['cross_precision'],
                      'output': str(args.output), 'full_resolve_parity': False}))


if __name__=='__main__':
    main()
