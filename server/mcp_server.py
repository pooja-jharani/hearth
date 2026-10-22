"""Hearth MCP server: a standalone, self-hosted Streamable HTTP server (endpoint /mcp).

Every tool returns structured data plus a short speakable sentence in `say`.
The LLM never touches the database and never decides conflicts; only these tools do.

Run: python -m server.mcp_server   (HEARTH_HOST / HEARTH_PORT / HEARTH_DB are optional)
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import db
from .services import chores, common, guard, help_requests, rules
from .services import events as event_svc
from .services.common import HearthError

log = logging.getLogger("hearth.server")

HOST = os.getenv("HEARTH_HOST", "127.0.0.1")
PORT = int(os.getenv("HEARTH_PORT", "8765"))

INSTRUCTIONS = """Hearth is a family coordinator: a shared calendar with conflict detection, family rules
and fair chores. Times are ISO 8601; a time without an offset is read in the family timezone.
Reads run directly. Changes to existing events (move_event, delete_event) never apply directly: they
return a pending_action_id and a preview; call commit_action only after the user says yes.
Every result has a short speakable sentence in `say`."""

mcp = FastMCP("Hearth", instructions=INSTRUCTIONS, host=HOST, port=PORT, stateless_http=True, json_response=True)


class BulkEvent(BaseModel):
    title: str
    start: str = Field(description="ISO 8601 start time")
    end: str | None = Field(default=None, description="ISO 8601 end time")
    duration_min: int | None = Field(default=None, description="Minutes, used when end is missing (default 60)")
    attendees: list[str | int] | None = Field(default=None, description="Member names; defaults to the speaker")
    location: str | None = None
    needs_adult: bool = False
    movable: bool = True


def run(fn: Callable[..., dict], **kwargs: Any) -> dict[str, Any]:
    """Open a DB session, call the service, and turn failures into structured errors."""
    try:
        with db.session() as s:
            out = fn(s, **kwargs)
        return {"ok": True, **out}
    except HearthError as err:
        return {"ok": False, "error": {"code": err.code, "message": err.message}, "say": err.message}
    except Exception:  # never leak a stack trace to the client
        log.exception("tool failed: %s", getattr(fn, "__name__", fn))
        msg = "Sorry, something went wrong on my side. Please try again."
        return {"ok": False, "error": {"code": "internal", "message": msg}, "say": msg}


# ---------------------------------------------------------------- tier 1

@mcp.tool()
def list_members() -> dict[str, Any]:
    """List the family members, their roles and whether they are adults."""
    def f(s):
        ms = [{"id": m.id, "name": m.name, "role": m.role, "is_adult": m.is_adult,
               "color": m.color, "initials": m.initials} for m in common.members(s)]
        return {"members": ms, "say": "The family is " + ", ".join(m["name"] for m in ms) + "."}
    return run(f)


@mcp.tool()
def add_event(title: str, start: str, created_by: str, end: str | None = None, duration_min: int | None = None,
              attendees: list[str | int] | None = None, location: str | None = None,
              needs_adult: bool = False, movable: bool = True) -> dict[str, Any]:
    """Add one event to the family calendar and report any conflicts it causes.

    start/end are ISO 8601. If end and duration_min are both missing, one hour is assumed.
    attendees are member names (defaults to the speaker). Set needs_adult for events where a
    child needs a grown-up present (school meetings, activities). Set movable=false for events
    that cannot be rescheduled. Events created by a child wait for a parent's approval."""
    return run(event_svc.add_event, title=title, start=start, end=end, duration_min=duration_min,
               attendees=attendees, location=location, needs_adult=needs_adult, movable=movable,
               created_by=created_by)


@mcp.tool()
def list_events(from_time: str | None = None, to_time: str | None = None,
                member: str | int | None = None) -> dict[str, Any]:
    """List events between two ISO times (default: the next 7 days), optionally for one member."""
    return run(event_svc.list_events, from_time=from_time, to_time=to_time, member=member)


@mcp.tool()
def detect_conflicts(from_time: str | None = None, to_time: str | None = None) -> dict[str, Any]:
    """Find clashes (person, coverage, rule) in a time window (default: the next 7 days)."""
    return run(event_svc.detect_conflicts, from_time=from_time, to_time=to_time)


@mcp.tool()
def find_free_slot(attendees: list[str | int], duration_min: int, earliest: str | None = None,
                   latest: str | None = None, needs_adult: bool = False) -> dict[str, Any]:
    """Find up to 3 times when all attendees are free, inside waking hours (8 am to 9 pm)."""
    return run(event_svc.find_free_slot, attendees=attendees, duration_min=duration_min,
               earliest=earliest, latest=latest, needs_adult=needs_adult)


@mcp.tool()
def suggest_resolutions(conflict_id: str) -> dict[str, Any]:
    """Give 2 to 3 ranked ways to fix a conflict, each with a reason. Does not change anything."""
    return run(event_svc.suggest_resolutions, conflict_id=conflict_id)


