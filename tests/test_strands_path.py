"""Exercises the real Strands agent loop and Strands' own MCP client against the real Hearth server,
using a stub model instead of Amazon Bedrock (so no AWS account is needed)."""
import json

import pytest

strands = pytest.importorskip("strands")
from strands.models import Model

from app.agent import HearthAgent


class ScriptedModel(Model):
    """Calls one tool on the first request of a turn, then speaks the tool's own `say`."""

    def __init__(self, tool, args):
        self.tool, self.args, self.system_prompts = tool, args, []

    def update_config(self, **kw):
        pass

    def get_config(self):
        return {}

    def structured_output(self, output_model, prompt, system_prompt=None, **kw):
        raise NotImplementedError

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
        self.system_prompts.append(system_prompt)
        self.tool_names = [t["name"] for t in (tool_specs or [])]
        last = messages[-1]
        result = next((b["toolResult"] for b in last["content"] if "toolResult" in b), None)
        yield {"messageStart": {"role": "assistant"}}
        if result is None:
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "t1", "name": self.tool}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(self.args)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            blocks = result["content"]
            text = blocks[0].get("text") or json.dumps(blocks[0].get("json"))
            say = json.loads(text).get("say", "Done.")
            yield {"contentBlockDelta": {"delta": {"text": say}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}


def test_strands_agent_calls_hearth_over_mcp(backend):
    agent = HearthAgent(backend, "bedrock")
    agent.model_override = ScriptedModel("add_event", {
        "title": "Swimming", "start": "2026-10-21T17:00:00", "attendees": ["Rohan"], "created_by": "Mom"})
    state = {}
    reply = agent.respond("Mom", "Rohan has swimming tomorrow at 5", state)
    assert reply.error is None, reply.error
    assert [e.name for e in reply.events] == ["add_event"]
    assert reply.events[0].result["event"]["title"] == "Swimming"
    assert reply.text.startswith("Added Swimming for tomorrow at 5 pm")
    # tools were discovered from the server's tools/list and the system prompt carries family context
    assert {"add_event", "commit_action", "week_guard"} <= set(agent.model_override.tool_names)
    prompt = agent.model_override.system_prompts[0]
    assert "Speaker: Mom" in prompt and "Dadi (grandparent)" in prompt
    # the event really is in the server's database
    names = [e["title"] for e in backend.call("list_events", {})["events"]]
    assert "Swimming" in names
