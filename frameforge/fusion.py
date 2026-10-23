"""Independent, clip-local compositing graph and FFmpeg execution.

Initial image-node subset; this is not the native Fusion engine. MediaIn uses
the retimed clip on the project canvas. Coordinates use a bottom-left origin.
"""
import copy
import math
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
from collections import Counter


CATALOG = {
    'MediaIn': {'inputs': [], 'parameters': {}},
    'MediaOut': {'inputs': ['Input'], 'parameters': {}},
    'Background': {'inputs': [], 'parameters': {k: (v, 0, 1) for k, v in [('Red', 0), ('Green', 0), ('Blue', 0), ('Alpha', 1)]}},
    'Transform': {'inputs': ['Input'], 'parameters': {'CenterX': (0.5, -10, 10), 'CenterY': (0.5, -10, 10), 'Size': (1, 0.01, 8), 'Angle': (0, -3600, 3600)}},
    'Merge': {'inputs': ['Background', 'Foreground'], 'parameters': {'Blend': (1, 0, 1), 'CenterX': (0.5, -10, 10), 'CenterY': (0.5, -10, 10)}},
}


def make_node(kind, identity, name=None, parameters=None, position=None):
    if kind not in CATALOG:
        raise ValueError('Unsupported Fusion node type: ' + str(kind))
    if parameters is not None and not isinstance(parameters, dict):
        raise ValueError('Fusion parameters must be an object')
    return {'id': identity, 'type': kind, 'name': identity if name is None else name,
            'parameters': {**{k: v[0] for k, v in CATALOG[kind]['parameters'].items()}, **(parameters or {})},
            'inputs': {}, 'position': {'x': 0, 'y': 0} if position is None else position}


def default_graph():
    source = make_node('MediaIn', 'MediaIn1', position={'x': 0, 'y': 0})
    output = make_node('MediaOut', 'MediaOut1', position={'x': 320, 'y': 0})
    output['inputs']['Input'] = source['id']
    return {'version': 1, 'nodes': [source, output], 'output_node_id': output['id']}


