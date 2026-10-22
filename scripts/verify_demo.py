"""Generate original test media and exercise the live editor through MCP stdio."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from frameforge.engine import ffmpeg_executable
from frameforge.client import ensure_service, rpc

def main():
    workspace = ROOT / "workspace"
    media = workspace / "demo-media"
    media.mkdir(parents=True, exist_ok=True)
    for name, source, frequency in [("motion", "testsrc2=size=640x360:rate=24", 440), ("bars", "smptebars=size=640x360:rate=24", 660)]:
        output = media / (name + ".mp4")
        subprocess.run([ffmpeg_executable(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", source, "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(output)], check=True)
    url = ensure_service(workspace)
    process = subprocess.Popen([sys.executable, str(ROOT / "frameforge_entry.py"), "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    sequence = 0
    calls = []
    def request(method, params):
        nonlocal sequence
        sequence += 1
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": sequence, "method": method, "params": params}) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(process.stderr.read())
        reply = json.loads(line)
        if "error" in reply:
            raise RuntimeError(reply["error"])
        return reply["result"]
    def tool(tool_name, **arguments):
        reply = request("tools/call", {"name": tool_name, "arguments": arguments})
        if reply.get("isError"):
            raise RuntimeError(reply["content"])
        calls.append(tool_name)
        return reply["structuredContent"]
    try:
        initialized = request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "GT Studio acceptance", "version": "1"}})
        project = tool("create_project", name="REA · Edit verification", width=1280, height=720, fps=24)
        timeline = project["timelines"][0]
        video = next(t for t in timeline["tracks"] if t["kind"] == "video")
        first = tool("import_media", path=str(media / "motion.mp4"))
        second = tool("import_media", path=str(media / "bars.mp4"))
        clip = tool("append_clip", media_id=first["id"], track_id=video["id"])
        tool("append_clip", media_id=second["id"], track_id=video["id"])
        split = tool("split_clip", clip_id=clip["id"], frame=36)
        tool("set_clip_properties", clip_id=split["second"]["id"], properties={"saturation": 0.35, "contrast": 1.2, "volume": 0.4})
        tool("add_marker", frame=36, label="MCP split + grade")
        tool("save_project", path=str(workspace / "demo-project.json"))
        state = tool("get_state")
        assert rpc(url, "get_state")["id"] == state["id"]
        output = workspace / "demo-export.mp4"
        job = tool("submit_render", output=str(output))
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            status = tool("get_render_job", job_id=job["id"])
            if status["status"] in {"completed", "failed"}:
                break
            time.sleep(0.15)
        assert status["status"] == "completed", status
        decoded = subprocess.run([ffmpeg_executable(), "-v", "error", "-i", str(output), "-map", "0:v:0", "-f", "null", "-"], capture_output=True)
        assert decoded.returncode == 0, decoded.stderr
        result = {"status": "passed", "mcp_server": initialized["serverInfo"], "project": str(workspace / "demo-project.json"), "output": str(output), "decoded_video": True, "render_result": status["result"], "shared_http_project_id": state["id"], "mcp_actions": sorted(set(calls)), "full_resolve_parity": False}
        (ROOT / "research" / "demo-verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        process.terminate()
        process.communicate(timeout=5)

if __name__ == "__main__":
    main()
