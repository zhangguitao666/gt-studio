"""Actual MCP -> independent engine -> retimed video/captions export acceptance."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from frameforge.engine import ffmpeg_executable

def main():
    workspace = ROOT / 'workspace' / 'retime-subtitles'
    workspace.mkdir(parents=True, exist_ok=True)
    source = workspace / 'moving-source.mp4'
    ffmpeg = ffmpeg_executable()
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=24:d=3', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(source)], check=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = subprocess.Popen([sys.executable, str(ROOT / 'frameforge_entry.py'), 'serve', '--workspace', str(workspace), '--port', str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    process = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with urlopen(f'http://127.0.0.1:{port}/health', timeout=.2) as response:
                    assert json.load(response)['application'] == 'GT Studio'
                break
            except OSError:
                if server.poll() is not None:
                    raise RuntimeError(server.stderr.read())
                time.sleep(.05)
        else:
            raise RuntimeError('Acceptance server failed to start')
        process = subprocess.Popen([sys.executable, str(ROOT / 'frameforge_entry.py'), 'mcp', '--workspace', str(workspace), '--port', str(port)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        sequence, actions = 0, []
        def request(method, params):
            nonlocal sequence
            sequence += 1
            process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': sequence, 'method': method, 'params': params}) + '\n')
            process.stdin.flush()
            line = process.stdout.readline()
            if not line:
                raise RuntimeError(process.stderr.read())
            reply = json.loads(line)
            assert 'error' not in reply, reply
            return reply['result']
        def tool(action, **arguments):
            result = request('tools/call', {'name': action, 'arguments': arguments})
            assert not result['isError'], result
            actions.append(action)
            return result['structuredContent']
        request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'retime subtitle acceptance', 'version': '1'}})
        tools = request('tools/list', {})['tools']
        tool('create_project', name='Retime + captions verification', width=320, height=180, fps=24)
        media = tool('import_media', path=str(source))
        first = tool('append_clip', media_id=media['id'])
        reverse = tool('append_clip', media_id=media['id'])
        tool('set_clip_speed', clip_id=first['id'], percentage=50, ripple=True, pitch_correction=True)
        halves = tool('split_clip', clip_id=first['id'], frame=37)
        tool('set_clip_speed', clip_id=reverse['id'], percentage=-100, pitch_correction=True)
        frozen = tool('append_clip', media_id=media['id'], in_frame=24, out_frame=48)
        tool('set_clip_speed', clip_id=frozen['id'], percentage=0)
        cue = tool('add_subtitle', start_frame=24, end_frame=72, text='Literal {\\N} 100%\nFrame-accurate captions')
        tool('update_subtitle', cue_id=cue['id'], end_frame=84)
        tool('add_subtitle', start_frame=228, end_frame=252, text='Subtitle-only tail')
        tool('set_subtitle_style', properties={'font_size': 18, 'margin_vertical': 10, 'outline': 1, 'color': '#FFFFFF'})
        sidecar = workspace / 'captions.srt'
        tool('export_subtitles', path=str(sidecar))
        assert 'Literal {\\N} 100%' in sidecar.read_text()
        path = workspace / 'retime-project.json'
        tool('save_project', path=str(path))
        state = tool('get_state')
        clips = state['timelines'][0]['tracks'][0]['clips']
        assert [c['duration_frames'] for c in sorted(clips, key=lambda c: c['start_frame'])] == [37, 107, 72, 24]
        assert halves['second']['source_start'] == {'num': 37, 'den': 2}
        output = workspace / 'retime-caption-export.mp4'
        job = tool('submit_render', output=str(output))
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            status = tool('get_render_job', job_id=job['id'])
            if status['status'] in {'completed', 'failed'}:
                break
            time.sleep(.1)
        assert status['status'] == 'completed', status
        assert status['result']['duration_frames'] == 252
        decoded = subprocess.run([ffmpeg, '-v', 'error', '-i', str(output), '-an', '-vf', 'scale=1:1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], capture_output=True)
        assert decoded.returncode == 0, decoded.stderr
        assert len(decoded.stdout) == 252 * 3
        result = {'status': 'passed', 'project': str(path), 'output': str(output), 'srt': str(sidecar), 'advertised_tool_count': len(tools), 'decoded_video_frames': 252, 'duration_seconds': 10.5, 'fractional_split_source_start': halves['second']['source_start'], 'clip_durations': [37, 107, 72, 24], 'mcp_actions': sorted(set(actions)), 'full_resolve_parity': False, 'comparison_with_original_resolve': 'Not yet established; this verifies the independent pipeline.'}
        (ROOT / 'research/retime-subtitle-verification.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
    finally:
        if process:
            process.terminate()
            process.communicate(timeout=5)
        server.terminate()
        server.communicate(timeout=5)

if __name__ == '__main__':
    main()
