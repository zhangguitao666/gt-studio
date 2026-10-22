"""Recover selected probe JSON from standard Zstd frames in an offline snapshot.

No proprietary wrapper schema is inferred. Exact frame/JSON byte offsets and
hashes retain the relationship to the saved SQLite record.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _selector_bytes(value, label):
    if not isinstance(value, str) or not value or not value.strip():
        raise ValueError(label + ' must be a nonempty string')
    if len(value) > 4096 or any(ord(char) < 32 for char in value):
        raise ValueError(label + ' must be at most 4096 characters without control characters')
    try:
        return value.encode('utf-8', errors='strict')
    except UnicodeError as exc:
        raise ValueError(label + ' must be valid UTF-8 text') from exc


def extract(snapshot, library, marker_name='REA_RETIME_EVIDENCE', json_prefix='{"after":', timeline=None):
    marker_bytes = _selector_bytes(marker_name, 'marker_name')
    prefix_bytes = _selector_bytes(json_prefix, 'json_prefix')
    if timeline is not None:
        _selector_bytes(timeline, 'timeline')
    if not json_prefix.startswith('{'):
        raise ValueError('json_prefix must begin with a JSON object opening brace')
    # A single-member prefix is enough for our marker records. Validate it as a
    # JSON prefix rather than accepting an arbitrary string that cannot match.
    try:
        prefix_example = json.loads(json_prefix + 'null}')
    except json.JSONDecodeError as exc:
        raise ValueError('json_prefix must be a JSON object member prefix such as {"after":') from exc
    if not isinstance(prefix_example, dict) or len(prefix_example) != 1:
        raise ValueError('json_prefix must select one JSON object member')
    snapshot = Path(snapshot).resolve()
    library = Path(library).resolve()
    if not snapshot.is_relative_to(ROOT / 'research/evidence') or snapshot.name == 'Project.db':
        raise ValueError('Select an explicitly saved research/evidence snapshot')
    before = sha(snapshot.read_bytes())
    zstd = ctypes.CDLL(str(library))
    zstd.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    zstd.ZSTD_decompress.restype = ctypes.c_size_t
    zstd.ZSTD_isError.argtypes = [ctypes.c_size_t]
    zstd.ZSTD_isError.restype = ctypes.c_uint
    records = []
    with sqlite3.connect(snapshot.as_uri() + '?mode=ro&immutable=1', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        for row in connection.execute('SELECT * FROM BtLockableBlob'):
            blob = row['FieldsBlob']
            if not isinstance(blob, bytes) or len(blob) > 1024 * 1024:
                continue
            offset = blob.find(b'\x28\xb5\x2f\xfd')
            if offset < 0:
                continue
            buffer = ctypes.create_string_buffer(1024 * 1024)
            size = zstd.ZSTD_decompress(buffer, len(buffer), blob[offset:], len(blob) - offset)
            if zstd.ZSTD_isError(size):
                continue
            decoded = buffer.raw[:size]
            if marker_bytes not in decoded:
                continue
            occurrences = []
            position = 0
            while True:
                position = decoded.find(prefix_bytes, position)
                if position < 0:
                    break
                # Latin-1 supplies a one-byte index solely for JSON boundary
                # discovery. Actual payload is then decoded strictly as UTF-8.
                try:
                    _, end = json.JSONDecoder().raw_decode(decoded[position:].decode('latin-1'))
                    payload = decoded[position:position + end]
                    case = json.loads(payload.decode('utf-8', errors='strict'))
                except (json.JSONDecodeError, UnicodeError) as exc:
                    raise ValueError(f'Invalid selected JSON at BtLockableBlob {row["BtLockableBlob_id"]}, decoded byte offset {position}: {exc}') from exc
                if not isinstance(case, dict):
                    raise ValueError('Selected marker payload must be a JSON object')
                occurrences.append({'decoded_offset': position, 'bytes': len(payload),
                                    'sha256': sha(payload), 'case': case})
                position += end
            if not occurrences:
                continue
            # A marker name is currently observed only as bytes co-occurring in
            # this decoded blob. Do not invent a private wrapper association.
            # Separate exact payload bytes by hash, retaining every occurrence.
            groups = {}
            for occurrence in occurrences:
                groups.setdefault(occurrence['sha256'], []).append(occurrence)
            for group in groups.values():
                if timeline is not None and group[0]['case'].get('timeline') != timeline:
                    continue
                records.append({'table': 'BtLockableBlob', 'primary_key': row['BtLockableBlob_id'],
                                'column': 'FieldsBlob', 'blob_sha256': sha(blob),
                                'zstd_magic_offset': offset, 'decoded_bytes': size,
                                'decoded_sha256': sha(decoded), 'json_occurrences': group,
                                'case': group[0]['case']})
    assert sha(snapshot.read_bytes()) == before, 'Snapshot changed during inspection'
    return {'schema_version': 1, 'evidence_type': 'derived_from_saved_native_probe_markers',
            'snapshot': {'path': str(snapshot), 'sha256': before},
            'decoder': {'path': str(library), 'sha256': sha(library.read_bytes()),
                        'per_blob_output_limit_bytes': 1024 * 1024},
            'marker_name': marker_name, 'json_prefix': json_prefix, 'timeline_filter': timeline,
            'selection_scope': 'Marker bytes co-occur in decoded blob; exact JSON prefix and optional case.timeline filter select payloads. No native wrapper association is inferred.',
            'records': sorted(records, key=lambda r: (str(r['case'].get('timeline', '')), str(r['primary_key']), r['json_occurrences'][0]['sha256'])),
            'limitations': [f'Only payloads with marker {marker_name!r} and JSON prefix {json_prefix!r} are extracted.',
                            'Marker name establishes decoded-blob co-occurrence only, not association with a particular JSON payload or native marker.',
                            'Distinct exact payload hashes in one blob form separate records; optional timeline filter tests exact JSON case.timeline.',
                            'No native wrapper field meanings are inferred.',
                            'Probe readbacks do not prove decoded render or audio equivalence.',
                            'Selected probe cases do not establish general feature or retiming parity.'],
            'full_resolve_parity': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--zstd-library', type=Path, default=Path('/opt/homebrew/lib/libzstd.dylib'))
    parser.add_argument('--marker-name', default='REA_RETIME_EVIDENCE')
    parser.add_argument('--json-prefix', default='{"after":')
    parser.add_argument('--timeline', help='Exact JSON case.timeline value; does not infer native marker association')
    parser.add_argument('--output', type=Path, default=ROOT / 'research/retime-runtime-v2.json')
    args = parser.parse_args()
    result = extract(args.snapshot, args.zstd_library, marker_name=args.marker_name, json_prefix=args.json_prefix, timeline=args.timeline)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'cases': len(result['records']),
                      'completed': sum(r['case'].get('completed') is True for r in result['records']),
                      'marker_name': result['marker_name'], 'json_prefix': result['json_prefix'], 'timeline_filter': result['timeline_filter']}))


if __name__ == '__main__':
    main()