def finite(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def validate_graph(graph):
    if not isinstance(graph, dict) or set(graph) != {'version', 'nodes', 'output_node_id'} or type(graph['version']) is not int or graph['version'] != 1:
        raise ValueError('Invalid Fusion graph format')
    nodes = graph['nodes']
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 64:
        raise ValueError('Fusion graph requires 1..64 nodes')
    by_id = {}
    for node in nodes:
        if not isinstance(node, dict) or set(node) != {'id', 'type', 'name', 'parameters', 'inputs', 'position'}:
            raise ValueError('Invalid Fusion node fields')
        identity = node['id']
        if not isinstance(identity, str) or not identity.strip() or len(identity) > 128 or identity in by_id:
            raise ValueError('Missing or duplicate Fusion node ID')
        if node['type'] not in CATALOG:
            raise ValueError('Unsupported Fusion node type')
        if not isinstance(node['name'], str) or not node['name'].strip() or len(node['name']) > 256:
            raise ValueError('Invalid Fusion node name')
        spec = CATALOG[node['type']]
        params = node['parameters']
        if not isinstance(params, dict) or set(params) != set(spec['parameters']):
            raise ValueError('Invalid Fusion parameters')
        for key, (_, low, high) in spec['parameters'].items():
            if not finite(params[key], low, high):
                raise ValueError('Fusion parameter out of range: ' + key)
        inputs = node['inputs']
        if not isinstance(inputs, dict) or set(inputs) - set(spec['inputs']) or any(not isinstance(v, str) for v in inputs.values()):
            raise ValueError('Invalid Fusion input ports')
        pos = node['position']
        if not isinstance(pos, dict) or set(pos) != {'x', 'y'} or any(not finite(v, -1e6, 1e6) for v in pos.values()):
            raise ValueError('Invalid Fusion node position')
        by_id[identity] = node
    if sum(n['type'] == 'MediaOut' for n in nodes) != 1 or graph['output_node_id'] not in by_id or by_id[graph['output_node_id']]['type'] != 'MediaOut':
        raise ValueError('Fusion graph needs exactly one designated MediaOut')
    for node in nodes:
        for source in node['inputs'].values():
            if source not in by_id or by_id[source]['type'] == 'MediaOut':
                raise ValueError('Missing Fusion source or source has no image output')
    active, done = set(), set()
    def visit(identity):
        if identity in active:
            raise ValueError('Fusion connections form a cycle')
        if identity in done:
            return
        active.add(identity)
        for source in by_id[identity]['inputs'].values():
            visit(source)
        active.remove(identity); done.add(identity)
    for identity in by_id:
        visit(identity)
    return by_id


def render_order(graph):
    nodes = validate_graph(graph)
    order, seen, errors = [], set(), []
    def walk(identity):
        if identity in seen:
            return
        seen.add(identity)
        node = nodes[identity]
        for port in CATALOG[node['type']]['inputs']:
            if port not in node['inputs']:
                errors.append(f'{node["name"]}.{port} is not connected')
            else:
                walk(node['inputs'][port])
        order.append(node)
    walk(graph['output_node_id'])
    return order, errors


def describe_graph(graph):
    _, errors = render_order(graph)
    return {'graph': copy.deepcopy(graph), 'render_ready': not errors, 'errors': errors,
            'node_catalog': copy.deepcopy(CATALOG), 'native_equivalence_verified': False}


class FusionActions:
    def _fusion_clip(self, clip_id):
        clip, track = self._clip(clip_id)
        if track['kind'] != 'video':
            raise ValueError('Fusion requires a video clip')
        return clip

    def get_fusion_graph(self, clip_id):
        return describe_graph(self._fusion_clip(clip_id).get('fusion_graph', default_graph()))

    def _edit_fusion(self, clip_id):
        clip = self._fusion_clip(clip_id)
        return clip.setdefault('fusion_graph', default_graph())

    def add_fusion_node(self, clip_id, type, name=None, parameters=None, position=None):
        if type == 'MediaOut':
            raise ValueError('The output node already exists')
        graph = self._edit_fusion(clip_id)
        node = make_node(type, 'node_' + uuid.uuid4().hex[:12], name, parameters, position)
        graph['nodes'].append(node)
        validate_graph(graph)
        return copy.deepcopy(node)

    def update_fusion_node(self, clip_id, node_id, parameters=None, name=None, position=None):
        graph = self._edit_fusion(clip_id)
        node = next((n for n in graph['nodes'] if n['id'] == node_id), None)
        if node is None:
            raise ValueError('Fusion node does not exist')
        if parameters is not None:
            if not isinstance(parameters, dict):
                raise ValueError('Fusion parameters must be an object')
            node['parameters'].update(parameters)
        if name is not None:
            node['name'] = name
        if position is not None:
            node['position'] = position
        validate_graph(graph)
        return copy.deepcopy(node)

    def connect_fusion_nodes(self, clip_id, target_node_id, input, source_node_id=None):
        graph = self._edit_fusion(clip_id)
        node = next((n for n in graph['nodes'] if n['id'] == target_node_id), None)
        if node is None or input not in CATALOG[node['type']]['inputs']:
            raise ValueError('Fusion input port does not exist')
        if source_node_id is None:
            node['inputs'].pop(input, None)
        else:
            node['inputs'][input] = source_node_id
        validate_graph(graph)
        return describe_graph(graph)

    def delete_fusion_node(self, clip_id, node_id):
        graph = self._edit_fusion(clip_id)
        if node_id == graph['output_node_id']:
            raise ValueError('Cannot delete the designated MediaOut')
        if not any(n['id'] == node_id for n in graph['nodes']):
            raise ValueError('Fusion node does not exist')
        graph['nodes'] = [n for n in graph['nodes'] if n['id'] != node_id]
        for node in graph['nodes']:
            node['inputs'] = {k: v for k, v in node['inputs'].items() if v != node_id}
        validate_graph(graph)
        return describe_graph(graph)

    def clear_fusion_graph(self, clip_id):
        self._fusion_clip(clip_id).pop('fusion_graph', None)
        return describe_graph(default_graph())

    def render_fusion_frame(self, clip_id, output, node_id=None, frame=0):
        """Export a node checkpoint before clip grade and timeline compositing."""
        from .engine import ffmpeg_executable, clip_duration
        clip = copy.deepcopy(self._fusion_clip(clip_id))
        project = copy.deepcopy(self._require())
        self._frame(frame)
        if frame >= clip_duration(clip):
            raise ValueError('Fusion frame is outside the clip duration')
        graph = copy.deepcopy(clip.get('fusion_graph', default_graph()))
        nodes = validate_graph(graph)
        node_id = node_id or graph['output_node_id']
        if node_id not in nodes:
            raise ValueError('Fusion node does not exist')
        if node_id != graph['output_node_id']:
            nodes[graph['output_node_id']]['inputs']['Input'] = node_id
        order, errors = render_order(graph)
        if errors:
            raise ValueError('Incomplete Fusion checkpoint: ' + '; '.join(errors))
        destination = Path(output).expanduser().resolve()
        if destination.suffix.lower() != '.png':
            raise ValueError('Fusion checkpoint output must be .png')
        if destination == Path(project['path']).resolve() or any(destination == Path(m['path']).resolve() for m in project['media']):
            raise ValueError('Output must not overwrite project or source media')
        cmd = [ffmpeg_executable(), '-v', 'error', '-y', '-filter_complex_threads', '1']
        media = None
        if any(node['type'] == 'MediaIn' for node in order):
            media = self._media(clip['media_id'])
            media = self._media_level_info(media)
            if media.get('still'):
                cmd += ['-loop', '1', '-framerate', f'{project["fps"]["num"]}/{project["fps"]["den"]}']
            cmd += ['-i', media['path']]
        filters, label = compile_graph(graph, '[0:v]' + self._video_selection(clip, project), project,
                                       clip_duration(clip), 'checkpoint', force_output=True, media=media)
        filters.extend(float_to_rgba16(label, 'checkpoint_integer'))
        filters.append(f'[checkpoint_integer]trim=start_frame={frame}:end_frame={frame+1},setpts=PTS-STARTPTS,format=rgba64be[checkpoint_output]')
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix='.gt-node-', suffix='.png', dir=destination.parent)
        os.close(handle)
        try:
            result = subprocess.run(cmd + ['-filter_complex', ';'.join(filters), '-map', '[checkpoint_output]',
                                          '-frames:v', '1', '-pix_fmt', 'rgba64be', '-update', '1', temporary], capture_output=True, text=True)
            if result.returncode:
                raise ValueError('Fusion checkpoint render failed: ' + result.stderr[-4000:])
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {'output': str(destination), 'clip_id': clip_id, 'node_id': node_id, 'frame': frame,
                'width': project['width'], 'height': project['height'], 'format': 'png', 'channels': 'RGBA16',
                'alpha_association': 'associated node samples; PNG viewers may assume straight alpha',
                'scope': 'node output before clip grade, transforms, opacity and timeline compositing',
                'bytes': destination.stat().st_size, 'native_equivalence_verified': False}


