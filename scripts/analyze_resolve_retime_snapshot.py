#!/usr/bin/env python3
"""Read a dedicated Resolve SQLite backup; retain exact structural facts, not timing semantics."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import plistlib
import re
import sqlite3
import zlib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TABLES = ['Sm2Timeline','Sm2Sequence','Sm2SequenceContainer','Sm2TiTrack','Sm2TiItem','SmSpeedProfile',
          'SM_Project_Sm2Timeline','Sm2Sequence_Sm2TiTrack','Sm2SequenceContainer_Sm2TiTrack',
          'Sm2TiItem_Sm2TiTrack','Sm2TiItem_Sm2TiItem','Sm2Selector_Sm2TiItem','Sm2TiTrack_Sm2TiTrack']


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(path):
    raw = path.read_bytes()
    return {'path':str(path), 'bytes':len(raw), 'sha256':digest(raw)}


def standardized_decode(raw):
    """Only recognize standard compression/plist/XML; never guess native field layouts."""
    layers=[]
    payload=raw
    try:
        if raw.startswith(b'\x1f\x8b'):
            # gzip.decompress is only attempted on bounded saved blobs.
            if len(raw)>1024*1024:return {'status':'compressed_input_too_large'}
            with __import__('io').BytesIO(raw) as stream:
                with gzip.GzipFile(fileobj=stream) as gz: payload=gz.read(1024*1024+1)
            if len(payload)>1024*1024:return {'status':'decompression_limit'}
            layers.append({'format':'gzip','offset':0})
        else:
            offset = next((offset for offset in (0,4) if len(raw)>offset+2 and raw[offset]&15==8 and ((raw[offset]<<8)+raw[offset+1])%31==0),None)
            if offset is not None:
                decoder=zlib.decompressobj()
                payload=decoder.decompress(raw[offset:],1024*1024+1)
                if len(payload)>1024*1024 or decoder.unconsumed_tail:return {'status':'decompression_limit'}
                if not decoder.eof or decoder.unused_data:return {'status':'not_complete_single_zlib_stream'}
                layer={'format':'zlib','offset':offset}
                if offset==4:layer['prefix_hex']=raw[:4].hex()
                layers.append(layer)
        result={'status':'opaque','compression_layers':layers}
        if layers: result.update(decoded_bytes=len(payload),decoded_sha256=digest(payload),decoded_prefix_hex=payload[:64].hex())
        stripped=payload.lstrip()
        if payload.startswith(b'bplist00') or stripped.startswith(b'<?xml') and b'<plist' in stripped[:256]:
            parsed=plistlib.loads(payload)
            result.update(status='standard_plist',value=repr(parsed)[:4000])
        elif stripped.startswith((b'<?xml',b'<')) and b'<!DOCTYPE' not in stripped.upper() and b'<!ENTITY' not in stripped.upper():
            element=ET.fromstring(payload)
            result.update(status='standard_xml',root_tag=element.tag,xml_prefix=payload.decode('utf-8')[:4000])
        # Zstandard bytes may be visible, but no proprietary wrapper or map is decoded.
        if raw.find(b'\x28\xb5\x2f\xfd')>=0:result['zstandard_magic_candidate_offset']=raw.find(b'\x28\xb5\x2f\xfd')
        return result
    except (ValueError,OSError,zlib.error,ET.ParseError,plistlib.InvalidFileException,UnicodeError,EOFError) as exc:
        return {'status':'standard_format_decode_failed','error':str(exc)}


def scalar(value):
    if not isinstance(value,bytes):return value
    result={'sqlite_type':'blob','bytes':len(value),'sha256':digest(value),'prefix_hex':value[:64].hex(),
            'standard_format_inspection':standardized_decode(value)}
    if len(value)<=256:result['full_hex']=value.hex()
    return result


def canonical_row_hash(row):
    exact={key: {'__bytes_hex':value.hex()} if isinstance(value,bytes) else value for key,value in row.items()}
    return digest(json.dumps(exact,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,default=ROOT/'research/evidence/reference-project-snapshot.sqlite')
    parser.add_argument('--output',type=Path,default=ROOT/'research/retime-reference.json')
    args=parser.parse_args()
    snapshot=args.snapshot.resolve()
    # This tool never opens the original live Resolve Project.db.
    if snapshot.name=='Project.db' or not snapshot.is_relative_to((ROOT/'research/evidence').resolve()):
        raise ValueError('Select an explicitly saved snapshot in this project research/evidence directory')
    before=identity(snapshot)
    connection=sqlite3.connect(snapshot.as_uri()+'?mode=ro&immutable=1',uri=True)
    connection.row_factory=sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    integrity=[row[0] for row in connection.execute('PRAGMA integrity_check')]
    schemas,records,raw={},{},{}
    for table in TABLES:
        definition=connection.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?',('table',table)).fetchone()
        if definition is None:continue
        columns=[dict(row) for row in connection.execute(f'PRAGMA table_info("{table}")')]
        primary=[column['name'] for column in sorted(columns,key=lambda c:c['pk']) if column['pk']]
        rows=[dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]
        schemas[table]={'sql':definition[0],'columns':columns,'primary_key_columns':primary,'row_count':len(rows)}
        raw[table]=rows
        records[table]=[{'anchor':{'table':table,'primary_key':{key:row[key] for key in primary}},
                         'canonical_row_sha256':canonical_row_hash(row),
                         'columns':{key:scalar(value) for key,value in row.items()}} for row in rows]
    connection.close()
    assert identity(snapshot)==before,'Snapshot changed while inspected; results invalid'
    cases=[]
    for timeline in raw.get('Sm2Timeline',[]):
        match=re.fullmatch(r'REA_SPEED_(\d{8}_\d{6})_(-?\d+)_(false|true)',timeline.get('Name') or '')
        if not match:continue
        sequence_ids={row['Sm2Sequence_id'] for row in raw.get('Sm2Sequence',[]) if row.get('Sm2Timeline_id')==timeline['Sm2Timeline_id'] or row['Sm2Sequence_id']==timeline.get('Sequence')}
        container_ids={row['Sm2SequenceContainer_id'] for row in raw.get('Sm2SequenceContainer',[]) if row.get('Sm2Sequence_id') in sequence_ids}
        associations=[r for r in raw.get('Sm2SequenceContainer_Sm2TiTrack',[]) if r['DbOwner'] in container_ids]
        associated_tracks={row['DbAssociate'] for row in associations}
        tracks=[row for row in raw.get('Sm2TiTrack',[]) if row.get('Sequence') in sequence_ids or row.get('Sm2Sequence_id') in sequence_ids or row['Sm2TiTrack_id'] in associated_tracks]
        case={'timeline_name':timeline['Name'],'timeline_primary_key':timeline['Sm2Timeline_id'],
              'case_name_parameters':{'percentage':int(match[2]),'ripple':match[3]=='true','stamp':match[1]},
              'name_parameter_interpretation':'Labels of attempted test setup, not proof that SetSpeed ran or returned success.',
              'sequence_primary_keys':sorted(sequence_ids),'container_primary_keys':sorted(container_ids),'tracks':[]}
        for track in tracks:
            memberships=[row for row in raw.get('Sm2TiItem_Sm2TiTrack',[]) if row['DbOwner']==track['Sm2TiTrack_id']]
            members={row['DbAssociate'] for row in memberships}
            items=[row for row in raw.get('Sm2TiItem',[]) if row.get('Sm2TiTrack_id')==track['Sm2TiTrack_id'] or row['Sm2TiItem_id'] in members]
            case['tracks'].append({'track_primary_key':track['Sm2TiTrack_id'],'DbType':track.get('DbType'),'Type':track.get('Type'),
                'container_relation_property_names':[row['DbPropertyName'] for row in associations if row['DbAssociate']==track['Sm2TiTrack_id']],
                'item_membership_rows':memberships,
                'items':[{'primary_key':row['Sm2TiItem_id'],'DbType':row['DbType'],'Name':row.get('Name'),
                    'stored_fields':{key:scalar(row.get(key)) for key in ('Start','Duration','In','MediaStartTime','MediaFilePath','MediaRef','MediaFrameRate','MediaTimemapBA','PreConformMediaExtents','FieldsBlob')},
                    'source_end_frame':None,'speed_percentage':None,
                    'unresolved':'No decoded source-end or speed field; opaque bytes are not timing semantics.'} for row in items]})
        case['later_clip_position_recovery']='Not established: each track has fewer than two stored members' if all(len(t['items'])<2 for t in case['tracks']) else 'Multiple members present; raw Start fields retained, require API corroboration.'
        cases.append(case)
    probe=ROOT/'scripts/probe_resolve_retime.lua'
    data={'schema_version':1,'evidence_type':'read_only_saved_sqlite_structure','snapshot':before,
          'original_database_opened':False,'integrity_check':integrity,
          'row_hash_algorithm':'SHA256 of JSON sorted keys, compact separators, ensure_ascii=True, UTF8; original BLOB represented as {__bytes_hex:full hexadecimal}.',
          'probe_script_current_at_analysis':identity(probe) if probe.is_file() else None,
          'probe_source_limitation':'Current script identity is context only; it may be revised after the experiment. Timeline names do not prove all script actions executed.',
          'case_count':len(cases),'cases':cases,'schemas':schemas,'tables':records,
          'observations':{'SmSpeedProfile_row_count':len(raw.get('SmSpeedProfile',[])),
              'speed_change_demonstrated_by_this_artifact':False,'second_clip_observed_in_each_track':all(len(t['items'])>=2 for c in cases for t in c['tracks']) if cases else False},
          'limitations':['Snapshot state does not establish unsaved in-memory final state.',
              'No Console per-case metrics or successful SetSpeed return captured in this artifact.',
              'Raw column names/values and relation membership are structural facts; frame/time units, source boundaries and speed semantics are not inferred.',
              'No proprietary BLOB layout guessed; binary integer/double interpretation and Zstandard wrapper decoding are intentionally not performed.',
              'An empty SmSpeedProfile table does not prove speed changes are absent throughout the application.',
              'No original Resolve rendering or independent parity proven by database structure.']}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'output':str(args.output),'snapshot_sha256':before['sha256'],'cases':len(cases),'table_counts':{k:v['row_count'] for k,v in schemas.items()}}))

if __name__=='__main__':main()
