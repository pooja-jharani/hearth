"""Scripted 'model' for MOCK mode: maps an utterance to MCP tool calls, then speaks the tool's own `say`.

It makes the same kinds of tool calls a real model would, through the same MCP backend, so the UI,
cards, confirm flow, Undo and tests all run without any AWS account.
"""
from __future__ import annotations

import re
from datetime import timedelta

from . import nlu
from .types import ToolEvent

KID_OK_WORDS = ("dish", "plant", "toy", "room", "bed", "shoe", "table", "book", "laundry basket")
EFFORT = {"dish": 2, "laundry": 3, "grocer": 4, "bin": 1, "trash": 1, "cook": 3, "clean": 3, "plant": 1,
          "vacuum": 3, "tidy": 2, "toy": 1}
STOP = {"the", "a", "an", "my", "our", "to", "of", "it", "this", "that", "event", "move", "shift", "push", "delete",
        "remove", "cancel", "reschedule", "please"}


class MockPolicy:
    def __init__(self, backend, now, tz):
        self.b, self.now, self.tz = backend, now, tz

    # -- helpers -----------------------------------------------------------
    def _call(self, events: list[ToolEvent], name: str, args: dict) -> dict:
        result = self.b.call(name, args)
        events.append(ToolEvent(name, {k: v for k, v in args.items() if v is not None}, result))
        return result

    def _today(self):
        return self.now().astimezone(self.tz).date()

    def _find_event(self, events, text: str, state: dict) -> dict | None:
        lo = self.now().astimezone(self.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        res = self._call(events, "list_events", {"from_time": lo.isoformat(),
                                                 "to_time": (lo + timedelta(days=21)).isoformat()})
        words = [w for w in re.findall(r"[a-z']+", text.lower()) if w not in STOP and len(w) > 2
                 and w not in nlu.NAME_WORDS and w not in nlu.WEEKDAYS]
        day, _ = nlu.extract_day(text, self._today())
        best, score = None, 0
        for e in res.get("events", []):
            sc = sum(1 for w in words if w.rstrip("s") in e["title"].lower())
            if day and e["start"][:10] == day.isoformat():
                sc += 1
            if sc > score:
                best, score = e, sc
        return best

    # -- main entry --------------------------------------------------------
    def respond(self, speaker: str, text: str, state: dict) -> tuple[str, list[ToolEvent]]:
        ev: list[ToolEvent] = []
        low = text.lower().strip()
        today = self._today()

        def done(msg: str | None = None):
            last = ev[-1].result if ev else {}
            return msg or last.get("say") or "Done.", ev

        # confirmations: a pending change first, otherwise a request someone asked this speaker
        if re.fullmatch(r"(yes|yep|yeah|sure|ok|okay|confirm|do it|go ahead|yes please|please do|sounds good|i will|i'll go|i can)[.! ]*", low):
            if state.get("pending_id"):
                self._call(ev, "commit_action", {"pending_action_id": state["pending_id"]})
                return done()
            reqs = self.b.call("list_pending_approvals", {"member": speaker}).get("requests", [])
            if reqs:
                self._call(ev, "respond_request", {"request_id": reqs[0]["id"], "actor": speaker, "accept": True})
                return done()
            return "There's nothing waiting for a yes right now.", ev
        if re.fullmatch(r"(no|nope|cancel|never ?mind|leave it|keep it|i can'?t( make it| go| come)?|sorry,? (no|i can'?t)|can'?t make it)[.! ]*", low):
            if state.get("pending_id"):
                state["pending_id"] = None
                return "Okay, I've left everything as it was.", ev
            reqs = self.b.call("list_pending_approvals", {"member": speaker}).get("requests", [])
            if reqs and not low.startswith(("cancel", "never", "leave", "keep")):
                self._call(ev, "respond_request", {"request_id": reqs[0]["id"], "actor": speaker, "accept": False})
                return done()
            state["pending_id"] = None
            return "Okay, I've left everything as it was.", ev
        if re.match(r"(undo|take that back|revert)", low):
            self._call(ev, "undo_last", {"actor": speaker})
            return done()

        # choose one of the options just offered
        m = re.match(r"(?:do |pick |take |go with |choose )?(?:option |number |#)?(1|2|3|first|second|third|one|two)\b", low)
        if m and state.get("options"):
            idx = {"1": 0, "one": 0, "first": 0, "2": 1, "two": 1, "second": 1, "3": 2, "third": 2}[m.group(1)]
            opts = state["options"]
            if idx < len(opts):
                return self.apply_option(speaker, opts[idx], ev)

        # rules
        rule = nlu.parse_rule(text)
        if rule:
            self._call(ev, "add_rule", rule)
            return done()
        if re.search(r"\b(what are|show|list)\b.*\brules?\b|\bfamily rules\b", low):
            self._call(ev, "list_rules", {})
            return done()
        m = re.search(r"\b(?:forget|remove|delete|drop)\b.*\brule\b(?:.*about\s+(.+))?", low)
        if m:
            rules = self._call(ev, "list_rules", {}).get("rules", [])
            key = (m.group(1) or "").strip()
            hit = next((r for r in rules if key and key in (r["source_text"] + r["description"]).lower()), None) \
                or (rules[-1] if rules else None)
            if hit:
                self._call(ev, "remove_rule", {"rule_id": hit["id"]})
                return done()
            return "There are no rules to remove.", ev

        # conflicts and fixes
        if re.search(r"what can we do|what are (?:my|our) options|how (?:do|can) we fix|any (?:ideas|options)|fix (?:it|this)|suggest", low):
            cid = state.get("conflict_id")
            if not cid:
                found = self._call(ev, "detect_conflicts", {})
                cs = found.get("conflicts", [])
                if not cs:
                    return "There's nothing to fix. No clashes right now.", ev
                cid = cs[0]["id"]
            self._call(ev, "suggest_resolutions", {"conflict_id": cid})
            return done()

        # approvals
        if re.search(r"waiting for approval|pending approval|approval inbox|\binbox\b|what needs approving", low):
            self._call(ev, "list_pending_approvals", {})
            return done()
        if re.match(r"approve\b", low):
            pend = self._call(ev, "list_pending_approvals", {}).get("events", [])
            hit = next((p for p in pend if any(w in p["title"].lower() for w in re.findall(r"[a-z]{4,}", low[7:]))), None) \
                or (pend[0] if pend else None)
            if not hit:
                return "Nothing is waiting for approval.", ev
            self._call(ev, "approve_event", {"event_id": hit["id"], "actor": speaker})
            return done()

        # reading
        if re.search(r"\b(week ?guard|any risks?|risks?\b|check (?:the )?(?:next )?week|anything to worry|what could go wrong|watch out)", low):
            self._call(ev, "week_guard", {"days": 7})
            return done()
        if re.search(r"planning load|mental load|who (?:does|is doing) (?:the )?(?:most )?planning|who plans", low):
            self._call(ev, "planning_load", {"days": 14})
            return done()
        if re.search(r"what'?s (?:happening|on|going on|coming up)|what is (?:happening|on)|summary|this week|next week|my week|our week|today|tomorrow", low) \
                and not re.search(r"\b(add|have|move|delete|remove|cancel)\b", low) \
                and (text.strip().endswith("?") or re.match(r"(what|show|tell|any|summary)", low)):
            rng = "next_week" if "next week" in low else "tomorrow" if "tomorrow" in low else \
                "today" if re.search(r"\btoday\b", low) else "week"
            self._call(ev, "family_summary", {"range": rng})
            return done()

        # chores
        m = re.search(r"who (?:should|can|will|is going to|'s going to)\s+(?:do|take|handle|clean|wash)\s+(?:the\s+)?(.+?)[?.! ]*$", low)
        if m or re.match(r"assign\b.*\bchore\b", low):
            title = (m.group(1) if m else re.sub(r"assign|the|chore|a|to\s+\w+", "", low)).strip() or "chore"
            effort = next((v for k, v in EFFORT.items() if k in title), 2)
            self._call(ev, "assign_chore", {"title": title[:1].upper() + title[1:], "effort": effort,
                                            "kid_ok": any(k in title for k in KID_OK_WORDS)})
            return done()
        if re.search(r"\b(show|list|what are|what)\b.*\bchores?\b", low):
            self._call(ev, "list_chores", {"status": "open"})
            return done()
        m = re.search(r"\b(?:i|we|he|she|\w+)\s+(?:finished|did|completed|done with)\s+(?:the\s+)?(.+?)[.! ]*$|^(?:the\s+)?(.+?)\s+is done", low)
        if m and not re.search(r"\d", low):
            what = (m.group(1) or m.group(2)).strip()
            chores = self._call(ev, "list_chores", {"status": "open"}).get("chores", [])
            hit = next((c for c in chores if what.rstrip("s") in c["title"].lower()), None)
            if hit:
                self._call(ev, "complete_chore", {"chore_id": hit["id"]})
                return done()

        # free time
        if re.search(r"\bwho(?:'s| is) free\b|\bfind (?:a )?(?:free )?(?:slot|time)\b|\bwhen (?:are|is) .* free\b|\bfree (?:slot|time)\b", low):
            names = nlu.mentioned_members(text) or ["Mom", "Dad"]
            dur = 60
            dm = re.search(r"(\d+)\s*(hour|hr|h|min)", low)
            if dm:
                dur = int(dm.group(1)) * (60 if dm.group(2).startswith("h") else 1)
            day, _ = nlu.extract_day(text, today)
            day = day or today
            self._call(ev, "find_free_slot", {
                "attendees": names, "duration_min": dur, "needs_adult": False,
                "earliest": nlu.at_time(day, (8, 0)), "latest": nlu.at_time(day, (21, 0))})
            return done()

        # circular import
        if low.startswith("circular") or "school circular" in low[:40]:
            items = nlu.extract_circular(text, today, speaker)
            if not items:
                return "I couldn't find any dated items in that circular. Try pasting the lines with dates.", ev
            self._call(ev, "add_events_bulk", {"events": [{k: v for k, v in i.items() if k != "created_by"} for i in items],
                                               "created_by": speaker})
            return done()

        # move / change who's going / delete
        m = re.match(r"(?:please )?(?:move|shift|push|reschedule)\s+(.+?)\s+(?:to|till|until|for)\s+(.+)$", low)
        if m:
            target = self._find_event(ev, m.group(1), state) or state.get("last_event")
            if not target:
                return "Which event do you want to move?", ev
            new_text = m.group(2)
            day, rest = nlu.extract_day(new_text, today)
            start, _, _ = nlu.extract_time(rest if rest.strip() else new_text)
            if start is None:
                start = nlu.bare_hour(rest)
            if start is None:
                return "What time should I move it to?", ev
            base_day = day or __import__("datetime").date.fromisoformat(target["start"][:10])
            self._call(ev, "move_event", {"event_id": target["id"], "new_start": nlu.at_time(base_day, start),
                                          "actor": speaker})
            return done()
        m = re.search(r"(?:ask|get|let)\s+(\w+)\s+(?:to\s+)?(?:attend|go to|take|cover|do|handle)\s+(?:the\s+)?(.+)$", low)
        if m and m.group(1) in nlu.NAME_WORDS:
            target = self._find_event(ev, m.group(2), state)
            if not target:
                return "Which event should they attend?", ev
            self._call(ev, "ask_member", {"event_id": target["id"], "member": nlu.NAME_WORDS[m.group(1)],
                                          "actor": speaker})
            return done()
        m = re.match(r"(?:please )?(?:delete|remove|cancel)\s+(?:the\s+)?(.+)$", low)
        if m:
            target = self._find_event(ev, m.group(1), state)
            if not target:
                return "I can't find that event. Which one do you mean?", ev
            self._call(ev, "delete_event", {"event_id": target["id"], "actor": speaker})
            return done()

        # adding events
        if nlu.count_dated_segments(text, today) >= 2:
            items = nlu.parse_bulk(text, speaker, today)
            if len(items) >= 2:
                self._call(ev, "add_events_bulk", {"events": [{k: v for k, v in i.items() if k != "created_by"} for i in items],
                                                   "created_by": speaker})
                return done()
        args = nlu.parse_event(text, speaker, today)
        if args:
            self._call(ev, "add_event", args)
            return done()
        return ("I didn't quite catch that. Try something like \"Rohan's PTM is Thursday at 5 at school\" "
                "or \"What's happening this week?\""), ev

    def apply_option(self, speaker: str, opt: dict, ev: list[ToolEvent]):
        if opt["kind"] == "keep":
            return "Okay, I'll keep things as they are. The clash stays flagged.", ev
        if opt["kind"] == "add_attendee":  # a person gets asked; nothing changes until they answer
            result = self._call(ev, "ask_member", {"event_id": opt["event_id"], "member": opt["add_member"],
                                                   "actor": speaker})
            return result.get("say", "Done."), ev
        args = {"event_id": opt["event_id"], "actor": speaker}
        if opt.get("new_start"):
            args["new_start"] = opt["new_start"]
        if opt.get("add_member") is not None:
            args["add_attendee"] = opt["add_member"]
        if opt.get("remove_member") is not None:
            args["remove_attendee"] = opt["remove_member"]
        result = self._call(ev, "move_event", args)
        return result.get("say", "Done."), ev
