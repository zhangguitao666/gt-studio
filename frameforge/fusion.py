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
from .fusion_precision import DEPTH_NAMES, quantize_value, quantize_image


CATALOG = {
    'MediaIn': {'inputs': [], 'parameters': {}},
    'MediaOut': {'inputs': ['Input'], 'parameters': {}},
    'Background': {'inputs': [], 'parameters': {**{k: (v, 0, 1) for k, v in [('Red', 0), ('Green', 0), ('Blue', 0), ('Alpha', 1)]}, 'Depth': (0, 0, 4)}},
    'Transform': {'inputs': ['Input'], 'parameters': {'CenterX': (0.5, -10, 10), 'CenterY': (0.5, -10, 10), 'Size': (1, 0.01, 8), 'Angle': (0, -3600, 3600)}},
    'Merge': {'inputs': ['Background', 'Foreground'], 'parameters': {'Blend': (1, 0, 1), 'CenterX': (0.5, -10, 10), 'CenterY': (0.5, -10, 10)}},
}


def make_node(kind, identity, name=None, parameters=None, position=None):
    if kind not in CATALOG:
        raise ValueError('Unsupported Fusion node type: ' + str(kind))
    if parameters is not None and not isinstance(parameters, dict):
        raise ValueError('Fusion parameters must be an object')
    values = {**{k: v[0] for k, v in CATALOG[kind]['parameters'].items()}, **(parameters or {})}
    # Implicit default depth keeps legacy files and older running clients
    # compatible; the new inspector obtains the default from the catalogue.
    if kind == 'Background' and 'Depth' not in (parameters or {}):
        values.pop('Depth')
    return {'id': identity, 'type': kind, 'name': identity if name is None else name,
            'parameters': values,
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
        required = set(spec['parameters']) - ({'Depth'} if node['type']=='Background' else set())
        if not isinstance(params, dict) or not required <= set(params) <= set(spec['parameters']):
            raise ValueError('Invalid Fusion parameters')
        for key, (default, low, high) in spec['parameters'].items():
            value = params.get(key, default)
            if not finite(value, low, high) or (key=='Depth' and value not in DEPTH_NAMES):
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
    """Quantize color and alpha through zimg RGB planes, avoiding gray-range remaps."""
    return [f'[{source}]format=gbrapf32le,split=2[{output}_rgb_source][{output}_alpha_source]',
            f'[{output}_rgb_source]zscale=dither=none,format=gbrap16le,extractplanes=r+g+b[{output}_r][{output}_g][{output}_b]',
            f'[{output}_alpha_source]format=gbrapf32le,geq=r=\'alpha(X,Y)\':g=\'alpha(X,Y)\':b=\'alpha(X,Y)\':a=1,zscale=dither=none,format=gbrap16le,extractplanes=r[{output}_alpha]',
            f'[{output}_g][{output}_b][{output}_r][{output}_alpha]mergeplanes=0x00102030:format=gbrap16le[{output}]']


def rgba8_to_rgba16(source, output, *, has_alpha=True):
    """Expand all eight-bit channels as UNORM, including independent alpha."""
    # Extract before converting packed RGBA: swscale's RGBA8 -> GBRAP8
    # conversion itself can change non-opaque alpha by one eight-bit unit.
    prepare = '' if has_alpha else 'format=rgba,'
    filters = [f'[{source}]{prepare}extractplanes=r+g+b+a[{output}_r8][{output}_g8][{output}_b8][{output}_a8]']
    for c in ('r','g','b','a'):
        # extractplanes can retain its RGB parent's matrix tag. zimg rejects
        # RGB matrix coefficients on a grayscale carrier in newer versions.
        # Both ends are scalar gray: select the same non-RGB matrix so only
        # depth/range changes, then restore the RGB tag after reassembly.
        filters.append(f'[{output}_{c}8]zscale=matrixin=709:matrix=709:rangein=full:range=full:dither=none,format=gray16le[{output}_{c}]')
    filters.append(f'[{output}_g][{output}_b][{output}_r][{output}_a]mergeplanes=0x00102030:format=gbrap16le,setparams=colorspace=gbr[{output}]')
    return filters


def rgba16_to_float(source, output):
    """Normalize RGB and alpha independently, avoiding alpha range remapping."""
    return [f'[{source}]format=gbrap16le,split=2[{output}_rgb_source][{output}_alpha_source]',
            f'[{output}_rgb_source]zscale=dither=none,format=gbrapf32le,extractplanes=r+g+b[{output}_r][{output}_g][{output}_b]',
            f'[{output}_alpha_source]geq=r=\'alpha(X,Y)\':g=\'alpha(X,Y)\':b=\'alpha(X,Y)\':a=65535,zscale=dither=none,format=gbrapf32le,extractplanes=r[{output}_alpha]',
            f'[{output}_g][{output}_b][{output}_r][{output}_alpha]mergeplanes=0x00102030:format=gbrapf32le[{output}]']


def transform_float_image(source, output, width, height, x=0, y=0, size=1, angle=0):
    """Sample a project-size float canvas without integer pad/rotate boundaries."""
    theta = angle*math.pi/180
    cx, cy = (width-1)/2+x, (height-1)/2+y
    sx = f'(({math.cos(theta)}*(X-({cx}))-{math.sin(theta)}*(Y-({cy})))/({size})+{(width-1)/2})'
    sy = f'(({math.sin(theta)}*(X-({cx}))+{math.cos(theta)}*(Y-({cy})))/({size})+{(height-1)/2})'
    if size < 1:
        return _minify_float_image(source, output, width, height, sx, sy, 1/size)
    inside = f'gte({sx},0)*lt({sx},{width})*gte({sy},0)*lt({sy},{height})'
    expressions = ':'.join(f"{c}='if({inside},{sample}({sx},{sy}),0)'" for c,sample in (('r','r'),('g','g'),('b','b'),('a','alpha')))
    return [f'[{source}]format=gbrapf32le,geq={expressions}:interpolation=bilinear[{output}]']


def _minify_float_image(source, output, width, height, sx, sy, radius):
    """Widen a triangle footprint when shrinking, with transparent black outside.

    The captured native Size=.5 boundary has 1/8 and 7/8 coverage. A source
    footprint of 1/Size reproduces those samples. Other shrink factors use
    the same model; their native filter defaults remain unmeasured.

    Eval loops keep the filter expression bounded even at Size=.01. geq
    registers are private to each channel/thread. All channels are sampled
    independently, retaining associated RGB, including RGB at zero alpha.
    """
    wx = f'max(0,1-abs(ld(4)-ld(0))/{radius!r})'
    wy = f'max(0,1-abs(ld(5)-ld(1))/{radius!r})'
    # 0/1: source coordinates; 2/3: first taps; 4/5: current tap;
    # 6: sum; 7: normalization; 8: horizontal normalization; 9: vertical weight.
    setup = f'st(0,{sx});st(1,{sy});st(2,ceil(ld(0)-{radius}));st(3,ceil(ld(1)-{radius}));'
    def weight_sum(center):
        # Sum both arithmetic progressions analytically. A composed chain can
        # shrink far below a single node's .01 limit: iterating its full black
        # footprint would be unbounded, or stall when integer taps exceed 2^53.
        first, middle, last = f'ceil({center}-{radius})', f'floor({center})', f'floor({center}+{radius})'
        return (f'({middle}-{first}+1)*(1+(({first}+{middle})/2-{center})/{radius})+'
                f'({last}-{middle})*(1-(({middle}+1+{last})/2-{center})/{radius})')
    denominator = f'st(8,{weight_sum("ld(0)")});st(7,({weight_sum("ld(1)")})*ld(8));'
    gate = (f'gt(ld(0),-{radius})*lt(ld(0),{width-1}+{radius})*'
            f'gt(ld(1),-{radius})*lt(ld(1),{height-1}+{radius})')
    expressions = []
    for channel, sample in (('r', 'r'), ('g', 'g'), ('b', 'b'), ('a', 'alpha')):
        # Normalize over the entire footprint, including taps outside the
        # source. Only the numerator clips taps; edge pixels must lose coverage.
        total = (
            f'st(6,0);st(5,max(0,ld(3)));'
            f'while(lte(ld(5),min({height-1},ld(1)+{radius})),st(9,{wy});'
            f'st(4,max(0,ld(2)));'
            f'while(lte(ld(4),min({width-1},ld(0)+{radius})),st(6,ld(6)+'
            f'{sample}(ld(4),ld(5))*{wx}*ld(9));st(4,ld(4)+1));'
            'st(5,ld(5)+1));ld(6)/ld(7)'
        )
        expressions.append(f"{channel}='{setup}if({gate},{denominator}{total},0)'")
    return [f'[{source}]format=gbrapf32le,geq=' + ':'.join(expressions) +
            f':interpolation=nearest[{output}]']


def _concatenated_order(order, output_id, width, height):
    """Compile adjacent default Transforms into one sampling operation.

    Keep the editable graph and its intermediate checkpoints intact. A branch
    can still request an intermediate transform while a later branch samples
    the original source with the composed coordinates. This is not general
    off-canvas image storage across other node types.
    """
    nodes = {node['id']: copy.deepcopy(node) for node in order}
    for node in nodes.values():
        if node['type'] != 'Transform':
            continue
        parent = nodes[node['inputs']['Input']]
        if parent['type'] != 'Transform':
            continue
        before, after = parent['parameters'], node['parameters']
        angle = math.radians(after['Angle'])
        px, py = (before['CenterX']-.5)*width, (.5-before['CenterY'])*height
        x = after['Size']*(math.cos(angle)*px+math.sin(angle)*py)
        y = after['Size']*(-math.sin(angle)*px+math.cos(angle)*py)
        node['parameters'] = {
            'CenterX': after['CenterX']+x/width,
            'CenterY': after['CenterY']-y/height,
            'Size': before['Size']*after['Size'],
            'Angle': before['Angle']+after['Angle'],
        }
        node['inputs']['Input'] = parent['inputs']['Input']
    needed = set()
    def visit(identity):
        if identity in needed:
            return
        needed.add(identity)
        for source in nodes[identity]['inputs'].values():
            visit(source)
    visit(output_id)
    return [node for identity, node in nodes.items() if identity in needed]


def compile_graph(graph, selection, project, duration_frames, prefix, *, force_output=False, media=None):
    """Return filter statements and an output label; generate only reachable nodes."""
    order, errors = render_order(graph)
    if errors:
        raise ValueError('Incomplete Fusion graph: ' + '; '.join(errors))
    if not force_output and [n['type'] for n in order] == ['MediaIn', 'MediaOut']:
        return None  # Bit-identical legacy path, including disconnected nodes.
    width, height = project['width'], project['height']
    order = _concatenated_order(order, graph['output_node_id'], width, height)
    rate = f'{project["fps"]["num"]}/{project["fps"]["den"]}'
    duration = duration_frames * project['fps']['den'] / project['fps']['num']
    uses = Counter(source for n in order for source in n['inputs'].values())
    uses[graph['output_node_id']] = 1
    labels, filters, precision = {}, [], {}
    def take(identity):
        return labels[identity].pop()
    def canvas(label):
        filters.append(f'color=c=black@0:s={width}x{height}:r={rate}:d={duration:.12f},format=gbrapf32le[{label}]')
    for index, node in enumerate(order):
        out = f'{prefix}_f{index}'
        params, kind = node['parameters'], node['type']
        if kind == 'MediaIn':
            from .media_levels import level_filters, effective_data_level
            before, after = level_filters(media or {})
            rgb8 = (media or {}).get('pixel_format') in {'rgb24', 'bgr24', 'argb', 'abgr', 'rgba', 'bgra', 'gbrp', 'gbrap', 'rgb0', '0rgb', 'bgr0', '0bgr'}
            # Preserve the decoded 8-bit RGB values before the integer resize.
            # swscale's packed RGB8 -> RGB16 path is not UNORM byte expansion.
            # Normalize channels independently, avoiding depth/range remaps
            # in the alpha paths of the conversion filters.
            normalized = selection + before
            # Video code values need byte-exact normalization before the
            # 16/235 mapping. Full/other Auto retain the separately measured
            # decoder expansion; treating every mode as Video regresses Full.
            if rgb8 and effective_data_level(media or {})=='Video':
                raw = out+'_decoded'; filters.append(normalized+f'[{raw}]')
                expanded = out+'_expanded'
                alpha_present = (media or {}).get('pixel_format') in {'argb','abgr','rgba','bgra','gbrap'}
                filters.extend(rgba8_to_rgba16(raw, expanded, has_alpha=alpha_present))
                normalized = f'[{expanded}]null'
            integer = out + '_integer_source'
            filters.append(normalized + f',scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1,format=gbrap16le,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0[{integer}]')
            floating = out + '_float_source'
            filters.extend(rgba16_to_float(integer, floating))
            filters.append(f'[{floating}]null' + after + f',premultiply=inplace=1[{out}]')
            precision[node['id']] = 4
        elif kind == 'Background':
            raw = out + '_canvas'; canvas(raw)
            depth = params.get('Depth', 0)
            values = {key: quantize_value(params[key], depth) for key in ('Red', 'Green', 'Blue', 'Alpha')}
            filters.append(f'[{raw}]geq=r={values["Red"]}:g={values["Green"]}:b={values["Blue"]}:a={values["Alpha"]}[{out}]')
            precision[node['id']] = 1 if depth==0 else depth
        elif kind == 'Transform':
            source = take(node['inputs']['Input'])
            depth = precision[node['inputs']['Input']]
            sampled = out if depth==4 else out+'_sampled'
            filters.extend(transform_float_image(source, sampled, width, height, (params['CenterX']-.5)*width, (.5-params['CenterY'])*height, params['Size'], params['Angle']))
            if depth!=4:
                filters.extend(quantize_image(sampled, out, depth))
            precision[node['id']] = depth
        elif kind == 'Merge':
            back, front = (take(node['inputs'][port]) for port in ('Background', 'Foreground'))
            depth = precision[node['inputs']['Background']]
            if depth!=precision[node['inputs']['Foreground']]:
                converted = out+'_converted'; filters.extend(quantize_image(front, converted, depth)); front=converted
            alpha = out + '_alpha'
            blend = params['Blend']
            filters.append(f'[{front}]geq=r=\'r(X,Y)*{blend}\':g=\'g(X,Y)*{blend}\':b=\'b(X,Y)*{blend}\':a=\'alpha(X,Y)*{blend}\'[{alpha}]')
            positioned = out + '_positioned'
            filters.extend(transform_float_image(alpha, positioned, width, height, (params['CenterX']-.5)*width, (.5-params['CenterY'])*height))
            merged = out if depth==4 else out+'_merged'
            filters.extend(premultiplied_over(back, positioned, merged, floating=True))
            if depth!=4:
                filters.extend(quantize_image(merged, out, depth))
            precision[node['id']] = depth
        else:  # MediaOut
            filters.append(f'[{take(node["inputs"]["Input"])}]null[{out}]')
            precision[node['id']] = precision[node['inputs']['Input']]
        count = uses[node['id']]
        if count > 1:
            labels[node['id']] = [f'{out}_use{i}' for i in range(count)]
            filters.append(f'[{out}]split={count}' + ''.join(f'[{label}]' for label in labels[node['id']]))
        else:
            labels[node['id']] = [out]
    return filters, take(graph['output_node_id'])