def has_processing(graph):
    if graph is None:
        return False
    order, errors = render_order(graph)
    return bool(errors) or [node['type'] for node in order] != ['MediaIn', 'MediaOut']


def place_image(source, output, width, height, x=0, y=0):
    """Place on a transparent canvas without multiplying or discarding RGB at A=0."""
    return [f'[{source}]format=gbrap16le,pad=w=\'max(iw,{width})+{2*math.ceil(abs(x))}\':h=\'max(ih,{height})+{2*math.ceil(abs(y))}\':x=(ow-iw)/2:y=(oh-ih)/2:color=black@0,'
            f'crop=w={width}:h={height}:x=(iw-{width})/2-({x}):y=(ih-{height})/2-({y}):exact=1[{output}]']


def premultiplied_over(background, foreground, output, *, floating=False):
    """RGBA16 associated over; RGB may exceed alpha (native generator glow)."""
    front, mask, back, weighted = (output+'_'+suffix for suffix in ('front','mask','back','weighted'))
    fmt, peak = ('gbrapf32le', 1) if floating else ('gbrap16le', 65535)
    return [f'[{foreground}]format={fmt},split=2[{front}][{mask}_source]',
            f'[{mask}_source]geq=r=\'alpha(X,Y)\':g=\'alpha(X,Y)\':b=\'alpha(X,Y)\':a=\'alpha(X,Y)\'[{mask}]',
            f'[{background}]format={fmt}[{back}]',
            f'[{back}][{mask}]blend=all_expr=\'A*(1-B/{peak})\'[{weighted}]',
            f'[{weighted}][{front}]blend=all_mode=addition[{output}]']


