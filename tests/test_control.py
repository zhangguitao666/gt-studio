import json
from pathlib import Path
import subprocess
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from frameforge.client import rpc
from frameforge.control import validate
from frameforge.service import Controller, EditorServer


@pytest.fixture
def running_server(tmp_path):
    server = EditorServer(("127.0.0.1", 0), Controller(tmp_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, tmp_path, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def test_mcp_and_http_share_project(running_server):
    server, workspace, url = running_server
    root = Path(__file__).resolve().parent.parent
    p = subprocess.Popen([sys.executable, str(root / "frameforge_entry.py"), "mcp", "--workspace", str(workspace), "--port", str(server.server_port)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    def call(method, params):
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}) + "\n")
        p.stdin.flush()
        line = p.stdout.readline()
        assert line, p.stderr.read()
        return json.loads(line)["result"]
    try:
        identity = call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})["serverInfo"]
        assert identity["name"] == "gt-studio" and identity["title"] == "GT Studio"
        tools = call("tools/list", {})["tools"]
        assert {"split_clip", "render", "submit_render", "get_state"} <= {t["name"] for t in tools}
        result = call("tools/call", {"name": "create_project", "arguments": {"name": "MCP shared project", "width": 320, "height": 180}})
        assert not result["isError"]
        assert rpc(url, "get_state")["name"] == "MCP shared project"
        rpc(url, "add_marker", {"frame": 24, "label": "shared marker"})
        state = call("tools/call", {"name": "get_state"})["structuredContent"]
        assert state["timelines"][0]["markers"][0]["name"] == "shared marker"
        saved = call("tools/call", {"name": "save_project"})["structuredContent"]
        assert json.loads(Path(saved["path"]).read_text())["id"] == state["id"]
        error = call("tools/call", {"name": "delete_clip", "arguments": {"clip_id": "missing"}})
        assert error["isError"]
        assert rpc(url, "get_state")["id"] == state["id"]
        caps = call("resources/read", {"uri": "gt-studio://capabilities"})
        capabilities = json.loads(caps["contents"][0]["text"])
        assert capabilities["full_resolve_parity"] is False
        assert capabilities["application"] == "GT Studio"
        legacy = call("resources/read", {"uri": "frameforge://capabilities"})
        assert json.loads(legacy["contents"][0]["text"]) == capabilities
    finally:
        p.terminate()
        p.communicate(timeout=5)


def test_browser_origins_cannot_mutate_project(running_server):
    _, _, url = running_server
    request = Request(url + "/rpc", b'{"action":"create_project","params":{"name":"foreign"}}', {"Content-Type": "application/json", "Origin": "https://unrelated.example"})
    with pytest.raises(HTTPError) as error:
        urlopen(request)
    assert error.value.code == 403
    assert rpc(url, "get_state") == {"project": None}


@pytest.mark.parametrize("action,params", [("move_clip", {"clip_id": "a", "start_frame": 1.25}), ("set_clip_properties", {"clip_id": "a", "properties": {"gamma": float("nan")}}), ("render", {"output": ""}), ("delete_clip", {"clip_id": "a", "arbitrary": True})])
def test_bad_parameters_are_rejected(action, params):
    with pytest.raises(ValueError):
        validate(action, params)


@pytest.mark.parametrize("params", [{"clip_id": "a", "percentage": 50, "ripple": 1}, {"clip_id": "a", "percentage": 1601}, {"clip_id": "a", "percentage": True}, {"clip_id": "a", "percentage": 0, "freeze_frame": -1}, {"clip_id": "a", "percentage": 0, "freeze_frame": True}])
def test_retime_control_rejects_invalid_percentage_and_flags(params):
    with pytest.raises(ValueError):
        validate("set_clip_speed", params)


def test_transport_commands_are_pending_until_native_observation(running_server):
    _, _, url = running_server
    assert rpc(url, "get_transport")["ui_connected"] is False
    rpc(url, "set_page", {"page": "Color"})
    rpc(url, "set_playhead", {"frame": 36})
    result = rpc(url, "set_playback", {"state": "playing"})
    assert result["pending"] is True
    assert [x["changed"] for x in result["requests"]] == ["page", "frame", "playback"]
    assert result["observed"]["playback"] == "stopped"
    observed = rpc(url, "report_transport", {"page": "Color", "frame": 36, "playback": "playing", "applied_revision": 3})
    assert observed["ui_connected"] and not observed["pending"]


@pytest.mark.parametrize('seek,observed,explicit,expected', [(12, 0, None, 12), (None, 18, None, 18), (12, 0, 6, 6)])
def test_freeze_uses_pending_or_observed_playhead_with_explicit_override(running_server, seek, observed, explicit, expected):
    import wave
    _, workspace, url = running_server
    source = workspace / 'source.wav'
    with wave.open(str(source), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b'\0\0' * 96000)
    rpc(url, 'create_project', {'name': 'Native freeze semantics', 'fps': 24})
    media = rpc(url, 'import_media', {'path': str(source)})
    clip = rpc(url, 'append_clip', {'media_id': media['id'], 'out_frame': 47})
    rpc(url, 'report_transport', {'page': 'Edit', 'frame': observed, 'playback': 'paused', 'applied_revision': 0})
    if seek is not None:
        rpc(url, 'set_playhead', {'frame': seek})
    params = {'clip_id': clip['id'], 'percentage': 0}
    if explicit is not None:
        params['freeze_frame'] = explicit
    frozen = rpc(url, 'set_clip_speed', params)
    assert frozen['start_frame'] == expected
    assert frozen['duration_frames'] == 47 - expected
    assert frozen['speed_percentage'] == 0
    assert frozen['id'] != clip['id']
    rpc(url, 'undo')
    state = rpc(url, 'get_state')
    clips = [c for track in state['timelines'][0]['tracks'] for c in track['clips']]
    assert len(clips) == 1 and clips[0]['duration_frames'] == 47


def test_transport_rejects_old_session_heartbeat_and_bounds_ack(tmp_path):
    old=Controller(tmp_path/'old')
    new=Controller(tmp_path/'new')
    assert old.transport()['session_id'] != new.transport()['session_id']
    new.dispatch('set_playhead',{'frame':24})
    stale={'session_id':old.transport()['session_id'],'frame':999,'page':'Deliver','playback':'playing','applied_revision':50}
    result=new.dispatch('report_transport',stale)
    assert result['pending'] and not result['ui_connected']
    assert result['observed']['frame']==0 and result['observed']['applied_revision']==0
    fresh={**stale,'session_id':new.transport()['session_id'],'frame':24}
    result=new.dispatch('report_transport',fresh)
    assert result['observed']['applied_revision']==1
    assert not result['pending'] and result['ui_connected']
