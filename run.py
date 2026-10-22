"""One command to run Hearth: seeds the demo family, starts the MCP server (:8765) and the Streamlit app (:8501).

    python run.py            # both
    python run.py --server   # only the standalone MCP server (use it from any MCP client)
    python run.py --reset    # wipe the database and re-seed first
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def wait_for(url: str, seconds: int = 30) -> bool:
    import httpx
    for _ in range(seconds * 5):
        try:
            if httpx.get(url, timeout=0.5).status_code == 200:
                return True
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    return False


def main() -> int:
    load_env()
    os.chdir(ROOT)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "packages/family_conflicts"),
                                                         os.environ.get("PYTHONPATH", "")])}
    port = os.getenv("HEARTH_PORT", "8765")
    subprocess.run([sys.executable, "-m", "server.seed", *(["--reset"] if "--reset" in sys.argv else [])],
                   env=env, check=True)
    server = subprocess.Popen([sys.executable, "-m", "server.mcp_server"], env=env)
    procs = [server]
    try:
        if not wait_for(f"http://127.0.0.1:{port}/health"):
            print("The MCP server did not start. Check the log above.")
            return 1
        print(f"Hearth MCP server ready at http://127.0.0.1:{port}/mcp")
        if "--server" not in sys.argv:
            ui = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app/main.py",
                                   "--server.port", os.getenv("HEARTH_UI_PORT", "8501")], env=env)
            procs.append(ui)
            print(f"Hearth app at http://localhost:{os.getenv('HEARTH_UI_PORT', '8501')}")
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.send_signal(signal.SIGINT)
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