def float_to_rgba16(source, output):
    """Quantize RGB with zimg; retain alpha separately from zscale's RGB conversion."""
    return [f'[{source}]format=gbrapf32le,split=2[{output}_rgb_source][{output}_alpha_source]',
            f'[{output}_rgb_source]zscale=dither=none,format=gbrap16le,extractplanes=r+g+b[{output}_r][{output}_g][{output}_b]',
            f'[{output}_alpha_source]format=gbrapf32le,alphaextract,format=gray16le[{output}_alpha]',
            f'[{output}_g][{output}_b][{output}_r][{output}_alpha]mergeplanes=0x00102030:format=gbrap16le[{output}]']


def transform_float_image(source, output, width, height, x=0, y=0, size=1, angle=0):
    """Sample a project-size float canvas without integer pad/rotate boundaries."""
    theta = angle*math.pi/180
    cx, cy = (width-1)/2+x, (height-1)/2+y
    sx = f'(({math.cos(theta)}*(X-({cx}))-{math.sin(theta)}*(Y-({cy})))/({size})+{(width-1)/2})'
    sy = f'(({math.sin(theta)}*(X-({cx}))+{math.cos(theta)}*(Y-({cy})))/({size})+{(height-1)/2})'
    inside = f'gte({sx},0)*lt({sx},{width})*gte({sy},0)*lt({sy},{height})'
    expressions = ':'.join(f"{c}='if({inside},{sample}({sx},{sy}),0)'" for c,sample in (('r','r'),('g','g'),('b','b'),('a','alpha')))
    return [f'[{source}]format=gbrapf32le,geq={expressions}:interpolation=bilinear[{output}]']


def compile_graph(graph, selection, project, duration_frames, prefix, *, force_output=False, media=None):
    """Return filter statements and an output label; generate only reachable nodes."""
    order, errors = render_order(graph)
    if errors:
        raise ValueError('Incomplete Fusion graph: ' + '; '.join(errors))
    if not force_output and [n['type'] for n in order] == ['MediaIn', 'MediaOut']:
        return None  # Bit-identical legacy path, including disconnected nodes.
    width, height = project['width'], project['height']
    rate = f'{project["fps"]["num"]}/{project["fps"]["den"]}'
    duration = duration_frames * project['fps']['den'] / project['fps']['num']
    uses = Counter(source for n in order for source in n['inputs'].values())
    uses[graph['output_node_id']] = 1
    labels, filters = {}, []
    def take(identity):
        return labels[identity].pop()
    def canvas(label):
        filters.append(f'color=c=black@0:s={width}x{height}:r={rate}:d={duration:.12f},format=gbrapf32le[{label}]')
    for index, node in enumerate(order):
        out = f'{prefix}_f{index}'
        params, kind = node['parameters'], node['type']
        if kind == 'MediaIn':
            from .media_levels import level_filters
            before, after = level_filters(media or {})
            filters.append(selection + before + f',scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1,format=gbrap16le,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0,format=gbrapf32le' + after + f',premultiply=inplace=1[{out}]')
        elif kind == 'Background':
            raw = out + '_canvas'; canvas(raw)
            filters.append(f'[{raw}]geq=r={params["Red"]}:g={params["Green"]}:b={params["Blue"]}:a={params["Alpha"]}[{out}]')
        elif kind == 'Transform':
            source = take(node['inputs']['Input'])
            filters.extend(transform_float_image(source, out, width, height, (params['CenterX']-.5)*width, (.5-params['CenterY'])*height, params['Size'], params['Angle']))
        elif kind == 'Merge':
            back, front = (take(node['inputs'][port]) for port in ('Background', 'Foreground'))
            alpha = out + '_alpha'
            blend = params['Blend']
            filters.append(f'[{front}]geq=r=\'r(X,Y)*{blend}\':g=\'g(X,Y)*{blend}\':b=\'b(X,Y)*{blend}\':a=\'alpha(X,Y)*{blend}\'[{alpha}]')
            positioned = out + '_positioned'
            filters.extend(transform_float_image(alpha, positioned, width, height, (params['CenterX']-.5)*width, (.5-params['CenterY'])*height))
            filters.extend(premultiplied_over(back, positioned, out, floating=True))
        else:  # MediaOut
            filters.append(f'[{take(node["inputs"]["Input"])}]null[{out}]')
        count = uses[node['id']]
        if count > 1:
            labels[node['id']] = [f'{out}_use{i}' for i in range(count)]
            filters.append(f'[{out}]split={count}' + ''.join(f'[{label}]' for label in labels[node['id']]))
        else:
            labels[node['id']] = [out]
    return filters, take(graph['output_node_id'])
