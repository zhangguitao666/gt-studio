"""Independent 48kHz clip-pan model calibrated against owned native exports.

Gain changes retain float32 difference state in sixteen-sample groups, with a
512-sample outer block and an analytic stop length. These numerical boundaries
matter: a scalar one-pole on the gain itself does not reproduce the fixtures.
Other rates, automation and arbitrary source/timeline offsets remain unverified.
"""
import math
from pathlib import Path
import struct


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


BETA = f32(1-1/498)
B2 = f32(BETA*BETA)
B3 = f32(B2*BETA)
B4 = f32(B2*B2)
B8 = f32(B4*B4)
B16 = f32(B8*B8)
_LOG = f32(math.log(BETA))
_INV_LOG = f32(f32(.5*_LOG)/f32(_LOG*_LOG+f32(1e-7)))
_EPS2 = f32(1e-6)
_LOG_EPS2 = f32(math.log(_EPS2))


def targets(pan):
    """Selected native values establish a quantized, bounded gain curve.

    Continuous positions between captured values are an explicit interpolation
    model, not a claim of exhaustive native parameter coverage.
    """
    result = []
    for sign in (-1, 1):
        amplitude = 1+sign*pan/100
        db = -6 if amplitude<=0 else max(-6, min(6, round(200*math.log10(amplitude))/10))
        result.append(f32(10**(db/20)))
    return result


def gain_prefix(target, samples):
    """Return a finite prefix ending in constant target, or the clip endpoint."""
    output = [1.]*min(128, samples)
    current = 1.
    while len(output)<samples and current!=target:
        count = min(512, samples-len(output))
        difference = f32(current-target)
        squared = f32(difference*difference)
        length = (0 if squared<=_EPS2 else math.floor(
            max(0, f32(_INV_LOG*f32(_LOG_EPS2-f32(math.log(squared)))))+.5))
        length = min(length, count)
        groups = [[f32(difference*p) for p in (1, BETA, B2, B3)]]
        for _ in range(3):
            groups.append([f32(v*B4) for v in groups[-1]])
        for _ in range(length//16):
            for group in groups:
                output.extend(f32(target+v) for v in group)
            groups = [[f32(v*B16) for v in group] for group in groups]
        group = groups[0]
        for _ in range(length%16//4):
            output.extend(f32(target+v) for v in group)
            group = [f32(v*B4) for v in group]
        difference = group[0]
        for _ in range(length%4):
            output.append(f32(target+difference))
            difference = f32(difference*BETA)
        current = f32(target+difference)
        if length<count:
            output.extend([target]*(count-length))
            current = target
    if len(output)<samples:
        output.append(target)
    return output


def write_envelope(path, pan, samples, sample_rate):
    """Write only the startup; the renderer fills the remaining constant tail."""
    if sample_rate!=48000:
        raise ValueError('Clip pan is currently calibrated only at 48000 Hz')
    gains = targets(pan)
    channels = [gain_prefix(g, samples) for g in gains]
    count = max(map(len, channels))
    payload = bytearray()
    for i in range(count):
        payload.extend(struct.pack('<ff', *(c[min(i, len(c)-1)] for c in channels)))
    header = struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', 36+len(payload), b'WAVE',
        b'fmt ', 16, 3, 2, sample_rate, sample_rate*8, 8, 32, b'data', len(payload))
    Path(path).write_bytes(header+payload)
    return count
