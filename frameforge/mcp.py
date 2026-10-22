"""MCP stdio JSON-RPC adapter. All mutations share the live desktop state."""
import json
import sys
from .client import ensure_service, rpc
from .control import SCHEMAS, DESCRIPTIONS, validate

def run(workspace, port=18771):
    url = None
    def connection():
        nonlocal url
        if url is None:
            url = ensure_service(workspace, port)
        return url
    def result(req):
        method = req.get("method")
        params = req.get("params", {})
        if method == "initialize":
            version = params.get("protocolVersion")
            supported = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}
            return {"protocolVersion": version if version in supported else "2025-11-25", "capabilities": {"tools": {}, "resources": {}}, "serverInfo": {"name": "gt-studio", "title": "GT Studio", "version": "0.1.0"}, "instructions": "GT Studio: independent video editor reconstruction in development; full Resolve parity is not implemented. Use get_capabilities to inspect limits. Frame units follow project FPS. UI and tools share state."}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [{"name": action, "description": DESCRIPTIONS.get(action, action.replace("_", " ").capitalize() + " in the live independent editor."), "inputSchema": schema, "annotations": {"readOnlyHint": action in {"get_state", "get_capabilities", "get_transport", "list_actions", "probe_media", "inspect_fusion_settings", "get_fusion_graph", "get_render_job", "list_render_jobs"}, "openWorldHint": False}} for action, schema in SCHEMAS.items() if action != "report_transport"]}
        if method == "tools/call":
            try:
                action = params["name"]
                arguments = params.get("arguments", {})
                validate(action, arguments)
                data = rpc(connection(), action, arguments)
                return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "structuredContent": data if isinstance(data, dict) else {"result": data}, "isError": False}
            except Exception as e:
                return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        if method == "resources/list":
            return {"resources": [{"uri": "gt-studio://project", "name": "Live editor project", "mimeType": "application/json"}, {"uri": "gt-studio://capabilities", "name": "Implementation and parity status", "mimeType": "application/json"}]}
        if method == "resources/read":
            uri = params.get("uri")
            action = {"gt-studio://project": "get_state", "gt-studio://capabilities": "get_capabilities", "frameforge://project": "get_state", "frameforge://capabilities": "get_capabilities"}.get(uri)
            if not action:
                raise LookupError("Unknown resource")
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(rpc(connection(), action), ensure_ascii=False)}]}
        raise LookupError("Method not found")
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("Request must be an object")
            if "id" not in request:
                continue
            reply = {"jsonrpc": "2.0", "id": request["id"], "result": result(request)}
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        except LookupError as e:
            reply = {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": -32601, "message": str(e)}}
        except Exception as e:
            reply = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None, "error": {"code": -32602, "message": str(e)}}
        print(json.dumps(reply, ensure_ascii=False, allow_nan=False), flush=True)
