#!/usr/bin/env python3
"""Summarize saved REA records and current implementation declarations, without executing Resolve."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'research/evidence'


def source_record(path):
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def implementation_inventory():
    result = []
    for path in sorted((ROOT / 'frameforge').glob('*.py')):
        tree = ast.parse(path.read_text())
        declarations = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                declarations.append({'name': node.name, 'kind': type(node).__name__, 'line': node.lineno, 'end_line': node.end_lineno})
        item = dict(source_record(path), declarations=declarations, evidence_status='source_inspected_not_runtime_verified')
        if path.name == 'control.py':
            assignment = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SCHEMAS' for t in n.targets))
            item['actions'] = [k.value for k in assignment.value.keys]
        result.append(item)
    return result


def main():
    records = {name: json.loads((EVIDENCE / f'resolve-{name}.json').read_text()) for name in ('plist', 'macho', 'artifact', 'native-ui')}
    evidence = {}
    for name, record in records.items():
        evidence[name] = dict(source_record(EVIDENCE / f'resolve-{name}.json'),
            evidence_id=record.get('evidence_id'), subject=record.get('subject'),
            operation=record.get('operation'), limitations=record.get('limitations', []),
            status='evidence_record' if record.get('evidence_id') else 'error_not_observation')
    a = records['artifact']['normalized_result']
    substep = next(s for s in a['substeps'] if s['operation'] == 'inventory_artifact')
    inventory = substep['evidence']['normalized_result']
    counts = {'nodes': len(inventory['nodes']), 'occurrences': len(inventory['occurrences']), 'edges': len(inventory['edges'])}
    for key, count in counts.items():
        assert inventory['manifest'][{'nodes':'node_count','occurrences':'occurrence_count','edges':'edge_count'}[key]] == count
    assert len({n['artifact_id'] for n in inventory['nodes']}) == counts['nodes']
    assert len({n['occurrence_id'] for n in inventory['occurrences']}) == counts['occurrences']
    nodes = {n['artifact_id']: n for n in inventory['nodes']}
    categories = {'compositing': ('libFusionPage', '/Fusion/'), 'audio': ('libFairlightPage', 'libBMDAudioPlugins', 'libVoiceIsolation', 'libDolbyAtmos'),
        'color': ('libOpenColorIO', 'CanonLUTs', 'default_cm_config'), 'codec_camera': ('REDDecoder', 'libArriImageSdk', 'libavcodec', 'libavformat', 'libDNxSDK', 'libSonyRawDev'),
        'ai_candidates': ('libtorch', 'libonnxruntime', 'libllama', 'libggml'), 'hardware': ('libDaVinciPanels', 'libgpudetect'),
        'project_network': ('libpq.', 'libdavcloudclient', 'libcom-api')}
    leads = []
    for i, occurrence in enumerate(inventory['occurrences']):
        path = occurrence['logical_path']
        matched = [name for name, tokens in categories.items() if any(token in path for token in tokens)]
        if matched:
            leads.append({'logical_path': path, 'packaged_path': str(Path(records['artifact']['subject']['local_path']) / path),
                'categories': matched, 'occurrence_id': occurrence['occurrence_id'], 'artifact_id': occurrence['artifact_id'],
                'sha256': nodes.get(occurrence['artifact_id'], {}).get('sha256'),
                'anchor': f'/normalized_result/substeps/0/evidence/normalized_result/occurrences/{i}',
                'interpretation': 'Name/path lead only; does not establish execution, algorithm, feature support or parity.'})
    m = records['macho']['normalized_result']
    ui = records['native-ui']
    runtime_path = ROOT / 'research/runtime-observations.json'
    runtime = json.loads(runtime_path.read_text()) if runtime_path.is_file() else {}
    console = runtime.get('original_console_observation', {})
    implementation = implementation_inventory()
    actions = next((entry.get('actions', []) for entry in implementation if entry['path'].endswith('/control.py')), [])
    report = {'schema_version': 1, 'evidence': evidence,
        'installed_bundle': records['plist']['normalized_result']['bundle'],
        'artifact_inventory': {'manifest': inventory['manifest'], 'verified_array_counts': counts,
            'inventory_evidence_id': substep['evidence_id'], 'coverage': inventory['coverage'],
            'limitations': a['limitations'], 'count_meaning': 'Deduplicated artifact nodes and path occurrences, not independent feature counts.'},
        'macho': {k: m[k] for k in ('selected_architecture','architectures','build_metadata','dependencies','entrypoints')},
        'symbols': {k: {'observed_item_count':len(m[k]['items']), 'reported_total':m[k]['total'], 'exhaustive':m[k]['exhaustive'], 'limitations':m[k]['limitations']} for k in ('imports','exports')},
        'native_ui': {'error_code':ui.get('code'), 'message':ui.get('message'), 'evidence_id':ui.get('evidence_id'),
            'runtime_verified':False, 'interpretation':'CLI input validation error is not UI evidence.'},
        'runtime_boundary': {'original_console_calls_observed': bool(console),
            'provenance': 'Native CUA transcription, separate from canonical REA Evidence records.',
            'observation_source': source_record(runtime_path) if runtime_path.is_file() else None,
            'console_observation': console,
            'independent_application_observation':runtime.get('independent_application'),
            'earlier_external_bridge_probe':runtime.get('api_bridge_probe'),
            'unique_runtime_verified_method_count':None,
            'count_limitations':'Invocation count is not unique method count. Successful pcall does not prove non-nil return or complete semantics. The original retained payload was later archived via a saved marker; inspect its independent provenance.',
            'raw_console_probe_file_exists':(EVIDENCE / 'resolve-runtime-api-payload.json').is_file(),
            'raw_console_payload_archive':runtime.get('runtime_payload_archive'),
            'source':'research/runtime-observations.json; inspect its capture and payload limitations.'},
        'packaged_name_leads': leads, 'implementation':implementation,
        'implementation_action_count':len(actions),
        'full_functional_parity_verified':False}
    destination = ROOT / 'research/summary.json'
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'output':str(destination), 'counts':counts,'dependencies':len(m['dependencies']['items']), 'symbols':report['symbols'], 'packaged_leads':len(leads)}))

if __name__ == '__main__':
    main()
