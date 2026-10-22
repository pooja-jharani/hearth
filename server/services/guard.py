"""Summaries, the proactive Week Guard and the planning-load report."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from family_conflicts import parents_free_for
from sqlmodel import Session, select

from ..models import Approval, Chore, Event
from . import chores as chore_svc
from . import common as c
from .common import HearthError

SEV = {"high": 0, "medium": 1, "low": 2}


def _local_midnight(dt: datetime) -> datetime:
    local = dt.astimezone(c.TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _range(rng: str) -> tuple[datetime, datetime, str]:
    today = _local_midnight(c.now())
    rng = (rng or "week").lower()
    if rng == "today":
        return today, today + timedelta(days=1), "Today"
    if rng == "tomorrow":
        return today + timedelta(days=1), today + timedelta(days=2), "Tomorrow"
    if rng == "next_week":
        monday = today + timedelta(days=(7 - today.weekday()))
        return monday, monday + timedelta(days=7), "Next week"
    if rng == "week":
        return today, today + timedelta(days=7), "This week"
    raise HearthError("bad_range", "Range must be today, tomorrow, week or next_week.")


def family_summary(s: Session, range: str = "week"):
    lo, hi, label = _range(range)
    lo_u, hi_u = lo.astimezone(c.UTC), hi.astimezone(c.UTC)
    rows = s.exec(select(Event).where(Event.status == "active")
                  .where(Event.start_utc < c.to_db(hi_u)).where(Event.end_utc > c.to_db(lo_u))
                  .order_by(Event.start_utc)).all()
    now_u = c.to_db(c.now())
    upcoming = [e for e in rows if e.end_utc > now_u]
    conflicts = c.conflicts_for(s, window=(lo_u, hi_u))
    pending = s.exec(select(Approval).where(Approval.status == "pending")).all()
    open_chores = s.exec(select(Chore).where(Chore.status == "open")).all()
    highlights = [
        f"{c.day_word(c.from_db(e.start_utc)).capitalize()} {c.fmt_time(c.from_db(e.start_utc))}: {e.title}"
        for e in upcoming[:4]
    ]
    say = f"{label}: {len(rows)} event{'s' if len(rows) != 1 else ''}, {len(conflicts)} clash{'es' if len(conflicts) != 1 else ''}."
    if highlights:
        say += f" Next up: {highlights[0]}."
    if conflicts:
        say += f" {conflicts[0].why}"
    return {
        "range": range, "label": label,
        "counts": {"events": len(rows), "conflicts": len(conflicts), "pending_approvals": len(pending),
                   "open_chores": len(open_chores)},
        "highlights": highlights, "conflicts": c.conflict_dicts(conflicts), "say": say,
    }


def week_guard(s: Session, days: int = 7):
    days = max(1, min(30, int(days)))
    lo = c.now()
    hi = lo + timedelta(days=days)
    appts = c.load_appts(s)
    people = c.load_people(s)
    names = {p.id: p.name for p in people}
    window = [a for a in appts if a.start < hi and a.end > lo]
    risks: list[dict] = []

    conflicts = c.conflicts_for(s, window=(lo, hi))
    clash_events: set[int] = set()
    for x in conflicts:
        clash_events.update(x.event_ids)
        risks.append({"type": x.type, "severity": x.severity, "why": x.why, "event_ids": list(x.event_ids),
                      "day": c.day_word(x.start) if x.start else None, "conflict_id": x.id})

    for a in window:
        if a.needs_adult and a.id not in clash_events:
            adults_attending = [i for i in a.attendees if i in names and next(p for p in people if p.id == i).is_adult]
            if adults_attending:
                continue
            free = parents_free_for(a, appts, people)
            if len(free) == 1:
                risks.append({
                    "type": "THIN_COVERAGE", "severity": "low", "event_ids": [a.id], "day": c.day_word(a.start),
                    "why": f"Only {free[0].name} is free for {a.title} {c.say_when(a.start)}, "
                           f"so {free[0].name} can't take other plans then.",
                })

    per_day: dict[tuple[int, str], list[int]] = defaultdict(list)
    for a in window:
        for pid in a.attendees:
            per_day[(pid, a.start.astimezone(c.TZ).date().isoformat())].append(a.id)
    for (pid, day), ids in per_day.items():
        if len(ids) >= 4:
            d = datetime.fromisoformat(day).replace(tzinfo=c.TZ)
            risks.append({"type": "OVERLOADED_DAY", "severity": "medium", "event_ids": ids,
                          "day": c.day_word(d),
                          "why": f"{names.get(pid, 'Someone')} has {len(ids)} things planned {c.day_word(d)}."})

    today = c.now().astimezone(c.TZ).date()
    for ch in s.exec(select(Chore).where(Chore.status == "open")).all():
        if ch.due_date and ch.due_date < today:
            who = names.get(ch.assigned_to, "Nobody")
            risks.append({"type": "OVERDUE_CHORE", "severity": "low", "event_ids": [],
                          "day": ch.due_date.strftime("%a %d %b"),
                          "why": f"{ch.title} was due {ch.due_date.strftime('%A')} and {who} hasn't finished it."})

    risks.sort(key=lambda r: SEV.get(r["severity"], 9))
    if not risks:
        say = f"The next {days} days look clear. No clashes or risks."
    else:
        say = f"I found {len(risks)} risk{'s' if len(risks) != 1 else ''} in the next {days} days. First: {risks[0]['why']}"
    return {"days": days, "risks": risks, "say": say}


def planning_load(s: Session, days: int = 14):
    days = max(1, min(60, int(days)))
    lo = _local_midnight(c.now()).astimezone(c.UTC)
    hi = lo + timedelta(days=days)
    appts = c.load_appts(s)
    rows = {e.id: e for e in s.exec(select(Event).where(Event.status == "active")).all()}
    people = c.load_people(s)
    stats = {p.id: {"member": p.name, "events": 0, "hours": 0.0, "organised": 0, "chore_points": 0} for p in people}
    for a in appts:
        if a.start >= hi or a.end <= lo:
            continue
        for pid in a.attendees:
            if pid in stats:
                stats[pid]["events"] += 1
                stats[pid]["hours"] += (a.end - a.start).total_seconds() / 3600
        creator = rows[a.id].created_by
        if creator in stats:
            stats[creator]["organised"] += 1
    for pid, pts in chore_svc.scores(s).items():
        stats[pid]["chore_points"] = pts
    out = []
    for st in stats.values():
        st["hours"] = round(st["hours"], 1)
        out.append(st)
    total_org = sum(x["organised"] for x in out)
    top = max(out, key=lambda x: x["organised"]) if out else None
    say = f"Planning load for the next {days} days."
    if top and total_org:
        share = round(100 * top["organised"] / total_org)
        say += f" {top['member']} organised {share}% of the plans."
    return {"days": days, "per_member": out, "say": say}
