"""Shared helpers: time handling, member lookup, serialisation, errors."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from family_conflicts import Appt, Person, Rule
from family_conflicts import fmt_time as _fmt_time
from sqlmodel import Session, select

from ..models import Event, EventAttendee, FamilyRule, Member

TZ = ZoneInfo(os.getenv("HEARTH_TZ", "Asia/Kolkata"))
UTC = timezone.utc

ALIASES = {
    "mom": "Mom", "mummy": "Mom", "mama": "Mom", "mother": "Mom", "mum": "Mom",
    "dad": "Dad", "papa": "Dad", "daddy": "Dad", "father": "Dad", "pappa": "Dad",
    "dadi": "Dadi", "grandma": "Dadi", "grandmother": "Dadi",
    "rohan": "Rohan",
}


class HearthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def now() -> datetime:
    """Aware UTC 'now'. HEARTH_NOW (ISO) pins the clock for demos and tests."""
    pinned = os.getenv("HEARTH_NOW")
    if pinned:
        return parse_dt(pinned)
    return datetime.now(UTC)


def parse_dt(value: str | datetime) -> datetime:
    """ISO string -> aware UTC. Naive values are read in the family timezone."""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            raise HearthError(
                "bad_date",
                f"I couldn't read '{value}' as a date and time. Which day and time did you mean?",
            )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(UTC)


def to_db(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


def from_db(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC)


def local_iso(dt: datetime) -> str:
    return dt.astimezone(TZ).isoformat()


def day_word(dt: datetime) -> str:
    d = dt.astimezone(TZ).date()
    today = now().astimezone(TZ).date()
    if d == today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    if 0 < (d - today).days < 7:
        return dt.astimezone(TZ).strftime("%A")
    return dt.astimezone(TZ).strftime("%a %d %b")


def say_when(dt: datetime) -> str:
    return f"{day_word(dt)} at {_fmt_time(dt, TZ)}"


def fmt_time(dt: datetime) -> str:
    return _fmt_time(dt, TZ)


def find_member(s: Session, ref: str | int) -> Member:
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        m = s.get(Member, int(ref))
        if m:
            return m
    else:
        name = ALIASES.get(ref.strip().lower(), ref.strip())
        m = s.exec(select(Member).where(Member.name == name)).first()
        if m:
            return m
        for cand in s.exec(select(Member)).all():
            if cand.name.lower() == name.lower():
                return cand
    names = ", ".join(x.name for x in s.exec(select(Member)).all())
    raise HearthError("unknown_member", f"I don't know a family member called {ref}. I know {names}.")


def members(s: Session) -> list[Member]:
    return list(s.exec(select(Member).order_by(Member.id)).all())


def load_people(s: Session) -> list[Person]:
    return [Person(m.id, m.name, m.role, m.is_adult) for m in members(s)]


def load_rules(s: Session) -> list[Rule]:
    out = []
    for r in s.exec(select(FamilyRule).where(FamilyRule.active)).all():
        params = json.loads(r.params_json or "{}")
        params["source_text"] = r.source_text
        out.append(Rule(r.id, r.member_id, r.kind, params))
    return out


def attendee_map(s: Session) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for row in s.exec(select(EventAttendee)).all():
        out.setdefault(row.event_id, []).append(row.member_id)
    return out


def load_appts(s: Session, statuses: tuple[str, ...] = ("active",)) -> list[Appt]:
    att = attendee_map(s)
    evs = s.exec(select(Event).where(Event.status.in_(statuses))).all()
    return [
        Appt(
            e.id, e.title, from_db(e.start_utc), from_db(e.end_utc),
            tuple(sorted(att.get(e.id, []))), e.needs_adult, e.movable, e.location,
        )
        for e in evs
    ]


def event_dict(s: Session, e: Event, att: dict[int, list[int]] | None = None) -> dict:
    att = att if att is not None else attendee_map(s)
    names = {m.id: m.name for m in members(s)}
    return {
        "id": e.id,
        "title": e.title,
        "start": local_iso(from_db(e.start_utc)),
        "end": local_iso(from_db(e.end_utc)),
        "attendees": [names[i] for i in sorted(att.get(e.id, [])) if i in names],
        "location": e.location,
        "needs_adult": e.needs_adult,
        "movable": e.movable,
        "created_by": names.get(e.created_by, "?"),
        "status": e.status,
    }


def conflicts_for(s: Session, event_ids: set[int] | None = None, window=None) -> list:
    from family_conflicts import detect

    appts = load_appts(s)
    found = detect(appts, load_people(s), load_rules(s), TZ)
    if event_ids is not None:
        found = [c for c in found if event_ids & set(c.event_ids)]
    if window:
        lo, hi = window
        by_id = {a.id: a for a in appts}
        found = [
            c for c in found
            if any(by_id[i].start < hi and lo < by_id[i].end for i in c.event_ids if i in by_id)
        ]
    return found


def conflict_dicts(conflicts: list) -> list[dict]:
    return [c.to_dict(TZ) for c in conflicts]


def dump(obj) -> str:
    return json.dumps(obj, default=str)
