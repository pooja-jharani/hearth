"""Turn MCP tool results into UI cards (plain dicts), independent of Streamlit so it can be tested."""
from __future__ import annotations

import uuid

from .types import ToolEvent

# tools whose results are only plumbing for the agent; they never get a card of their own
SILENT = {"list_events", "list_members"}


def _id() -> str:
    return uuid.uuid4().hex[:8]


def conflict_cards(conflicts: list[dict]) -> list[dict]:
    return [{"id": _id(), "kind": "conflict", "conflict": c} for c in conflicts]


def cards_from_events(events: list[ToolEvent]) -> list[dict]:
    cards: list[dict] = []
    for e in events:
        r = e.result or {}
        if e.name in SILENT:
            continue
        if not r.get("ok", True):
            cards.append({"id": _id(), "kind": "error", "text": r.get("say") or "Something went wrong."})
            continue
        n = e.name
        if n == "add_event":
            cards.append({"id": _id(), "kind": "event", "event": r["event"], "assumed": r.get("assumed_duration"),
                          "approval": r.get("needs_approval")})
            cards += conflict_cards(r.get("conflicts", []))
        elif n == "add_events_bulk":
            added = [x["event"] for x in r["results"] if x.get("ok") and x.get("event")]
            failed = [x for x in r["results"] if not x.get("ok")]
            cards.append({"id": _id(), "kind": "bulk", "events": added, "failed": failed})
            cards += conflict_cards(r.get("conflicts", []))
        elif n in ("detect_conflicts",):
            cards += conflict_cards(r.get("conflicts", [])) or [{"id": _id(), "kind": "info", "title": "No clashes",
                                                                 "text": r["say"]}]
        elif n == "suggest_resolutions":
            cards.append({"id": _id(), "kind": "options", "conflict": r["conflict"], "options": r["options"]})
        elif n in ("move_event", "delete_event"):
            cards.append({"id": _id(), "kind": "confirm", "pending_id": r["pending_action_id"],
                          "preview": r["preview"], "text": r["say"]})
        elif n == "commit_action":
            cards.append({"id": _id(), "kind": "done", "text": r["say"], "undo": r.get("undo_available", False),
                          "conflicts": r.get("conflicts_after", [])})
            cards += conflict_cards(r.get("conflicts_after", []))
        elif n == "undo_last":
            cards.append({"id": _id(), "kind": "info", "title": "Undone", "text": r["say"]})
        elif n == "add_rule":
            cards.append({"id": _id(), "kind": "rule", "rule": r["rule"]})
            cards += conflict_cards(r.get("existing_conflicts", []))
        elif n == "list_rules":
            cards.append({"id": _id(), "kind": "rules", "rules": r["rules"]})
        elif n == "remove_rule":
            cards.append({"id": _id(), "kind": "info", "title": "Rule removed", "text": r["say"]})
        elif n == "assign_chore":
            cards.append({"id": _id(), "kind": "chore", "chore": r["chore"], "reason": r["reason"]})
        elif n == "complete_chore":
            cards.append({"id": _id(), "kind": "info", "title": "Chore done", "text": r["say"]})
        elif n == "list_chores":
            cards.append({"id": _id(), "kind": "chores", "chores": r["chores"], "scores": r["scores"]})
        elif n == "family_summary":
            cards.append({"id": _id(), "kind": "summary", "data": r})
            cards += conflict_cards(r.get("conflicts", []))
        elif n == "week_guard":
            cards.append({"id": _id(), "kind": "guard", "data": r})
        elif n == "find_free_slot":
            cards.append({"id": _id(), "kind": "slots", "slots": r["slots"], "text": r["say"]})
        elif n == "approve_event":
            cards.append({"id": _id(), "kind": "event", "event": r["event"], "assumed": False, "approval": False})
            cards += conflict_cards(r.get("conflicts", []))
        elif n == "list_pending_approvals":
            cards.append({"id": _id(), "kind": "approvals", "events": r["events"], "requests": r.get("requests", [])})
        elif n == "ask_member":
            cards.append({"id": _id(), "kind": "asked", "request": r["request"], "text": r["say"]})
        elif n == "respond_request":
            cards.append({"id": _id(), "kind": "done", "text": r["say"], "undo": r.get("undo_available", False),
                          "conflicts": r.get("conflicts_after", [])})
            cards += conflict_cards(r.get("conflicts_after", []))
        elif n == "planning_load":
            cards.append({"id": _id(), "kind": "load", "data": r})
        else:
            cards.append({"id": _id(), "kind": "info", "title": n, "text": r.get("say", "")})
    # newest first, and never more than five cards at once
    return cards[:5]
