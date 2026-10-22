"""Shared fixtures. The MCP server is started as a real subprocess on a free port."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
# Thursday 22 Oct 2026 is the demo Thursday; "now" is Tuesday 20 Oct, 10:00 IST.
DEMO_NOW = "2026-10-20T10:00:00+05:30"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def server(tmp_path):
    """A seeded server on its own DB and port. Yields (url, db_path)."""
    db = str(tmp_path / "hearth.db")
    port = free_port()
    env = {**os.environ, "HEARTH_DB": db, "HEARTH_PORT": str(port), "HEARTH_NOW": DEMO_NOW,
           "PYTHONPATH": f"{ROOT}:{ROOT / 'packages/family_conflicts'}"}
    subprocess.run([sys.executable, "-m", "server.seed", "--reset"], cwd=ROOT, env=env, check=True,
                   capture_output=True)
    proc = subprocess.Popen([sys.executable, "-m", "server.mcp_server"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{url}/health", timeout=0.5).status_code == 200:
                break
        except Exception:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("server did not start: " + proc.stdout.read().decode()[-2000:])
    yield url, db
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture()
def backend(server, monkeypatch):
    from app.backend import MCPBackend
    monkeypatch.setenv("HEARTH_NOW", DEMO_NOW)
    return MCPBackend(server[0] + "/mcp")
