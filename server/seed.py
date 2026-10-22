"""Seed the demo family. Run: python -m server.seed [--reset]

Events are placed relative to the current week (or HEARTH_NOW), so the demo works any week.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from sqlmodel import select

from . import db
from .models import Chore, Event, EventAttendee, Member
from .services import common as c

MEMBERS = [
    ("Mom", "parent", True, "#0F766E", "M"),
    ("Dad", "parent", True, "#B45309", "D"),
    ("Rohan", "child", False, "#4F46E5", "R"),
    ("Dadi", "grandparent", True, "#9D174D", "Da"),
]


def _next_weekday(base: datetime, weekday: int) -> datetime:
    """Local midnight of the next given weekday on or after tomorrow (Mon=0)."""
    d = base.astimezone(c.TZ).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


def seed(reset: bool = False, now: datetime | None = None) -> dict:
    db.init(reset=reset)
    now = now or c.now()
    with db.session() as s:
        if s.exec(select(Member)).first():
            return {"seeded": False}
        for name, role, adult, color, initials in MEMBERS:
            s.add(Member(name=name, role=role, is_adult=adult, color=color, initials=initials))
        s.commit()
        m = {x.name: x.id for x in s.exec(select(Member)).all()}

        def ev(title, day, sh, eh, who, creator, loc=None, needs_adult=False, movable=True, sm=0, em=0):
            start = day.replace(hour=sh, minute=sm)
            end = day.replace(hour=eh, minute=em)
            e = Event(title=title, start_utc=c.to_db(start), end_utc=c.to_db(end), location=loc,
                      needs_adult=needs_adult, movable=movable, created_by=m[creator])
            s.add(e)
            s.flush()
            for w in who:
                s.add(EventAttendee(event_id=e.id, member_id=m[w]))

        wed, thu, fri = _next_weekday(now, 2), _next_weekday(now, 3), _next_weekday(now, 4)
        sat, sun = _next_weekday(now, 5), _next_weekday(now, 6)
        ev("Mom's team review", thu, 17, 18, ["Mom"], "Mom", movable=False)
        ev("Dadi's bhajan group", wed, 18, 19, ["Dadi"], "Dadi", movable=False)
        ev("Rohan's football", sat, 16, 17, ["Rohan"], "Mom", loc="Ground", needs_adult=True, movable=False)
        ev("Family lunch", sun, 13, 14, ["Mom", "Dad", "Rohan", "Dadi"], "Mom", sm=30, em=30)
        ev("Dad's cricket nets", fri, 7, 8, ["Dad"], "Dad")
        s.commit()

        # chore history so fairness has something to show (Mom has carried the most lately)
        past = now - timedelta(days=1)
        history = [("Dishes", 2, "Mom", 1), ("Laundry", 3, "Mom", 3), ("Groceries", 4, "Mom", 5),
                   ("Dishes", 2, "Dad", 4), ("Bins", 1, "Dad", 6), ("Water plants", 1, "Rohan", 2),
                   ("Tidy room", 2, "Rohan", 7), ("Fold clothes", 2, "Dadi", 2), ("Sort pulses", 2, "Dadi", 6)]
        for title, effort, who, days_ago in history:
            s.add(Chore(title=title, effort=effort, kid_ok=who == "Rohan", assigned_to=m[who],
                        assigned_at=c.to_db(past - timedelta(days=days_ago - 1)), status="done",
                        completed_at=c.to_db(past - timedelta(days=days_ago - 1))))
        s.commit()
    return {"seeded": True}


if __name__ == "__main__":
    out = seed(reset="--reset" in sys.argv)
    print("Seeded the Hearth demo family." if out["seeded"] else "Database already has data (use --reset to start over).")
