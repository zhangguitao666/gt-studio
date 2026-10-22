"""One loopback process owns project state, shared by desktop and MCP clients."""
import copy
import json
import os
from pathlib import Path
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .control import capabilities, validate, SCHEMAS
from .engine import Engine

DEFAULT_PORT = 18771

class Controller:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.engine = Engine(self.workspace)
        self.lock = threading.RLock()
        self.jobs = {}
        self.transport_session_id = uuid.uuid4().hex
        self.requested_transport = {"revision": 0, "changed": None, "page": "Edit", "frame": 0, "playback": "paused"}
        self.transport_requests = []
        self.observed_transport = {"page": None, "frame": 0, "playback": "stopped", "updated_at": 0, "applied_revision": 0}

    def transport(self):
        return {"session_id": self.transport_session_id, "project_id": (self.engine.project or {}).get('id'), "requested": copy.deepcopy(self.requested_transport), "requests": copy.deepcopy(self.transport_requests), "observed": copy.deepcopy(self.observed_transport), "ui_connected": time.time() - self.observed_transport["updated_at"] < 3,
                "pending": self.requested_transport["revision"] > self.observed_transport["applied_revision"]}

    def dispatch(self, action, params):
        validate(action, params)
        with self.lock:
            if action == "list_actions":
                return {"actions": sorted(SCHEMAS)}
            if action == "get_transport":
                return self.transport()
            if action == "report_transport":
                if params.get('session_id', self.transport_session_id) != self.transport_session_id:
                    return self.transport()
                observation = {key: value for key, value in params.items() if key != 'session_id'}
                if 'applied_revision' in observation:
                    observation['applied_revision'] = min(observation['applied_revision'], self.requested_transport['revision'])
                self.observed_transport.update(observation, updated_at=time.time())
                return self.transport()
            if action in {"set_playhead", "set_playback", "set_page"}:
                field, value = {"set_playhead": ("frame", params.get("frame")), "set_playback": ("playback", params.get("state")), "set_page": ("page", params.get("page"))}[action]
                self.requested_transport.update({field: value, "changed": field, "revision": self.requested_transport["revision"] + 1})
                self.transport_requests.append(copy.deepcopy(self.requested_transport))
                self.transport_requests = self.transport_requests[-128:]
                return self.transport()
            if action == "get_capabilities":
                return capabilities()
            if action == "list_render_jobs":
                return {"jobs": copy.deepcopy(list(self.jobs.values()))}
            if action == "get_render_job":
                if params["job_id"] not in self.jobs:
                    raise ValueError("Unknown render job")
                return copy.deepcopy(self.jobs[params["job_id"]])
            if action == "submit_render":
                if self.engine.project is None:
                    raise ValueError("Create or open a project first")
                job_id = uuid.uuid4().hex
                snapshot = copy.deepcopy(self.engine.project)
                job = {"id": job_id, "status": "queued", "output": params["output"], "created_at": time.time()}
                self.jobs[job_id] = job
                def work():
                    with self.lock:
                        job["status"] = "running"
                    try:
                        worker = Engine(self.workspace / "render-snapshots" / job_id)
                        worker.project = snapshot
                        result = worker.dispatch("render", params)
                        with self.lock:
                            job.update(status="completed", result=result, finished_at=time.time())
                    except Exception as e:
                        with self.lock:
                            job.update(status="failed", error=str(e), finished_at=time.time())
                threading.Thread(target=work, daemon=True).start()
                return copy.deepcopy(job)
            if action == "set_clip_speed" and params["percentage"] == 0 and "freeze_frame" not in params:
                from .engine import clip_duration
                clip, _ = self.engine._clip(params["clip_id"])
                transport = self.transport()
                pending_seeks = [r for r in self.transport_requests
                                 if r["changed"] == "frame" and r["revision"] > self.observed_transport["applied_revision"]]
                frame = (pending_seeks[-1]["frame"] if pending_seeks else
                         self.observed_transport["frame"] if transport["ui_connected"] else
                         self.requested_transport["frame"])
                if clip["start_frame"] <= frame < clip["start_frame"] + clip_duration(clip):
                    params = {**params, "freeze_frame": frame}
            return self.engine.dispatch(action, params)

class EditorServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, controller):
        self.controller = controller
        super().__init__(address, Handler)

class Handler(BaseHTTPRequestHandler):
    server_version = "GT-Studio/0.1"
    def log_message(self, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        # Do not expose local file/project operations to foreign web origins.
        host = self.headers.get("Host", "").split(":", 1)[0]
        return host in {"127.0.0.1", "localhost"} and not self.headers.get("Origin")

    def do_GET(self):
        if not self.allowed():
            return self.send_json({"error": "Foreign origin or host"}, 403)
        if self.path == "/health":
            return self.send_json({"application": "GT Studio", "version": "0.1.0", "workspace": str(self.server.controller.workspace)})
        if self.path == "/state":
            return self.send_json({"result": self.server.controller.dispatch("get_state", {})})
        if self.path == "/capabilities":
            return self.send_json({"result": capabilities()})
        if self.path == "/transport":
            return self.send_json({"result": self.server.controller.dispatch("get_transport", {})})
        self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        if not self.allowed():
            return self.send_json({"error": "Foreign origin or host"}, 403)
        if self.path != "/rpc":
            return self.send_json({"error": "Not found"}, 404)
        if self.headers.get_content_type() != "application/json":
            return self.send_json({"error": "Expected application/json"}, 415)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 1024 * 1024:
                raise ValueError("Invalid request size")
            data = json.loads(self.rfile.read(size))
            result = self.server.controller.dispatch(data["action"], data.get("params", {}))
            self.send_json({"result": result})
        except (ValueError, KeyError, TypeError) as e:
            self.send_json({"error": str(e)}, 400)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

def serve(workspace, port=DEFAULT_PORT):
    EditorServer(("127.0.0.1", port), Controller(workspace)).serve_forever(poll_interval=0.25)
