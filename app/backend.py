"""Python MCP client wrapper used by the UI, the agent and the tests.

Each call opens a short-lived Streamable HTTP session to the standalone Hearth server. The raw
JSON-RPC request and response bodies are captured in `trace` for the Protocol Inspector.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

TRACE_LIMIT = 300


def run_sync(coro):
    """Run a coroutine from sync code, even if an event loop is already running in this thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict[str, Any] = {}

    def target():
        try:
            box["v"] = asyncio.run(coro)
        except BaseException as e:  # noqa: BLE001
            box["e"] = e

    t = threading.Thread(target=target)
    t.start()
    t.join()
    if "e" in box:
        raise box["e"]
    return box["v"]


class MCPBackend:
    def __init__(self, url: str, trace: list | None = None):
        self.url = url
        self.trace: list[dict] = trace if trace is not None else []
        self.protocol_version: str | None = None

    # -- raw traffic capture ------------------------------------------------
    def _log(self, direction: str, body: bytes | str):
        try:
            payload = json.loads(body)
        except Exception:
            return
        self.trace.append({"t": time.time(), "dir": direction, "msg": payload})
        del self.trace[:-TRACE_LIMIT]

    def _client(self) -> httpx.AsyncClient:
        async def on_request(req: httpx.Request):
            if req.method == "POST" and req.content:
                self._log("client → server", req.content)

        async def on_response(resp: httpx.Response):
            if resp.status_code == 200 and "json" in resp.headers.get("content-type", ""):
                await resp.aread()
                self._log("server → client", resp.content)

        return httpx.AsyncClient(
            timeout=httpx.Timeout(30, read=120), follow_redirects=True,
            event_hooks={"request": [on_request], "response": [on_response]},
        )

    async def _with_session(self, fn):
        async with self._client() as http:
            async with streamable_http_client(self.url, http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    self.protocol_version = str(init.protocolVersion)
                    return await fn(session, init)

    # -- public API ----------------------------------------------------------
    def handshake(self) -> dict:
        async def f(session, init):
            return {"protocolVersion": str(init.protocolVersion), "serverInfo": init.serverInfo.model_dump()}
        return run_sync(self._with_session(f))

    def list_tools(self) -> list[dict]:
        async def f(session, init):
            res = await session.list_tools()
            return [{"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema}
                    for t in res.tools]
        return run_sync(self._with_session(f))

    def call(self, name: str, args: dict | None = None) -> dict:
        args = {k: v for k, v in (args or {}).items() if v is not None}

        async def f(session, init):
            res = await session.call_tool(name, args)
            if res.structuredContent is not None:
                data = res.structuredContent
                if set(data) == {"result"} and isinstance(data["result"], dict):
                    data = data["result"]
                return data
            text = "".join(getattr(b, "text", "") for b in res.content)
            try:
                return json.loads(text)
            except Exception:
                return {"ok": False, "error": {"code": "tool_error", "message": text}, "say": text}
        return run_sync(self._with_session(f))
