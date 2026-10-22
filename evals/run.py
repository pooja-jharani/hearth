"""Agent eval: python -m evals.run [--live]

Replays evals/utterances.yaml against a fresh seeded server per case and prints the pass rate.
Mock mode needs no AWS. --live uses LLM_PROVIDER=bedrock (needs AWS credentials and Bedrock access).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
NOW = "2026-10-20T10:00:00+05:30"
PLUMBING = {"list_events", "list_members"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(tmp: str):
    port = free_port()
    env = {**os.environ, "HEARTH_DB": f"{tmp}/e.db", "HEARTH_PORT": str(port), "HEARTH_NOW": NOW,
           "PYTHONPATH": f"{ROOT}:{ROOT / 'packages/family_conflicts'}"}
    os.environ.update({"HEARTH_NOW": NOW})
    subprocess.run([sys.executable, "-m", "server.seed", "--reset"], cwd=ROOT, env=env, check=True, capture_output=True)
    proc = subprocess.Popen([sys.executable, "-m", "server.mcp_server"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5).status_code == 200:
                return proc, f"http://127.0.0.1:{port}/mcp"
        except Exception:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("server did not start")


def match(expected, actual) -> bool:
    if isinstance(expected, list):
        return isinstance(actual, list) and all(
            any(match(e, a) for a in actual) for e in expected)
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.lower() in actual.lower()
    return expected == actual


def main() -> int:
    sys.path[:0] = [str(ROOT), str(ROOT / "packages/family_conflicts")]
    from app.agent import HearthAgent
    from app.backend import MCPBackend

    provider = "bedrock" if "--live" in sys.argv else "mock"
    cases = yaml.safe_load((ROOT / "evals/utterances.yaml").read_text())
    passed = 0
    for i, case in enumerate(cases, 1):
        with tempfile.TemporaryDirectory() as tmp:
            proc, url = start_server(tmp)
            try:
                agent, state = HearthAgent(MCPBackend(url), provider), {}
                for prior in case.get("given", []):
                    agent.respond(case["speaker"], prior, state)
                reply = agent.respond(case["speaker"], case["say"], state)
                calls = [e for e in reply.events if e.name not in PLUMBING]
                first = calls[0] if calls else None
                ok = bool(first) and first.name == case["tool"] and all(
                    match(v, first.args.get(k)) for k, v in case.get("args", {}).items())
                got = f"{first.name} {first.args}" if first else f"no tool call ({reply.text[:60]})"
            finally:
                proc.terminate()
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {i:2d}. {case['say'][:60]!r}" + ("" if ok else f"\n        expected {case['tool']} {case.get('args', '')}\n        got      {got}"))
    print(f"\n{provider} mode: {passed}/{len(cases)} passed ({100 * passed // len(cases)}%)")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
