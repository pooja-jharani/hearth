"""The Hearth agent.

Three interchangeable providers, all talking to the standalone MCP server through `MCPBackend`:

* ``mock``     scripted tool calls (no AWS needed; used for development, tests and offline demos)
* ``bedrock``  Strands Agents SDK + Amazon Bedrock, tools discovered from the server's tools/list
* fallback     if Strands fails to start, a plain Bedrock Converse tool loop over the same tools

The model never touches the database and never decides conflicts; it only picks MCP tools.
"""
from __future__ import annotations

import json
import logging
import os

from server.services.common import TZ, now

from .backend import MCPBackend
from .mock_llm import MockPolicy
from .types import AgentReply, ToolEvent

log = logging.getLogger("hearth.agent")

MAX_TOOL_ROUNDS = 4
HISTORY_LIMIT = 16

SYSTEM_PROMPT = """You are Hearth, the voice of a family calendar. Replies are spoken aloud, so keep them to one or
two short, warm sentences. Say names and times, never IDs.

Now: {now} ({tz}). Speaker: {speaker}.
Family: {members}.
Saved family rules: {rules}.

How to work:
- Reply in the language the speaker used: Hindi (Devanagari) or English. Hinglish in, Hindi or English out is fine.
  Keep tool arguments (titles, member names) as the speaker said them.
- Resolve relative dates ("Thursday", "tomorrow") from Now before calling a tool. Send ISO 8601 times.
- If a time has no am/pm, assume the sensible one for family life (5 is 5 pm, 7 is 7 am only when it says morning).
- Add events with add_event, or add_events_bulk when one sentence has several. Always read `conflicts`.
- If there are conflicts, explain the first in one sentence. Only call suggest_resolutions when the user asks
  what can be done. Offer at most 3 options.
- Never change an event without confirmation: move_event and delete_event only create a pending action. Show
  its `say`, wait for a yes, then call commit_action with the pending_action_id.
- If someone states a standing preference ("Dadi can't do evening pickups"), save it with add_rule and repeat it back.
- For "what's happening" use family_summary; for risks use week_guard; for chores use assign_chore.
- Pasted school circulars: extract each dated item and call add_events_bulk (attendee Rohan; needs_adult for PTMs).
- Speak the tool's `say` rather than inventing details. Never invent members, times or conflicts. Never claim
  success before the tool returns ok. If a tool returns an error, ask the user one short question.
- No medical or legal advice. Use at most {rounds} tool calls per message."""


def update_state(state: dict, events: list[ToolEvent]) -> None:
    """Remember what the next message may refer to (a pending action, the last clash, offered options)."""
    for e in events:
        r = e.result or {}
        if not r.get("ok", True):
            continue
        if e.name == "commit_action" or e.name == "undo_last":
            state["pending_id"] = None
        if r.get("pending_action_id"):
            state["pending_id"] = r["pending_action_id"]
        confl = r.get("conflicts") or r.get("conflicts_after")
        if e.name in ("add_event", "add_events_bulk", "approve_event", "detect_conflicts", "add_rule") and confl:
            state["conflict_id"] = confl[0]["id"]
        if e.name in ("commit_action",) and not confl:
            state["conflict_id"] = None
        if e.name == "suggest_resolutions":
            state["options"] = r.get("options", [])
        if e.name in ("add_event", "approve_event") and r.get("event"):
            state["last_event"] = r["event"]


