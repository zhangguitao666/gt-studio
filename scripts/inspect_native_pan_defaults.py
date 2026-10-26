"""Read version-bound native pan smoothing defaults without executing Resolve.

REA records the selected Mach-O identity separately. This focused system-otool
inspection retains only facts from three direct calls and a bounded data range;
it is not a generic caller graph or proof of runtime routing/sample-rate rules.
"""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = Path('/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/libFairlightPage.dylib')
EXPECTED_SHA = '153686267784cdd4c09cdd0824f26874a25c22e8a3d71c9cdf70c6348b0c5989'
CALLS = (0x6f5a34, 0x6fa8b4, 0x6faae8)


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def read_constant(raw, address):
    offset = 0
    if raw[:4]==b'\xca\xfe\xba\xbe':
        for i in range(struct.unpack_from('>I', raw, 4)[0]):
            cpu, _, start, _, _ = struct.unpack_from('>5I', raw, 8+20*i)
            if cpu==0x100000c:
                offset = start
                break
        else:
            raise ValueError('No arm64 slice')
    if raw[offset:offset+4]!=b'\xcf\xfa\xed\xfe':
        raise ValueError('Expected little-endian 64-bit Mach-O')
    count = struct.unpack_from('<I', raw, offset+16)[0]
    position = offset+32
    for _ in range(count):
        command, size = struct.unpack_from('<II', raw, position)
        if command==0x19:
            segment, vm, _, file_offset, file_size = struct.unpack_from('<16sQQQQ', raw, position+8)
            if vm<=address and address+4<=vm+file_size:
                at = offset+file_offset+address-vm
                result = {'virtual_address': hex(address), 'file_offset': at,
                    'segment': segment.rstrip(b'\0').decode(), 'bits': hex(struct.unpack_from('<I', raw, at)[0]),
                    'float32': struct.unpack_from('<f', raw, at)[0]}
                sections = struct.unpack_from('<I', raw, position+64)[0]
                for k in range(sections):
                    section = position+72+80*k
                    name, _, va, length = struct.unpack_from('<16s16sQQ', raw, section)
                    if va<=address<va+length:
                        result['section'] = name.rstrip(b'\0').decode()
                return result
        position += size
    raise ValueError('Selected address is not file backed')


def inspect(path):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest!=EXPECTED_SHA:
        raise ValueError('Library identity differs; refresh native address evidence before using this version-bound inspector')
    base = read_constant(raw, 0x1d2145c)
    weight = read_constant(raw, 0x1d21458)
    process = subprocess.Popen(['/usr/bin/otool', '-arch', 'arm64', '-tvV', str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    history = deque(maxlen=16)
    calls, lines = [], 0
    for line in process.stdout:
        lines += 1
        instruction = re.match(r'^([0-9a-f]{16})\s+(.+)$', line.strip())
        if instruction:
            address = int(instruction[1], 16)
            if '\tbl\t' in line and 'MixPole8SetAlphaEf' in line:
                context = '\n'.join(history)
                assert address in CALLS
                assert 'symbol stub for: _powf' in context
                assert '0x1d21000' in context and '#0x45c' in context
                assert '#0xcccd' in context and '#0x3e4c, lsl #16' in context
                calls.append(hex(address))
        history.append(line.strip())
    _, error = process.communicate(timeout=10)
    if process.returncode:
        raise RuntimeError(error)
    assert len(calls)==3
    exponent = f32(.2)
    beta = f32(base['float32']**exponent)
    assert struct.pack('<f', beta)==struct.pack('<I', 0x3f7f7c67)
    return {'target': str(path), 'sha256': digest, 'architecture': 'arm64',
        'tool': '/usr/bin/otool -arch arm64 -tvV', 'lines_examined': lines,
        'direct_named_setalpha_calls': calls, 'base': base, 'legacy_weight': weight,
        'exponent': {'bits': '0x3e4ccccd', 'float32': exponent},
        'default_beta': beta, 'default_beta_bits': '0x3f7f7c67',
        'runtime_branch': {'flag_address': '0x1dfdc18',
            'observed_static_condition': '>=1 selects MixPole; otherwise a legacy five-sample weighted-update path',
            'runtime_value_verified': False},
        'limitations': ['The base is in writable __DATA,__data, not a proven immutable runtime constant.',
            'Only three direct named BL call sites are covered; indirect/inlined/writer paths are not exhaustive.',
            'Nearest exported labels do not identify stripped local functions.',
            'No target execution, sample-rate independence, final resampling order or legacy runtime equivalence is established.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=LIBRARY)
    parser.add_argument('--output', type=Path, default=ROOT/'research/evidence/pan-smoothing-defaults.json')
    args = parser.parse_args()
    result = inspect(args.binary.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__=='__main__':
    main()
