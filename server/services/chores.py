"""Chores with a transparent fairness score."""
from __future__ import annotations

from datetime import timedelta

from sqlmodel import Session, select

from ..models import Chore, Member
from . import common as c
from .common import HearthError

WINDOW_DAYS = 14


def chore_dict(s: Session, ch: Chore) -> dict:
    names = {m.id: m.name for m in c.members(s)}
    return {
        "id": ch.id, "title": ch.title, "effort": ch.effort, "kid_ok": ch.kid_ok,
        "due": ch.due_date.isoformat() if ch.due_date else None,
        "assigned_to": names.get(ch.assigned_to), "status": ch.status,
    }


def scores(s: Session) -> dict[int, int]:
    """Effort points assigned in the last 14 days (done or not), per member."""
    cutoff = c.to_db(c.now() - timedelta(days=WINDOW_DAYS))
    out = {m.id: 0 for m in c.members(s)}
    for ch in s.exec(select(Chore)).all():
        if ch.assigned_to in out and ch.assigned_at and ch.assigned_at >= cutoff:
            out[ch.assigned_to] += ch.effort
    return out


def _last_assigned(s: Session) -> dict[int, object]:
    last: dict[int, object] = {}
    for ch in s.exec(select(Chore)).all():
        if ch.assigned_to and ch.assigned_at and (ch.assigned_to not in last or ch.assigned_at > last[ch.assigned_to]):
            last[ch.assigned_to] = ch.assigned_at
    return last


def pick_assignee(s: Session, kid_ok: bool) -> tuple[Member, str]:
    sc, last = scores(s), _last_assigned(s)
    eligible = [m for m in c.members(s) if m.is_adult or kid_ok]
    if not eligible:
        raise HearthError("nobody_eligible", "Nobody is eligible for that chore.")
    from datetime import datetime
    never = datetime.min
    eligible.sort(key=lambda m: (sc[m.id], last.get(m.id, never), m.id))
    pick = eligible[0]
    others = [f"{m.name} {sc[m.id]}" for m in eligible[1:]]
    reason = f"{pick.name} has the lightest load: {sc[pick.id]} points in the last {WINDOW_DAYS} days"
    if others:
        reason += f" (vs {', '.join(others)})"
    if len(eligible) > 1 and sc[eligible[1].id] == sc[pick.id]:
        reason += "; tied, so it goes to whoever did a chore least recently"
    return pick, reason + "."


def assign_chore(s: Session, title: str, effort: int = 2, kid_ok: bool = False, due: str | None = None,
                 assign_to: str | None = None):
    if not title or not title.strip():
        raise HearthError("missing_title", "Which chore?")
    effort = max(1, min(5, int(effort)))
    due_date = None
    if due:
        due_date = c.parse_dt(due).astimezone(c.TZ).date()
    if assign_to:
        pick = c.find_member(s, assign_to)
        if not pick.is_adult and not kid_ok:
            raise HearthError("not_kid_ok", f"{pick.name} can't be given {title}; it isn't marked kid-friendly.")
        reason = f"You asked for {pick.name}."
    else:
        pick, reason = pick_assignee(s, bool(kid_ok))
    ch = Chore(title=title.strip(), effort=effort, kid_ok=bool(kid_ok), due_date=due_date,
               assigned_to=pick.id, assigned_at=c.to_db(c.now()))
    s.add(ch)
    s.commit()
    return {"chore": chore_dict(s, ch), "reason": reason, "say": f"{pick.name} takes {ch.title}. {reason}"}


def complete_chore(s: Session, chore_id: int):
    ch = s.get(Chore, int(chore_id))
    if ch is None:
        raise HearthError("chore_not_found", "I can't find that chore.")
    if ch.status == "done":
        raise HearthError("already_done", f"{ch.title} is already marked done.")
    ch.status, ch.completed_at = "done", c.to_db(c.now())
    s.add(ch)
    s.commit()
    who = s.get(Member, ch.assigned_to).name if ch.assigned_to else "Someone"
    return {"chore": chore_dict(s, ch), "say": f"Nice, {who} finished {ch.title}."}


def list_chores(s: Session, member: str | None = None, status: str | None = None):
    q = select(Chore)
    if member:
        q = q.where(Chore.assigned_to == c.find_member(s, member).id)
    if status:
        q = q.where(Chore.status == status)
    rows = s.exec(q.order_by(Chore.id.desc())).all()
    sc = scores(s)
    names = {m.id: m.name for m in c.members(s)}
    open_n = sum(1 for r in rows if r.status == "open")
    return {"chores": [chore_dict(s, r) for r in rows],
            "scores": {names[i]: v for i, v in sc.items()},
            "say": f"{open_n} open chore{'s' if open_n != 1 else ''}."}
