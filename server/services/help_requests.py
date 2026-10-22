"""Ask-a-person requests: the fix for a coverage clash is a question to a real person, who can say yes or no."""
from __future__ import annotations

from sqlmodel import Session, select

from ..models import Event, EventAttendee, HelpRequest
from . import common as c
from . import events as ev_svc
from .common import HearthError


def request_dict(s: Session, r: HelpRequest) -> dict:
    names = {m.id: m.name for m in c.members(s)}
    ev = s.get(Event, r.event_id)
    return {
        "id": r.id, "status": r.status, "from": names.get(r.from_member), "to": names.get(r.to_member),
        "event": c.event_dict(s, ev) if ev else None,
    }


def ask_member(s: Session, event_id: int, member: str, actor: str):
    ev = ev_svc._event_or_error(s, event_id)
    asker = ev_svc._check_permission(s, actor, ev)
    target = c.find_member(s, member)
    if target.id == asker.id:
        raise HearthError("self_request", "You can just add yourself. Who else should I ask?")
    attending = c.attendee_map(s).get(ev.id, [])
    if target.id in attending:
        raise HearthError("already_attending", f"{target.name} is already going to {ev.title}.")
    open_req = s.exec(select(HelpRequest).where(HelpRequest.event_id == ev.id, HelpRequest.to_member == target.id,
                                                HelpRequest.status == "pending")).first()
    if open_req:
        raise HearthError("already_asked", f"I've already asked {target.name} about {ev.title}. Still waiting for a reply.")
    r = HelpRequest(event_id=ev.id, from_member=asker.id, to_member=target.id)
    s.add(r)
    s.commit()
    when = c.say_when(c.from_db(ev.start_utc))
    return {"request": request_dict(s, r),
            "say": f"I've asked {target.name} to come to {ev.title} {when}. It's in their inbox now."}


def respond_request(s: Session, request_id: int, actor: str, accept: bool):
    r = s.get(HelpRequest, int(request_id))
    if r is None:
        raise HearthError("request_not_found", "I can't find that request.")
    who = c.find_member(s, actor)
    if who.id != r.to_member:
        target = c.find_member(s, r.to_member)
        raise HearthError("permission", f"That request is for {target.name}, so only {target.name} can answer it.")
    if r.status != "pending":
        raise HearthError("already_answered", "That request was already answered.")
    ev = s.get(Event, r.event_id)
    if ev is None or ev.status == "cancelled":
        raise HearthError("event_not_found", "That event isn't on the calendar any more.")
    asker = c.find_member(s, r.from_member)
    r.decided_at = c.to_db(c.now())
    if not accept:
        r.status = "declined"
        s.add(r)
        s.commit()
        left = c.conflicts_for(s, {ev.id}) if ev.status == "active" else []
        say = f"Okay, I'll tell {asker.name} that {who.name} can't make {ev.title}."
        if left:
            say += f" The clash is still there: {left[0].why}"
        return {"request": request_dict(s, r), "conflicts_after": c.conflict_dicts(left), "undo_available": False,
                "say": say}
    att = sorted(c.attendee_map(s).get(ev.id, []))
    before = {"event_id": ev.id, "start": c.from_db(ev.start_utc).isoformat(),
              "end": c.from_db(ev.end_utc).isoformat(), "attendees": att}
    after_att = sorted(set(att) | {who.id})
    s.add(EventAttendee(event_id=ev.id, member_id=who.id))
    r.status = "accepted"
    s.add(r)
    ev_svc._audit(s, "move", before, {**before, "attendees": after_att}, who.id)
    s.commit()
    left = c.conflicts_for(s, {ev.id}) if ev.status == "active" else []
    say = f"Thanks {who.name}, you're going to {ev.title} {c.say_when(c.from_db(ev.start_utc))}."
    say += " No clashes left." if not left else f" Still a clash: {left[0].why}"
    return {"request": request_dict(s, r), "result": {"kind": "accept", "event": c.event_dict(s, ev)},
            "conflicts_after": c.conflict_dicts(left), "undo_available": True, "say": say}


def inbox(s: Session, member: str | None = None):
    """Child events awaiting approval, plus requests waiting for an answer (optionally for one person)."""
    base = ev_svc.list_pending_approvals(s)
    q = select(HelpRequest).where(HelpRequest.status == "pending")
    if member:
        q = q.where(HelpRequest.to_member == c.find_member(s, member).id)
    reqs = [request_dict(s, r) for r in s.exec(q.order_by(HelpRequest.id)).all()]
    parts = []
    if base["events"]:
        parts.append(f"{len(base['events'])} event{'s' if len(base['events']) != 1 else ''} waiting for approval")
    if reqs:
        first = reqs[0]
        parts.append(f"{len(reqs)} request{'s' if len(reqs) != 1 else ''}, first from {first['from']} "
                     f"about {first['event']['title']}")
    say = "Nothing is waiting." if not parts else "; ".join(parts).capitalize() + "."
    return {"events": base["events"], "requests": reqs, "say": say}