@mcp.tool()
def move_event(event_id: int, actor: str, new_start: str | None = None, add_attendee: str | int | None = None,
               remove_attendee: str | int | None = None) -> dict[str, Any]:
    """Propose moving an event or changing who attends. Nothing changes until commit_action.

    Returns a pending_action_id and a preview. Children cannot change adults' event_svc."""
    return run(event_svc.move_event, event_id=event_id, actor=actor, new_start=new_start,
               add_attendee=add_attendee, remove_attendee=remove_attendee)


@mcp.tool()
def delete_event(event_id: int, actor: str) -> dict[str, Any]:
    """Propose deleting an event. Nothing changes until commit_action."""
    return run(event_svc.delete_event, event_id=event_id, actor=actor)


@mcp.tool()
def commit_action(pending_action_id: int) -> dict[str, Any]:
    """Apply a pending move or delete after the user confirmed. Returns conflicts_after."""
    return run(event_svc.commit_action, pending_action_id=pending_action_id)


@mcp.tool()
def undo_last(actor: str | None = None) -> dict[str, Any]:
    """Undo the most recent change (add, move or delete)."""
    return run(event_svc.undo_last, actor=actor)


@mcp.tool()
def assign_chore(title: str, effort: int = 2, kid_ok: bool = False, due: str | None = None,
                 assign_to: str | int | None = None) -> dict[str, Any]:
    """Create a chore and assign it to the fairest eligible member, with the reason.

    effort is 1 to 5 points. Children only get chores with kid_ok=true."""
    return run(chores.assign_chore, title=title, effort=effort, kid_ok=kid_ok, due=due, assign_to=assign_to)


@mcp.tool()
def complete_chore(chore_id: int) -> dict[str, Any]:
    """Mark a chore as done."""
    return run(chores.complete_chore, chore_id=chore_id)


@mcp.tool()
def list_chores(member: str | int | None = None, status: str | None = None) -> dict[str, Any]:
    """List chores (status: open or done) and each member's load score for the last 14 days."""
    return run(chores.list_chores, member=member, status=status)


@mcp.tool()
def family_summary(range: str = "week") -> dict[str, Any]:
    """Summarise a range: today, tomorrow, week or next_week."""
    return run(guard.family_summary, range=range)


@mcp.tool()
def add_rule(member: str | int, kind: str, time: str | None = None, task: str | None = None,
             source_text: str = "") -> dict[str, Any]:
    """Save a standing family rule that every plan is checked against.

    kind: no_after (member can't do the task at or after `time`), no_before (not before `time`),
    no_task (member never does the task). task is a short lowercase noun like 'pickup'.
    Example: "Dadi can't do evening pickups" -> member=Dadi, kind=no_after, time=17:00, task=pickup."""
    return run(rules.add_rule, member=member, kind=kind, time=time, task=task, source_text=source_text)


@mcp.tool()
def list_rules() -> dict[str, Any]:
    """List the saved family rules."""
    return run(rules.list_rules)


@mcp.tool()
def remove_rule(rule_id: int) -> dict[str, Any]:
    """Remove a saved family rule."""
    return run(rules.remove_rule, rule_id=rule_id)


# ---------------------------------------------------------------- tier 2

@mcp.tool()
def add_events_bulk(events: list[BulkEvent], created_by: str) -> dict[str, Any]:
    """Add several events from one sentence. Returns a result per event and all conflicts."""
    return run(event_svc.add_events_bulk, events=[e.model_dump() for e in events], created_by=created_by)


@mcp.tool()
def week_guard(days: int = 7) -> dict[str, Any]:
    """Scan the next days for risks: clashes, thin adult cover, overloaded days, overdue chores."""
    return run(guard.week_guard, days=days)


@mcp.tool()
def list_pending_approvals(member: str | int | None = None) -> dict[str, Any]:
    """The inbox: child-created events waiting for a parent's approval, plus requests waiting for an answer
    (pass member to see only the requests addressed to that person)."""
    return run(help_requests.inbox, member=member)


@mcp.tool()
def ask_member(event_id: int, member: str | int, actor: str) -> dict[str, Any]:
    """Ask someone to join an event (for example, ask Dadi to attend the PTM when both parents are busy).
    Nothing changes until that person answers with respond_request."""
    return run(help_requests.ask_member, event_id=event_id, member=member, actor=actor)


@mcp.tool()
def respond_request(request_id: int, actor: str, accept: bool) -> dict[str, Any]:
    """Answer a request addressed to you. Accepting adds you to the event; the result says if the clash is gone."""
    return run(help_requests.respond_request, request_id=request_id, actor=actor, accept=accept)


@mcp.tool()
def approve_event(event_id: int, actor: str) -> dict[str, Any]:
    """Approve a child's event. Only adults can approve."""
    return run(event_svc.approve_event, event_id=event_id, actor=actor)


@mcp.tool()
def planning_load(days: int = 14) -> dict[str, Any]:
    """Who carries the planning load: events, hours, plans organised and chore points per member."""
    return run(guard.planning_load, days=days)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "hearth"})


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    db.init()
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
