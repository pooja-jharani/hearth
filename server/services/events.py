"""Events, conflicts, resolutions, pending actions and undo."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

from family_conflicts import detect, free_slots, suggest
from family_conflicts import fmt_time as ftime
from sqlmodel import Session, select

from ..models import Approval, AuditLog, Event, EventAttendee, PendingAction
from . import common as c
from .common import HearthError

PENDING_TTL_MIN = 15
DEFAULT_DURATION_MIN = 60


# ------------------------------------------------------------------ create

def _create_event(s: Session, title, start, end, duration_min, attendees, location, needs_adult, movable, created_by):
    creator = c.find_member(s, created_by)
    if not title or not str(title).strip():
        raise HearthError("missing_title", "What should I call the event?")
    start_dt = c.parse_dt(start)
    assumed = False
    if end:
        end_dt = c.parse_dt(end)
    else:
        if not duration_min:
            duration_min, assumed = DEFAULT_DURATION_MIN, True
        end_dt = start_dt + timedelta(minutes=int(duration_min))
    if end_dt <= start_dt:
        raise HearthError("bad_range", "The end time has to be after the start time. What end time did you mean?")
    people = [c.find_member(s, a) for a in (attendees or [creator.name])]
    ids = sorted({m.id for m in people})
    pending = not creator.is_adult
    ev = Event(
        title=str(title).strip(), start_utc=c.to_db(start_dt), end_utc=c.to_db(end_dt),
        location=location, needs_adult=bool(needs_adult), movable=bool(movable),
        created_by=creator.id, status="pending_approval" if pending else "active",
    )
    s.add(ev)
    s.flush()
    for i in ids:
        s.add(EventAttendee(event_id=ev.id, member_id=i))
    if pending:
        s.add(Approval(event_id=ev.id, requested_by=creator.id))
    return ev, creator, assumed, pending


def _audit(s: Session, action: str, before, after, actor):
    s.add(AuditLog(action=action, before_json=c.dump(before), after_json=c.dump(after), actor=actor))


def add_event(s: Session, title, start, end=None, duration_min=None, attendees=None, location=None,
              needs_adult=False, movable=True, created_by=None):
    if not created_by:
        raise HearthError("unknown_speaker", "Who is adding this event?")
    ev, creator, assumed, pending = _create_event(
        s, title, start, end, duration_min, attendees, location, needs_adult, movable, created_by)
    _audit(s, "add", None, {"event_ids": [ev.id]}, creator.id)
    s.commit()
    conflicts = [] if pending else c.conflicts_for(s, {ev.id})
    when = c.say_when(c.from_db(ev.start_utc))
    say = f"Added {ev.title} for {when}."
    if assumed:
        say = f"Added {ev.title} for {when}, for one hour."
    if pending:
        say = f"I've sent {ev.title} to a parent for approval."
    elif conflicts:
        say += f" Heads up: {conflicts[0].why}"
    return {
        "event": c.event_dict(s, ev), "conflicts": c.conflict_dicts(conflicts),
        "assumed_duration": assumed, "needs_approval": pending, "say": say,
    }


def add_events_bulk(s: Session, events: list[dict], created_by: str):
    if not events:
        raise HearthError("no_events", "I didn't catch any events. What should I add?")
    results, created = [], []
    for item in events:
        try:
            ev, creator, assumed, pending = _create_event(
                s, item.get("title"), item.get("start"), item.get("end"), item.get("duration_min"),
                item.get("attendees"), item.get("location"), item.get("needs_adult", False),
                item.get("movable", True), created_by)
            created.append(ev)
            results.append({"ok": True, "event_id": ev.id, "assumed_duration": assumed, "needs_approval": pending})
        except HearthError as err:
            results.append({"ok": False, "error": {"code": err.code, "message": err.message},
                            "title": item.get("title")})
    if created:
        _audit(s, "add_bulk", None, {"event_ids": [e.id for e in created]}, c.find_member(s, created_by).id)
    s.commit()
    ids = {e.id for e in created}
    att = c.attendee_map(s)
    by_id = {e.id: e for e in created}
    for r in results:
        if r["ok"]:
            r["event"] = c.event_dict(s, by_id[r["event_id"]], att)
    conflicts = c.conflicts_for(s, ids) if ids else []
    ok = len(created)
    bad = len(results) - ok
    say = f"Added {ok} event{'s' if ok != 1 else ''}."
    if bad:
        say += f" {bad} couldn't be added."
    if conflicts:
        say += f" {len(conflicts)} clash{'es' if len(conflicts) != 1 else ''}: {conflicts[0].why}"
    return {"results": results, "conflicts": c.conflict_dicts(conflicts), "say": say}


# -------------------------------------------------------------------- read

def _window(from_time, to_time):
    lo = c.parse_dt(from_time) if from_time else c.now()
    hi = c.parse_dt(to_time) if to_time else lo + timedelta(days=7)
    if hi <= lo:
        raise HearthError("bad_range", "The 'to' time has to be after the 'from' time.")
    return lo, hi


def list_events(s: Session, from_time=None, to_time=None, member=None):
    lo, hi = _window(from_time, to_time)
    mid = c.find_member(s, member).id if member else None
    att = c.attendee_map(s)
    rows = s.exec(select(Event).where(Event.status.in_(("active", "pending_approval")))
                  .where(Event.start_utc < c.to_db(hi)).where(Event.end_utc > c.to_db(lo))
                  .order_by(Event.start_utc)).all()
    if mid is not None:
        rows = [e for e in rows if mid in att.get(e.id, [])]
    evs = [c.event_dict(s, e, att) for e in rows]
    say = f"{len(evs)} event{'s' if len(evs) != 1 else ''}."
    if evs:
        first = rows[0]
        say += f" First: {first.title} {c.say_when(c.from_db(first.start_utc))}."
    return {"events": evs, "say": say}


def detect_conflicts(s: Session, from_time=None, to_time=None):
    lo, hi = _window(from_time, to_time)
    found = c.conflicts_for(s, window=(lo, hi))
    say = "No clashes." if not found else f"{len(found)} clash{'es' if len(found) != 1 else ''}. {found[0].why}"
    return {"conflicts": c.conflict_dicts(found), "say": say}


def find_free_slot(s: Session, attendees: list[str], duration_min: int, earliest=None, latest=None, needs_adult=False):
    ids = [c.find_member(s, a).id for a in attendees]
    lo = c.parse_dt(earliest) if earliest else c.now()
    hi = c.parse_dt(latest) if latest else lo + timedelta(days=2)
    slots = free_slots(c.load_appts(s), c.load_people(s), ids, int(duration_min), lo, hi, c.TZ,
                       needs_adult=bool(needs_adult), rules=c.load_rules(s))
    out = [{"start": c.local_iso(a), "end": c.local_iso(b)} for a, b in slots]
    if slots:
        say = "Free at " + ", ".join(c.say_when(a) for a, _ in slots) + "."
    else:
        say = "I couldn't find a free slot in that window."
    return {"slots": out, "say": say}


def suggest_resolutions(s: Session, conflict_id: str):
    appts, people, rules = c.load_appts(s), c.load_people(s), c.load_rules(s)
    conflict = next((x for x in detect(appts, people, rules, c.TZ) if x.id == conflict_id), None)
    if conflict is None:
        raise HearthError("conflict_not_found", "That clash is already sorted out.")
    options = suggest(conflict, appts, people, rules, c.TZ)
    parts = [f"{o.rank}. {o.label}" for o in options]
    say = "Here's what we can do. " + " ".join(f"Option {p}." for p in parts)
    return {"conflict": conflict.to_dict(c.TZ), "options": [o.to_dict(c.TZ) for o in options], "say": say}


# ------------------------------------------------------- pending + commit

def _event_or_error(s: Session, event_id: int) -> Event:
    ev = s.get(Event, int(event_id))
    if ev is None or ev.status == "cancelled":
        raise HearthError("event_not_found", "I can't find that event. Which one do you mean?")
    return ev


def _check_permission(s: Session, actor, ev: Event):
    if not actor:
        raise HearthError("unknown_speaker", "Who is asking for this change?")
    a = c.find_member(s, actor)
    owner = s.get(type(a), ev.created_by)
    if not a.is_adult and owner is not None and owner.is_adult:
        raise HearthError("permission", f"{a.name}, only a grown-up can change {ev.title}. I can ask one for you.")
    return a


def _new_pending(s: Session, kind: str, payload: dict, actor) -> PendingAction:
    pa = PendingAction(kind=kind, payload_json=c.dump(payload), actor=actor.id,
                       expires_at=c.to_db(c.now() + timedelta(minutes=PENDING_TTL_MIN)))
    s.add(pa)
    s.commit()
    return pa


def move_event(s: Session, event_id: int, actor: str, new_start=None, add_attendee=None, remove_attendee=None):
    ev = _event_or_error(s, event_id)
    a = _check_permission(s, actor, ev)
    att_before = sorted(c.attendee_map(s).get(ev.id, []))
    att_after = list(att_before)
    if remove_attendee:
        rid = c.find_member(s, remove_attendee).id
        att_after = [x for x in att_after if x != rid]
    if add_attendee:
        aid = c.find_member(s, add_attendee).id
        if aid not in att_after:
            att_after.append(aid)
    if not new_start and not add_attendee and not remove_attendee:
        raise HearthError("nothing_to_change", "What should I change: the time or who's going?")
    start_old, end_old = c.from_db(ev.start_utc), c.from_db(ev.end_utc)
    if new_start:
        ns = c.parse_dt(new_start)
        ne = ns + (end_old - start_old)
    else:
        ns, ne = start_old, end_old
    payload = {"event_id": ev.id, "new_start": ns.isoformat(), "new_end": ne.isoformat(),
               "attendees": sorted(att_after)}
    # hypothetical clash check for the preview
    appts = [x if x.id != ev.id else replace(x, start=ns, end=ne, attendees=tuple(sorted(att_after)))
             for x in c.load_appts(s)]
    base = {x.id for x in detect(c.load_appts(s), c.load_people(s), c.load_rules(s), c.TZ)}
    after = [x for x in detect(appts, c.load_people(s), c.load_rules(s), c.TZ) if x.id not in base]
    pa = _new_pending(s, "move", payload, a)
    names = {m.id: m.name for m in c.members(s)}
    parts = []
    if new_start:
        parts.append(f"move {ev.title} from {ftime(start_old, c.TZ)} to {ftime(ns, c.TZ)}")
    if remove_attendee or add_attendee:
        parts.append(f"change who's going to {', '.join(names[i] for i in att_after)}")
    say = f"Shall I {' and '.join(parts)}?"
    if after:
        say += f" Careful: {after[0].why}"
    return {
        "pending_action_id": pa.id,
        "preview": {
            "kind": "move", "event_id": ev.id, "title": ev.title,
            "from": c.local_iso(start_old), "to": c.local_iso(ns), "to_end": c.local_iso(ne),
            "attendees_before": [names[i] for i in att_before], "attendees_after": [names[i] for i in att_after],
            "new_conflicts": c.conflict_dicts(after),
        },
        "say": say + " Say yes to confirm.",
    }


def delete_event(s: Session, event_id: int, actor: str):
    ev = _event_or_error(s, event_id)
    a = _check_permission(s, actor, ev)
    pa = _new_pending(s, "delete", {"event_id": ev.id}, a)
    when = c.say_when(c.from_db(ev.start_utc))
    return {
        "pending_action_id": pa.id,
        "preview": {"kind": "delete", "event_id": ev.id, "title": ev.title, "from": c.local_iso(c.from_db(ev.start_utc))},
        "say": f"Shall I delete {ev.title} on {when}? Say yes to confirm.",
    }


def commit_action(s: Session, pending_action_id: int):
    pa = s.get(PendingAction, int(pending_action_id))
    if pa is None:
        raise HearthError("pending_not_found", "I don't have anything waiting to confirm.")
    if pa.used:
        raise HearthError("pending_used", "That change was already applied.")
    if pa.expires_at < c.to_db(c.now()):
        raise HearthError("pending_expired", "That request timed out. Ask me again and I'll redo it.")
    p = json.loads(pa.payload_json)
    ev = _event_or_error(s, p["event_id"])
    att = c.attendee_map(s)
    if pa.kind == "move":
        before = {"event_id": ev.id, "start": c.from_db(ev.start_utc).isoformat(),
                  "end": c.from_db(ev.end_utc).isoformat(), "attendees": sorted(att.get(ev.id, []))}
        ev.start_utc = c.to_db(c.parse_dt(p["new_start"]))
        ev.end_utc = c.to_db(c.parse_dt(p["new_end"]))
        for row in s.exec(select(EventAttendee).where(EventAttendee.event_id == ev.id)).all():
            s.delete(row)
        s.flush()
        for i in p["attendees"]:
            s.add(EventAttendee(event_id=ev.id, member_id=i))
        after = {"event_id": ev.id, "start": p["new_start"], "end": p["new_end"], "attendees": p["attendees"]}
        _audit(s, "move", before, after, pa.actor)
        say_done = f"Done. {ev.title} is now {c.say_when(c.from_db(ev.start_utc))}."
    else:
        before = {"event_id": ev.id, "status": ev.status}
        ev.status = "cancelled"
        _audit(s, "delete", before, {"event_id": ev.id, "status": "cancelled"}, pa.actor)
        say_done = f"Done. {ev.title} is deleted."
    pa.used = True
    s.add(ev)
    s.add(pa)
    s.commit()
    conflicts = c.conflicts_for(s, {ev.id}) if ev.status == "active" else []
    say = say_done + (" No clashes left." if not conflicts else f" Still a clash: {conflicts[0].why}")
    return {"result": {"kind": pa.kind, "event": c.event_dict(s, ev)},
            "conflicts_after": c.conflict_dicts(conflicts), "undo_available": True, "say": say}


def undo_last(s: Session, actor: str | None = None):
    row = s.exec(select(AuditLog).where(AuditLog.undone == False)  # noqa: E712
                 .order_by(AuditLog.id.desc())).first()
    if row is None:
        raise HearthError("nothing_to_undo", "There's nothing to undo.")
    before, after = json.loads(row.before_json), json.loads(row.after_json)
    title = ""
    if row.action in ("add", "add_bulk"):
        for eid in after["event_ids"]:
            ev = s.get(Event, eid)
            if ev:
                ev.status = "cancelled"
                title = title or ev.title
                s.add(ev)
                ap = s.get(Approval, eid)
                if ap:
                    s.delete(ap)
        say = f"Undone. I removed {title}." if row.action == "add" else "Undone. I removed those events."
    elif row.action == "move":
        ev = s.get(Event, before["event_id"])
        ev.start_utc = c.to_db(c.parse_dt(before["start"]))
        ev.end_utc = c.to_db(c.parse_dt(before["end"]))
        for r in s.exec(select(EventAttendee).where(EventAttendee.event_id == ev.id)).all():
            s.delete(r)
        s.flush()
        for i in before["attendees"]:
            s.add(EventAttendee(event_id=ev.id, member_id=i))
        s.add(ev)
        say = f"Undone. {ev.title} is back to {c.say_when(c.from_db(ev.start_utc))}."
    elif row.action == "delete":
        ev = s.get(Event, before["event_id"])
        ev.status = before["status"]
        s.add(ev)
        say = f"Undone. {ev.title} is back."
    else:
        raise HearthError("cannot_undo", "I can't undo that one.")
    row.undone = True
    s.add(row)
    s.commit()
    return {"undone": row.action, "say": say}


# --------------------------------------------------------------- approvals

def list_pending_approvals(s: Session):
    rows = s.exec(select(Approval).where(Approval.status == "pending")).all()
    evs = []
    att = c.attendee_map(s)
    for ap in rows:
        ev = s.get(Event, ap.event_id)
        if ev and ev.status == "pending_approval":
            evs.append(c.event_dict(s, ev, att))
    say = "Nothing is waiting for approval." if not evs else \
        f"{len(evs)} waiting: " + "; ".join(f"{e['title']} from {e['created_by']}" for e in evs) + "."
    return {"events": evs, "say": say}


def approve_event(s: Session, event_id: int, actor: str):
    a = c.find_member(s, actor)
    if not a.is_adult:
        raise HearthError("permission", f"{a.name}, only a grown-up can approve events.")
    ev = s.get(Event, int(event_id))
    ap = s.get(Approval, int(event_id))
    if ev is None or ap is None or ev.status != "pending_approval":
        raise HearthError("not_pending", "That event isn't waiting for approval.")
    ev.status = "active"
    ap.status, ap.decided_by = "approved", a.id
    s.add(ev)
    s.add(ap)
    s.commit()
    conflicts = c.conflicts_for(s, {ev.id})
    say = f"Approved {ev.title}."
    if conflicts:
        say += f" Note: {conflicts[0].why}"
    return {"event": c.event_dict(s, ev), "conflicts": c.conflict_dicts(conflicts), "say": say}
