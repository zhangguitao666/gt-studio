import argparse
from pathlib import Path

def main():
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="GT Studio independent desktop editor and MCP control")
    parser.add_argument("mode", choices=["ui", "serve", "mcp"], nargs="?", default="ui")
    parser.add_argument("--workspace", type=Path, default=root / "workspace")
    parser.add_argument("--port", type=int, default=18771)
    args = parser.parse_args()
    if args.mode == "serve":
        from .service import serve
        serve(args.workspace, args.port)
    elif args.mode == "mcp":
        from .mcp import run
        run(args.workspace, args.port)
    else:
        from .client import ensure_service
        from .ui import start_ui
        start_ui(ensure_service(args.workspace, args.port))

if __name__ == "__main__":
    main()
