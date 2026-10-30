#!/usr/bin/env python3
"""CWV Speed Engine Standalone Production Server on Port 8128.

Provides real REST API endpoints:
  - /health & /api/health
  - /api/audit
  - /api/optimize & /api/transform
  - /api/pwa/generate
  - /api/og/generate
  - /api/diff & /api/compare
  - /api/cache/export
  - /api/mcp/config
  - /api/speculation
  - /api/budget
and serves the standalone CWV Speed Studio from public/.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
PUBLIC_DIR = ROOT_DIR / "public"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cwv_speed_engine.ui_server import start_ui_server

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CWV Speed Engine Standalone Workstation")
    parser.add_argument("--port", type=int, default=8128, help="Port to listen on (default: 8128)")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    args = parser.parse_args()

    print(f"Starting CWV Speed Engine Server on {args.host}:{args.port}...")
    start_ui_server(host=args.host, port=args.port, directory=str(PUBLIC_DIR), blocking=True)
