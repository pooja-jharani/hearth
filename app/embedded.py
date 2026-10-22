"""Start the Hearth MCP server inside the same container when the app is hosted alone (e.g. Streamlit Community Cloud).

Locally `python run.py` already starts the server, so this does nothing when the server answers /health.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def _up(port: str) -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5).status_code == 200
    except Exception:  # noqa: BLE001
        return False


def ensure_server() -> None:
    port = os.getenv("HEARTH_PORT", "8765")
    if os.getenv("HEARTH_MCP_URL") or _up(port):
        return
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "packages/family_conflicts"),
                                                         os.environ.get("PYTHONPATH", "")])}
    subprocess.run([sys.executable, "-m", "server.seed"], env=env, cwd=ROOT, check=True)
    subprocess.Popen([sys.executable, "-m", "server.mcp_server"], env=env, cwd=ROOT)
    for _ in range(100):
        if _up(port):
            return
        time.sleep(0.2)