def _parse_json(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {"ok": False, "say": str(value)}


class HearthAgent:
    def __init__(self, backend: MCPBackend, provider: str | None = None):
        self.backend = backend
        self.provider = (provider or os.getenv("LLM_PROVIDER", "mock")).lower()
        self.model_id = os.getenv("BEDROCK_MODEL", "us.amazon.nova-lite-v1:0")
        self.region = os.getenv("AWS_REGION", "us-east-1")
        self.history: list[dict] = []
        self.model_override = None  # tests inject a stub Strands model here
        self.mock = MockPolicy(backend, now, TZ)

    # ---------------------------------------------------------------- public
    def respond(self, speaker: str, text: str, state: dict) -> AgentReply:
        try:
            if self.provider == "mock":
                reply, events = self.mock.respond(speaker, text, state)
                update_state(state, events)
                return AgentReply(reply, events, "mock")
            reply = self._live(speaker, text)
            update_state(state, reply.events)
            return reply
        except Exception as err:
            log.exception("agent failed")
            return AgentReply("Sorry, I couldn't do that just now. Please try again.", [], self.provider,
                              error=f"{type(err).__name__}: {err}")

    def apply_option(self, speaker: str, option: dict, state: dict) -> AgentReply:
        """Deterministic path for a tapped option card: no model involved."""
        reply, events = self.mock.apply_option(speaker, option, [])
        update_state(state, events)
        return AgentReply(reply, events, "direct")

    # ------------------------------------------------------------------ live
    def system_prompt(self, speaker: str) -> str:
        members = self.backend.call("list_members", {}).get("members", [])
        rules = self.backend.call("list_rules", {}).get("rules", [])
        return SYSTEM_PROMPT.format(
            now=now().astimezone(TZ).strftime("%A %d %B %Y, %I:%M %p"), tz=str(TZ), speaker=speaker,
            members=", ".join(f"{m['name']} ({m['role']})" for m in members) or "none",
            rules="; ".join(r["description"] for r in rules) or "none yet", rounds=MAX_TOOL_ROUNDS)

    def _live(self, speaker: str, text: str) -> AgentReply:
        prompt = self.system_prompt(speaker)
        if self.model_override is not None:  # tests: surface Strands errors instead of falling back
            return self._strands(prompt, text)
        try:
            return self._strands(prompt, text)
        except Exception:
            log.exception("Strands path failed; falling back to the plain Bedrock Converse loop")
            return self._converse(prompt, text)

    def _trim(self):
        """Keep the last few turns, cutting only at a user text message so tool pairs stay intact."""
        if len(self.history) <= HISTORY_LIMIT:
            return
        for i in range(len(self.history) - HISTORY_LIMIT, len(self.history)):
            m = self.history[i]
            if m["role"] == "user" and any("text" in b for b in m["content"]):
                self.history = self.history[i:]
                return
        self.history = []

    def _strands(self, prompt: str, text: str) -> AgentReply:
        from mcp.client.streamable_http import streamable_http_client
        from strands import Agent
        from strands.models import BedrockModel
        from strands.tools.mcp import MCPClient

        client = MCPClient(lambda: streamable_http_client(self.backend.url))
        model = self.model_override or BedrockModel(model_id=self.model_id, region_name=self.region,
                                                    temperature=0.2, max_tokens=700)
        self._trim()
        with client:
            tools = client.list_tools_sync()
            agent = Agent(model=model, tools=tools, system_prompt=prompt, messages=list(self.history),
                          callback_handler=None)
            budget = {"left": MAX_TOOL_ROUNDS}
            try:
                from strands.hooks import BeforeToolCallEvent

                def limit(event):
                    budget["left"] -= 1
                    if budget["left"] < 0:
                        event.cancel_tool = "Tool limit reached. Answer briefly with what you have."
                agent.hooks.add_callback(BeforeToolCallEvent, limit)
            except Exception:  # noqa: BLE001  (hook API differs between versions; the prompt also states the limit)
                log.warning("could not install the tool-round limit hook")
            start = len(agent.messages)
            result = agent(text)
        self.history = list(agent.messages)
        events = events_from_messages(agent.messages[start:])
        for e in events:
            self.backend.trace.append({"t": __import__("time").time(), "dir": "agent → server",
                                       "msg": {"method": "tools/call", "params": {"name": e.name, "arguments": e.args}}})
        spoken = str(result).strip() or (events[-1].result.get("say") if events else "")
        return AgentReply(spoken or "Done.", events, "bedrock")

    def _converse(self, prompt: str, text: str) -> AgentReply:
        import boto3

        brt = boto3.client("bedrock-runtime", region_name=self.region)
        specs = [{"toolSpec": {"name": t["name"], "description": t["description"][:900],
                               "inputSchema": {"json": t["inputSchema"]}}} for t in self.backend.list_tools()]
        self._trim()
        messages = list(self.history) + [{"role": "user", "content": [{"text": text}]}]
        len(messages) - 1
        events: list[ToolEvent] = []
        spoken = ""
        for _ in range(MAX_TOOL_ROUNDS + 1):
            resp = brt.converse(modelId=self.model_id, system=[{"text": prompt}], messages=messages,
                                toolConfig={"tools": specs}, inferenceConfig={"maxTokens": 700, "temperature": 0.2})
            msg = resp["output"]["message"]
            messages.append(msg)
            spoken = " ".join(b["text"] for b in msg["content"] if "text" in b).strip() or spoken
            uses = [b["toolUse"] for b in msg["content"] if "toolUse" in b]
            if not uses or len([e for e in events]) >= MAX_TOOL_ROUNDS * 3:
                break
            results = []
            for u in uses:
                out = self.backend.call(u["name"], u["input"])
                events.append(ToolEvent(u["name"], u["input"], out))
                results.append({"toolResult": {"toolUseId": u["toolUseId"], "content": [{"json": out}]}})
            messages.append({"role": "user", "content": results})
        self.history = messages
        if not spoken and events:
            spoken = events[-1].result.get("say", "Done.")
        return AgentReply(spoken or "Done.", events, "bedrock-converse")


def events_from_messages(messages: list[dict]) -> list[ToolEvent]:
    """Pair toolUse blocks with their toolResult blocks from a Strands/Converse message list."""
    uses: dict[str, dict] = {}
    out: list[ToolEvent] = []
    for m in messages:
        for b in m.get("content", []):
            if "toolUse" in b:
                uses[b["toolUse"]["toolUseId"]] = b["toolUse"]
            elif "toolResult" in b:
                tr = b["toolResult"]
                use = uses.get(tr["toolUseId"], {})
                payload: dict = {}
                for c in tr.get("content", []):
                    if "json" in c:
                        payload = c["json"]
                    elif "text" in c:
                        payload = _parse_json(c["text"])
                out.append(ToolEvent(use.get("name", "?"), use.get("input", {}), payload))
    return out
