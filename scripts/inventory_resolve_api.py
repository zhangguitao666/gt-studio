#!/usr/bin/env python3
"""Inventory installed API declarations without copying implementation or docstrings.

Page assignments are organizational inferences, never measured UI/API coverage.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path

DEFAULT_ROOT = Path('/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting')
DEFAULT_APP = Path('/Applications/DaVinci Resolve/DaVinci Resolve.app')
PAGES = ('media', 'cut', 'edit', 'fusion', 'color', 'fairlight', 'deliver')


def anchor(path, node):
    return {'path': str(path), 'line': node.lineno, 'end_line': node.end_lineno}


def groups(owner, method):
    result = []
    if owner in ('MediaStorage', 'MediaPool', 'MediaPoolItem', 'Folder'):
        result.append('media')
    if owner in ('Timeline', 'TimelineItem', 'MediaPool'):
        result.extend(['cut', 'edit'])
    if 'Fusion' in method or owner in ('Fusion', 'FusionComp'):
        result.append('fusion')
    if owner in ('Gallery', 'GalleryStill', 'GalleryStillAlbum', 'Graph', 'ColorGroup') or any(x in method for x in ('Grade', 'LUT', 'CDL', 'ColorGroup', 'Dolby', 'DRX', 'DCTL', 'ColorVersion', 'RemoteVersion', 'LocalVersion', 'NodeGraph')):
        result.append('color')
    if any(x in method for x in ('Audio', 'Fairlight', 'Voice', 'Speech', 'Dialogue', 'Transcri', 'Normalize')):
        result.append('fairlight')
    if any(x in method for x in ('Render', 'Export')):
        result.append('deliver')
    return list(dict.fromkeys(result)) or ['shared']


def file_identity(path):
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scripting-root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--app', type=Path, default=DEFAULT_APP)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'research/feature-inventory.json')
    args = parser.parse_args()
    source = args.scripting_root / 'DaVinciResolveScript.pyi'
    tree = ast.parse(source.read_text())
    classes, module_functions, aliases = [], [], []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            typed_dict = any(ast.unparse(b) == 'TypedDict' for b in node.bases)
            methods, fields = [], []
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append({'name': child.name, 'qualified_name': f'{node.name}.{child.name}',
                        'parameters': ast.unparse(child.args),
                        'returns': ast.unparse(child.returns) if child.returns else None,
                        'source': anchor(source, child), 'page_groups': groups(node.name, child.name),
                        'evidence_status': 'installed_documented_declaration', 'runtime_verified': False})
                elif isinstance(child, ast.AnnAssign):
                    fields.append({'name': ast.unparse(child.target), 'type': ast.unparse(child.annotation), 'source': anchor(source, child)})
            classes.append({'name': node.name, 'kind': 'typed_dictionary' if typed_dict else 'api_object',
                'source': anchor(source, node), 'bases': [ast.unparse(b) for b in node.bases],
                'methods': methods, 'fields_or_constants': fields})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module_functions.append({'name': node.name, 'parameters': ast.unparse(node.args),
                'returns': ast.unparse(node.returns) if node.returns else None, 'source': anchor(source, node), 'runtime_verified': False})
        elif isinstance(node, ast.AnnAssign):
            aliases.append({'name': ast.unparse(node.target), 'annotation': ast.unparse(node.annotation),
                'value': ast.unparse(node.value) if node.value else None, 'source': anchor(source, node)})
        elif isinstance(node, ast.Assign):
            aliases.append({'name': ', '.join(ast.unparse(t) for t in node.targets), 'value': ast.unparse(node.value), 'source': anchor(source, node)})
    methods = [m for c in classes for m in c['methods']]
    stub_resolve = next(c for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'Resolve')
    open_page = next(m for m in stub_resolve.body if isinstance(m, ast.FunctionDef) and m.name == 'OpenPage')
    # Read page tokens from the installed declaration, rather than assuming seven.
    import re
    declared_pages = re.findall(r"'([a-z]+)'", ast.get_docstring(open_page) or '')
    package = []
    contents = args.app / 'Contents'
    if contents.is_dir():
        for child in sorted(contents.iterdir()):
            if child.is_dir():
                descendants = list(child.rglob('*'))
                package.append({'path': str(child), 'kind': 'directory',
                    'file_count': sum(p.is_file() for p in descendants),
                    'direct_entries': sorted(p.name for p in child.iterdir())})
            else:
                package.append({'path': str(child), 'kind': 'file', 'bytes': child.stat().st_size})
    sources = [file_identity(args.scripting_root / p) for p in ('DaVinciResolveScript.pyi', 'README.md', 'CHANGELOG.md')]
    feature_specs = [
        ('media', 'Media ingest, codecs, RAW interpretation, proxy and relink', ['MediaStorage.', 'MediaPool.ImportMedia', 'MediaPool.RelinkClips', 'MediaPoolItem.LinkProxyMedia'], 'Decode reference corpus and compare frames, metadata, channel layout, timecode and proxy/relink outcomes.'),
        ('cut', 'Cut workflows, source tape, sync and multicam', ['MediaPool.CreateMulticamClip', 'TimelineItem.PerformMulticamSmartSwitch', 'Timeline.AutoAlignClips'], 'Record source UI and verify every Cut editing gesture and multicam/sync decision with fixtures.'),
        ('edit', 'Timeline edit semantics, tracks, transitions, keyframes, retime and captions', ['Timeline.', 'TimelineItem.'], 'Compare every operation across overlapping clips, linked A/V, gaps, trim/ripple/roll, undo, keyframes and retime frames.'),
        ('fusion', 'Fusion procedural graph and rendering', ['Resolve.Fusion', 'Timeline.CreateFusionClip', 'TimelineItem.AddFusionComp'], 'Enumerate actual tool registry, parameters, modifiers, expressions, 2D/3D graph evaluation and compare rendered frames.'),
        ('color', 'Grading, nodes, tracking, masks, scopes, color management, ACES and HDR', ['Graph.', 'ColorGroup.', 'Gallery.', 'Timeline.AnalyzeDolbyVision'], 'Measure transforms, scopes, masks/tracking, node ordering, LUT interpolation and HDR metadata against source output.'),
        ('fairlight', 'Fairlight tracks, buses, routing, automation, plugins and mixing', ['Project.ApplyFairlightPresetToCurrentTimeline', 'Timeline.NormalizeAudioLevel', 'Timeline.SetVoiceIsolationState', 'MediaPoolItem.SetAudioMapping'], 'Compare sample-accurate routing, buses, plugin DSP, latency, automation, loudness and multichannel/immersive output.'),
        ('deliver', 'Deliver render queue, codecs, containers and interchange', ['Project.GetRenderFormats', 'Project.GetRenderCodecs', 'Project.StartRendering', 'Timeline.Export'], 'Enumerate formats/codecs at runtime; export fixtures and inspect pixels, samples, metadata, timecode, subtitles and cancellation.'),
        ('shared', 'AI analysis, transcription, speech, captions, reframing and smart switch', ['Timeline.CreateSubtitlesFromAudio', 'TimelineItem.PerformMulticamSmartSwitch', 'MediaPoolItem.TranscribeAudio', 'MediaPool.GenerateSpeech'], 'Enumerate installed models and edition constraints; compare inference outputs, timing, quality and reproducibility on fixtures.'),
        ('shared', 'Project persistence, databases, collaboration and cloud', ['ProjectManager.'], 'Verify project roundtrip, schema migration, concurrent editing/conflicts, recovery, permissions and cloud synchronization.'),
        ('shared', 'Hardware, GPU, control surfaces, capture/output and performance', [], 'Enumerate devices/backends and verify reference frame/audio output, control protocols, realtime latency, cache and scheduling.'),
        ('shared', 'UI fidelity, shortcuts, preferences, accessibility and undo history', ['Resolve.GetKeyboardPresetList', 'Resolve.GetLayoutPresetList', 'Resolve.GetUserPreferencesPresetList'], 'Capture complete source workflows and compare visuals, interaction, keyboard mappings, focus, undo/redo and accessibility.'),
        ('shared', 'MCP operation of the independent project', [], 'Verify discoverable schemas, deterministic project/resource identity, actual feature execution, errors, cancellation and state inspection over stdio MCP.'),
        ('photo', 'Additional installed Photo page declaration', ['Resolve.OpenPage', 'Resolve.GetCurrentPage'], 'Observe installed Photo page and enumerate its workflows before defining parity tests.'),
    ]
    features = []
    for page, name, prefixes, proof in feature_specs:
        features.append({'page_group': page, 'name': name, 'status': 'parity_not_verified',
            'installed_declaration_refs': [dict(qualified_name=m['qualified_name'], source=m['source']) for m in methods if any(m['qualified_name'].startswith(p) for p in prefixes)],
            'required_evidence': proof,
            'limitations': 'Related API declarations are leads only and do not specify or cover the complete named subsystem.'})
    data = {'schema_version': 1,
        'scope': 'Complete AST declaration inventory of the identified installed Python stub; not an exhaustive Resolve feature inventory.',
        'sources': sources, 'runtime_evidence': [],
        'counts': {'classes': len(classes), 'api_object_classes': sum(c['kind'] == 'api_object' for c in classes),
            'typed_dictionary_classes': sum(c['kind'] == 'typed_dictionary' for c in classes),
            'method_declarations': len(methods), 'unique_qualified_method_names': len({m['qualified_name'] for m in methods}),
            'module_functions': len(module_functions), 'module_alias_or_assignment_declarations': len(aliases),
            'fields_and_constants': sum(len(c['fields_or_constants']) for c in classes),
            'runtime_verified_methods': 0},
        'pages': {'conventional_seven': list(PAGES), 'installed_open_page_tokens': declared_pages,
            'source': anchor(source, open_page), 'assignment_status': 'heuristic_organizational_mapping_not_availability_or_coverage'},
        'page_groups': {p: [m['qualified_name'] for m in methods if p in m['page_groups']] for p in (*PAGES, 'shared')},
        'feature_requirements': features,
        'classes': classes, 'module_functions': module_functions, 'aliases_and_assignments': aliases,
        'package_layout': package,
        'limitations': ['Declarations do not prove successful invocation, edition availability, output correctness, or UI completeness.',
            'Page groups overlap and use name/class heuristics; grouping does not establish page-exclusive behavior.',
            'Fusion and FusionComp are empty stub declarations here, so this inventory cannot enumerate Fusion tooling.',
            'Package member names establish presence only, not active loading, algorithms, licensing, or behavioral support.',
            'No proprietary method implementation or full documentation prose is copied.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'counts': data['counts'], 'declared_pages': declared_pages}))

if __name__ == '__main__':
    main()
