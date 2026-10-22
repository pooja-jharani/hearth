# Friction log

Honest, dated notes on things that went wrong while building Hearth with MCP, Strands, Bedrock, Polly and Kiro.
Entries below are real problems hit during the first build session (20 Oct 2026). **Add your own entries for Bedrock,
Polly, Kiro and Amazon Devices Builder Tools the moment something fails; none of those were used in that session,
so there are deliberately no entries for them yet. Do not invent any.**

## MCP Python SDK: `pip install mcp` now installs v2, which removed `FastMCP`
- Date: 2026-10-20
- Task attempted: write a standalone Streamable HTTP server using `from mcp.server.fastmcp import FastMCP`.
- Steps taken: `pip install mcp strands-agents ...` in a fresh venv, then imported FastMCP.
- Expected vs actual: expected FastMCP to import. Actual: `ModuleNotFoundError ... In mcp 2.x FastMCP was renamed to MCPServer`.
- Severity: Medium (breaks every existing tutorial and snippet; the error message itself was clear and helpful).
- Workaround used: pinned `mcp==1.30.0`, which supports protocol version 2025-11-25 and works with Strands.
- Actionable suggestion: have the install docs and quickstarts state the major version they target; keep a v1 compatibility import for one release.

## MCP Python SDK: `streamablehttp_client` is deprecated in favour of `streamable_http_client`
- Date: 2026-10-20
- Task attempted: capture raw JSON-RPC traffic for a "Protocol Inspector" view.
- Steps taken: used `streamablehttp_client`, got a DeprecationWarning, switched to `streamable_http_client(url, http_client=...)`.
- Expected vs actual: expected a documented hook for logging messages. Actual: no documented way; the working route was passing my own `httpx.AsyncClient` with event hooks, which only works when the server answers in plain JSON (`json_response=True`) because streamed SSE bodies can't be read in a hook without breaking streaming.
- Severity: Low.
- Workaround used: server runs with `json_response=True`; client logs request and response bodies in httpx hooks.
- Actionable suggestion: add a first-class message-tap / logging hook on `ClientSession` or the transport.

## MCP Python SDK: structured output shape for `dict[str, Any]` tools
- Date: 2026-10-20
- Task attempted: return structured data plus a short spoken sentence from each tool.
- Expected vs actual: unsure whether `structuredContent` is the dict itself or wrapped as `{"result": ...}`; the docs don't say for `dict[str, Any]`. It is the dict itself, found by testing. The client wrapper defensively handles both.
- Severity: Low.
- Workaround used: unwrap `{"result": {...}}` if present.
- Actionable suggestion: document the exact wrapping rules by return annotation.

## Entry template (copy for new problems)
## <tool>: <short title>
- Date:
- Task attempted:
- Steps taken:
- Expected vs actual:
- Severity: Low / Medium / High
- Workaround used:
- Actionable suggestion:
