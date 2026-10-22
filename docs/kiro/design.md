# Design

Standalone FastMCP server (`server/mcp_server.py`, Streamable HTTP at /mcp) -> services -> SQLite. The pure
`family_conflicts` package decides all conflicts and fix rankings; the LLM only picks tools. Streamlit app is an MCP
client (Strands + Bedrock, or a scripted mock). Changes go pending then commit; an audit log powers Undo.
See README and `packages/family_conflicts/README.md`.
