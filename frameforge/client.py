import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

def rpc(url, action, params=None, timeout=450):
    request = Request(url + "/rpc", json.dumps({"action": action, "params": params or {}}, allow_nan=False).encode(), {"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as e:
        result = json.load(e)
    if "error" in result:
        raise ValueError(result["error"])
    return result["result"]

def ensure_service(workspace, port=18771):
    url = f"http://127.0.0.1:{port}"
    workspace = Path(workspace).resolve()
    def health():
        try:
            with urlopen(url + "/health", timeout=1) as response:
                data = json.load(response)
            if data.get("application") != "GT Studio" or data.get("workspace") != str(workspace):
                raise RuntimeError(f"Port {port} belongs to another service/workspace")
            return True
        except (URLError, TimeoutError, ConnectionError):
            return False
    if health():
        return url
    workspace.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parent.parent
    with open(workspace / "service.log", "ab") as log:
        process = subprocess.Popen([sys.executable, str(root / "frameforge_entry.py"), "serve", "--workspace", str(workspace), "--port", str(port)], cwd=root, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(60):
        if health():
            return url
        if process.poll() is not None:
            raise RuntimeError(f"Editor service exited; see {workspace / 'service.log'}")
        time.sleep(0.1)
    raise RuntimeError("Editor service did not become ready")
