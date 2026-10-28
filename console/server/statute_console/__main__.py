"""python -m statute_console [--repo PATH] [--port 8765]

Run from console/server (or put console/server on PYTHONPATH).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .model import Workspace
from .server import serve


def main() -> None:
    here = Path(__file__).resolve()
    default_repo = here.parents[3]
    ap = argparse.ArgumentParser(description="STATUTE Console — read-only operational console")
    ap.add_argument("--repo", default=str(default_repo), help="STATUTE repository root")
    ap.add_argument("--output", default=None, help="Output root (default: <repo>/output)")
    ap.add_argument("--allow-source-root", action="append", default=[],
                    help="Additional directory from which source lines may be shown (default: the repo only)")
    ap.add_argument("--annotations", default=None, help="Annotations file (default: <repo>/brd_annotations.json)")
    ap.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1 — keep it local)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--static", default=str(here.parents[2] / "web" / "dist"), help="Built UI directory")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    ws = Workspace(repo, Path(args.output).resolve() if args.output else None,
                   [repo] + [Path(p).resolve() for p in args.allow_source_root],
                   Path(args.annotations).resolve() if args.annotations else None)
    if args.host not in ("127.0.0.1", "localhost"):
        print(f"WARNING: binding {args.host} exposes corpus-derived content beyond this machine.", file=sys.stderr)
    httpd = serve(ws, args.host, args.port, Path(args.static))
    static = Path(args.static)
    print(f"STATUTE Console · repo {repo}")
    print(f"  output  : {ws.output}")
    print(f"  UI      : {'built' if static.is_dir() else 'not built (API only)'}")
    print(f"  serving : http://{args.host}:{args.port}/  (read-only, Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
