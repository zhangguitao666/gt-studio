"""Render and inspect a compositing demo through the configured stdio MCP."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from frameforge.engine import ffmpeg_executable
from frameforge.service import Controller, EditorServer
from scripts.compare_native_retime_media import MCPProjectClient


def identity(path):
    raw = Path(path).read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


class ConfiguredClient(MCPProjectClient):
    def __init__(self, workspace):
        config = tomllib.loads((Path.home()/'.codex/config.toml').read_text())['mcp_servers']['frameforge']
        self.server = EditorServer(('127.0.0.1', 0), Controller(workspace))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        command = [config['command'], *config.get('args', []), '--workspace', str(workspace), '--port', str(self.server.server_port)]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={**os.environ, **config.get('env', {})})
        self.sequence, self.calls = 0, []
        self.server_info = self.request('initialize', {'protocolVersion': '2025-11-25'})['serverInfo']


def decode(path, audio=False):
    args = ['-vn', '-acodec', 'pcm_s16le', '-f', 's16le'] if audio else ['-an', '-pix_fmt', 'rgb24', '-f', 'rawvideo']
    return subprocess.run([ffmpeg_executable(), '-v', 'error', '-i', str(path), *args, '-'], capture_output=True, check=True).stdout


def main():
    workspace = ROOT/'workspace/fusion-node-verification'; workspace.mkdir(parents=True, exist_ok=True)
    source = workspace/'red-with-audio.mov'
    subprocess.run([ffmpeg_executable(), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=red:s=320x180:r=24:d=2', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2', '-c:v', 'qtrle', '-c:a', 'pcm_s16le', str(source)], check=True)
    client = ConfiguredClient(workspace)
    try:
        tools = client.request('tools/list', {})['tools']
        assert len(tools) == 51
        assert next(t for t in tools if t['name'] == 'get_fusion_graph')['annotations']['readOnlyHint']
        client.tool('create_project', name='GT Studio · Fusion 演示', width=320, height=180, fps=24)
        media = client.tool('import_media', path=str(source))
        clip = client.tool('append_clip', media_id=media['id'], out_frame=48)['id']
        baseline = workspace/'baseline.mov'; client.tool('render', output=str(baseline))
        def add(kind, name, params, x, y):
            return client.tool('add_fusion_node', clip_id=clip, type=kind, name=name, parameters=params, position={'x': x, 'y': y})['id']
        def connect(target, port, source=None):
            return client.tool('connect_fusion_nodes', clip_id=clip, target_node_id=target, input=port, **({'source_node_id': source} if source else {}))
        bg = add('Background', 'Blue overlay', {'Blue': 1, 'Alpha': 0.5}, 0, 180)
        transform = add('Transform', 'Upper right half', {'Size': 0.5, 'CenterX': 0.75, 'CenterY': 0.75}, 240, 180)
        merge = add('Merge', 'Half blend', {'Blend': 0.5}, 480, 0)
        client.tool('update_fusion_node', clip_id=clip, node_id='MediaOut1', position={'x': 720, 'y': 0})
        connect(transform, 'Input', bg); connect(merge, 'Background', 'MediaIn1'); connect(merge, 'Foreground', transform); connect('MediaOut1', 'Input', merge)
        graph = client.tool('get_fusion_graph', clip_id=clip)
        assert graph['render_ready']
        project = workspace/'GT Studio Fusion Demo.json'; client.tool('save_project', path=str(project))
        client.tool('open_project', path=str(project))
        assert client.tool('get_fusion_graph', clip_id=clip) == graph
        output = workspace/'GT Studio Fusion Demo.mov'
        result = client.tool('render', output=str(output)); assert result['duration_frames'] == 48
        raw = decode(output); assert len(raw) == 48*320*180*3
        def sample(frame, x, y):
            index = (frame*320*180+y*320+x)*3
            return list(raw[index:index+3])
        samples = [{'frame': f, 'inside': sample(f, 240, 45), 'outside': sample(f, 80, 45)} for f in (0, 23, 47)]
        for record in samples:
            assert max(abs(a-b) for a,b in zip(record['inside'], [191,0,64])) <= 6
            assert max(abs(a-b) for a,b in zip(record['outside'], [253,0,0])) <= 6
        audio_equal = decode(baseline, True) == decode(output, True); assert audio_equal
        # Incomplete output is editable, but rendering preserves existing exports.
        connect('MediaOut1', 'Input')
        before = identity(output)
        rejected = client.request('tools/call', {'name': 'render', 'arguments': {'output': str(output)}})
        assert rejected['isError'] and identity(output) == before
        client.tool('undo'); assert client.tool('get_fusion_graph', clip_id=clip) == graph
        # Both consumers reuse one image node through explicit compiler fanout.
        client.tool('update_fusion_node', clip_id=clip, node_id=merge, parameters={'Blend': 1})
        connect(merge, 'Background', bg); connect(merge, 'Foreground', bg)
        fanout = workspace/'fanout.mov'; client.tool('render', output=str(fanout))
        fanraw = decode(fanout); index = (90*320+160)*3
        assert max(abs(a-b) for a,b in zip(fanraw[index:index+3], [0,0,191])) <= 6
        client.tool('open_project', path=str(project))
        # Deletion and reset have transactional undo/redo semantics.
        unused = add('Merge', 'Unconnected test', {}, 480, 300)
        client.tool('delete_fusion_node', clip_id=clip, node_id=unused)
        client.tool('undo'); assert any(n['id'] == unused for n in client.tool('get_fusion_graph', clip_id=clip)['graph']['nodes'])
        client.tool('redo'); assert client.tool('get_fusion_graph', clip_id=clip) == graph
        client.tool('clear_fusion_graph', clip_id=clip)
        identity_output = workspace/'identity.mov'; client.tool('render', output=str(identity_output))
        assert decode(identity_output) == decode(baseline) and decode(identity_output, True) == decode(baseline, True)
        client.tool('undo'); assert client.tool('get_fusion_graph', clip_id=clip) == graph
        # Preserve the final saved demo, not the temporary branch/reset cases.
        client.tool('save_project', path=str(project))
        png = workspace/'fusion-output.png'
        subprocess.run([ffmpeg_executable(), '-v', 'error', '-y', '-i', str(output), '-frames:v', '1', str(png)], check=True)
        report = {'status': 'passed_configured_mcp_node_editing_and_actual_media_render', 'server': client.server_info,
                  'public_tool_count': len(tools), 'graph': graph, 'pixel_samples': samples, 'frame_count': 48,
                  'audio_identical_to_direct_path': audio_equal, 'shared_node_fanout_verified': True,
                  'identity_reset_decoded_rgb_pcm_exact': True, 'incomplete_output_rejected': rejected,
                  'existing_export_preserved_on_failure': True, 'project_roundtrip_verified': True,
                  'artifacts': [identity(p) for p in (source, baseline, output, fanout, identity_output, project, png)], 'calls': client.calls,
                  'compositing_precision': '8-bit RGB boundary in Transform/Merge; direct path unchanged',
                  'native_fusion_node_equivalence_verified': False, 'native_window_verification': 'pending', 'full_resolve_parity': False}
        target = ROOT/'research/fusion-node-verification.json'; target.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')
        print(json.dumps({'report': str(target), 'tools': len(tools), 'frames': 48, 'audio_equal': audio_equal, 'output': str(output)}, ensure_ascii=False))
    finally:
        client.close()


if __name__ == '__main__': main()
