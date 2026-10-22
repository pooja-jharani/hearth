from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolEvent:
    """One MCP tool call made while answering a message."""
    name: str
    args: dict
    result: dict


@dataclass
class AgentReply:
    text: str
    events: list[ToolEvent] = field(default_factory=list)
    provider: str = "mock"
    error: str | None = None
