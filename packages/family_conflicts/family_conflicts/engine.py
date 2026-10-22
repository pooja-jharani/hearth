"""Deterministic conflict engine for household schedules.

Pure Python, no I/O. All datetimes passed in must be timezone-aware.
Intervals are half-open: [start, end). Back-to-back events do not clash.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, tzinfo

WAKE_START_HOUR = 8
WAKE_END_HOUR = 21
STEP_MIN = 30
COVERAGE_BUFFER_MIN = 30  # gap kept after a fixed event that has a location

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class Person:
    id: int
    name: str
    role: str  # parent | child | grandparent
    is_adult: bool


@dataclass(frozen=True)
class Appt:
    id: int
    title: str
    start: datetime
    end: datetime
    attendees: tuple[int, ...] = ()
    needs_adult: bool = False
    movable: bool = True
    location: str | None = None


@dataclass(frozen=True)
class Rule:
    id: int
    member_id: int
    kind: str  # no_after | no_before | no_task
    params: dict


@dataclass(frozen=True)
class Conflict:
    id: str
    type: str  # PERSON_CLASH | COVERAGE_CLASH | RULE_VIOLATION
    severity: str
    event_ids: tuple[int, ...]
    people: tuple[str, ...]
    why: str
    start: datetime | None = None

    def to_dict(self, tz: tzinfo | None = None) -> dict:
        start = self.start.astimezone(tz) if (self.start and tz) else self.start
        return {
            "id": self.id,
            "type": self.type,
            "severity": self.severity,
            "event_ids": list(self.event_ids),
            "people": list(self.people),
            "why": self.why,
            "start": start.isoformat() if start else None,
        }


@dataclass(frozen=True)
class Option:
    rank: int
    kind: str  # move | reassign | add_attendee | keep
    label: str
    reason: str
    event_id: int | None = None
    new_start: datetime | None = None
    new_end: datetime | None = None
    add_member: int | None = None
    remove_member: int | None = None
    people_affected: int = 0
    shift_min: int = 0

    def to_dict(self, tz: tzinfo | None = None) -> dict:
        def conv(d: datetime | None):
            if d is None:
                return None
            return (d.astimezone(tz) if tz else d).isoformat()

        return {
            "rank": self.rank,
            "kind": self.kind,
            "label": self.label,
            "reason": self.reason,
            "event_id": self.event_id,
            "new_start": conv(self.new_start),
            "new_end": conv(self.new_end),
            "add_member": self.add_member,
            "remove_member": self.remove_member,
        }


# ---------------------------------------------------------------- helpers

def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open interval overlap."""
    return a_start < b_end and b_start < a_end


def fmt_time(dt: datetime, tz: tzinfo) -> str:
    local = dt.astimezone(tz)
    h = local.hour % 12 or 12
    suffix = "am" if local.hour < 12 else "pm"
    return f"{h} {suffix}" if local.minute == 0 else f"{h}:{local.minute:02d} {suffix}"


def fmt_day(dt: datetime, tz: tzinfo) -> str:
    return dt.astimezone(tz).strftime("%A")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def task_matches(title: str, task: str | None) -> bool:
    """'pickup' matches 'Rohan pick-up', 'pick up Rohan', 'pickups'."""
    if not task:
        return True
    return _norm(task) in _norm(title)


def _hhmm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def violates(rule: Rule, appt: Appt, tz: tzinfo) -> bool:
    if rule.member_id not in appt.attendees:
        return False
    task = rule.params.get("task")
    if not task_matches(appt.title, task):
        return False
    local = appt.start.astimezone(tz)
    mins = local.hour * 60 + local.minute
    if rule.kind == "no_task":
        return bool(task)
    t = rule.params.get("time")
    if not t:
        return False
    h, m = _hhmm(t)
    limit = h * 60 + m
    if rule.kind == "no_after":
        return mins >= limit
    if rule.kind == "no_before":
        return mins < limit
    return False


def _name(people: dict[int, Person], pid: int) -> str:
    return people[pid].name if pid in people else f"member {pid}"


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def parents_free_for(appt: Appt, appts: list[Appt], people: list[Person]) -> list[Person]:
    """Parents not attending any other event that overlaps `appt`."""
    free = []
    for p in people:
        if p.role != "parent":
            continue
        busy = any(
            o.id != appt.id and p.id in o.attendees and overlaps(appt.start, appt.end, o.start, o.end)
            for o in appts
        )
        if not busy:
            free.append(p)
    return free


def covered(appt: Appt, appts: list[Appt], people: list[Person]) -> bool:
    """An event that needs an adult is covered if an adult attends it, or a parent is free."""
    by_id = {p.id: p for p in people}
    if any(by_id[a].is_adult for a in appt.attendees if a in by_id):
        return True
    return bool(parents_free_for(appt, appts, people))


# --------------------------------------------------------------- detection

def detect(appts: list[Appt], people: list[Person], rules: list[Rule], tz: tzinfo) -> list[Conflict]:
    by_id = {p.id: p for p in people}
    out: list[Conflict] = []
    ordered = sorted(appts, key=lambda a: (a.start, a.id))

    # PERSON_CLASH
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if b.start >= a.end:
                break
            if not overlaps(a.start, a.end, b.start, b.end):
                continue
            shared = [x for x in a.attendees if x in b.attendees]
            if not shared:
                continue
            names = [_name(by_id, x) for x in shared]
            lo, hi = sorted((a.id, b.id))
            start = max(a.start, b.start)
            out.append(Conflict(
                id=f"c-PER-{lo}-{hi}",
                type="PERSON_CLASH",
                severity="medium",
                event_ids=(lo, hi),
                people=tuple(names),
                why=f"{_join(names)} {'is' if len(names) == 1 else 'are'} booked for both "
                    f"{a.title} and {b.title} at {fmt_time(start, tz)}.",
                start=start,
            ))

    # COVERAGE_CLASH
    for a in ordered:
        if not a.needs_adult or covered(a, appts, people):
            continue
        parents = [p for p in people if p.role == "parent"]
        names = [p.name for p in parents]
        blockers = sorted({
            o.id for o in appts
            if o.id != a.id and overlaps(a.start, a.end, o.start, o.end)
            and any(p.id in o.attendees for p in parents)
        })
        if len(names) == 2:
            busy = f"both {names[0]} and {names[1]} are busy"
        elif names:
            busy = f"{_join(names)} {'is' if len(names) == 1 else 'are'} busy"
        else:
            busy = "no parent is available"
        out.append(Conflict(
            id=f"c-COV-{a.id}",
            type="COVERAGE_CLASH",
            severity="high",
            event_ids=(a.id, *blockers),
            people=tuple(names),
            why=f"{a.title} at {fmt_time(a.start, tz)} needs an adult, and {busy}.",
            start=a.start,
        ))

    # RULE_VIOLATION
    for a in ordered:
        for r in rules:
            if violates(r, a, tz):
                name = _name(by_id, r.member_id)
                source = r.params.get("source_text") or describe_rule(r, name)
                out.append(Conflict(
                    id=f"c-RUL-{a.id}-{r.id}",
                    type="RULE_VIOLATION",
                    severity="high",
                    event_ids=(a.id,),
                    people=(name,),
                    why=f"{a.title} at {fmt_time(a.start, tz)} breaks your rule: {source}.",
                    start=a.start,
                ))

    out.sort(key=lambda c: (SEVERITY_ORDER.get(c.severity, 9), c.start or datetime.max.replace(tzinfo=tz), c.id))
    return out


def describe_rule(rule: Rule, member_name: str) -> str:
    task = rule.params.get("task")
    what = f"{task}s" if task else "plans"
    t = rule.params.get("time")
    if rule.kind == "no_after" and t:
        return f"{member_name} won't do {what} at or after {_pretty_hhmm(t)}"
    if rule.kind == "no_before" and t:
        return f"{member_name} won't do {what} before {_pretty_hhmm(t)}"
    if rule.kind == "no_task":
        return f"{member_name} won't do {what}"
    return f"{member_name}: {rule.kind}"


def _pretty_hhmm(value: str) -> str:
    h, m = _hhmm(value)
    hh = h % 12 or 12
    return f"{hh} {'am' if h < 12 else 'pm'}" if m == 0 else f"{hh}:{m:02d} {'am' if h < 12 else 'pm'}"


# ------------------------------------------------------------- resolutions

def _within_waking(start: datetime, end: datetime, tz: tzinfo) -> bool:
    ls, le = start.astimezone(tz), end.astimezone(tz)
    if ls.date() != le.date() and not (le.hour == 0 and le.minute == 0):
        return False
    end_minutes = le.hour * 60 + le.minute if ls.date() == le.date() else 24 * 60
    return ls.hour >= WAKE_START_HOUR and end_minutes <= WAKE_END_HOUR * 60


def _swap(appts: list[Appt], new: Appt) -> list[Appt]:
    return [new if a.id == new.id else a for a in appts]


def _ids(conflicts: list[Conflict]) -> set[str]:
    return {c.id for c in conflicts}


def _best_move(
    appt: Appt,
    appts: list[Appt],
    people: list[Person],
    rules: list[Rule],
    tz: tzinfo,
    target: Conflict,
    baseline: set[str],
    min_start: datetime | None = None,
) -> tuple[datetime, datetime, int] | None:
    """Smallest same-day shift that clears `target` and creates no new conflict."""
    dur = appt.end - appt.start
    candidates = []
    for k in range(-8, 13):
        if k == 0:
            continue
        shift = timedelta(minutes=STEP_MIN * k)
        ns = appt.start + shift
        ne = ns + dur
        if min_start is not None and ns < min_start:
            continue
        if ns.astimezone(tz).date() != appt.start.astimezone(tz).date():
            continue
        if not _within_waking(ns, ne, tz):
            continue
        candidates.append((abs(k), 0 if k > 0 else 1, ns, ne))
    for _, _, ns, ne in sorted(candidates, key=lambda c: (c[0], c[1])):
        hypo = _swap(appts, replace(appt, start=ns, end=ne))
        after = _ids(detect(hypo, people, rules, tz))
        if target.id not in after and not (after - baseline):
            return ns, ne, int(abs((ns - appt.start).total_seconds()) // 60)
    return None


def _free_adults(appt: Appt, appts: list[Appt], people: list[Person]) -> list[Person]:
    out = []
    for p in people:
        if not p.is_adult or p.id in appt.attendees:
            continue
        busy = any(
            o.id != appt.id and p.id in o.attendees and overlaps(appt.start, appt.end, o.start, o.end)
            for o in appts
        )
        if not busy:
            out.append(p)
    return out


def suggest(
    conflict: Conflict,
    appts: list[Appt],
    people: list[Person],
    rules: list[Rule],
    tz: tzinfo,
    max_options: int = 3,
) -> list[Option]:
    """Return up to `max_options` ranked ways to fix a conflict. The last is always 'keep as is'."""
    by_ev = {a.id: a for a in appts}
    by_p = {p.id: p for p in people}
    baseline = _ids(detect(appts, people, rules, tz))
    raw: list[Option] = []

    def add_move(appt: Appt, min_start: datetime | None = None, why_extra: str = ""):
        res = _best_move(appt, appts, people, rules, tz, conflict, baseline, min_start)
        if not res:
            return
        ns, ne, shift = res
        n = len(appt.attendees)
        reason = f"Smallest move that clears the clash; it creates no new one{why_extra}."
        raw.append(Option(0, "move", f"Move {appt.title} to {fmt_time(ns, tz)}", reason,
                          appt.id, ns, ne, people_affected=n, shift_min=shift))

    if conflict.type == "PERSON_CLASH":
        for eid in conflict.event_ids:
            a = by_ev.get(eid)
            if a and a.movable:
                add_move(a)

    elif conflict.type == "COVERAGE_CLASH":
        fixed = by_ev.get(conflict.event_ids[0])
        if fixed is None:
            return []
        parent_ids = {p.id for p in people if p.role == "parent"}
        for eid in conflict.event_ids[1:]:
            b = by_ev.get(eid)
            if b and b.movable and parent_ids & set(b.attendees):
                buf = timedelta(minutes=COVERAGE_BUFFER_MIN if fixed.location else 0)
                who = _join([by_p[x].name for x in b.attendees if x in parent_ids])
                gap = " and leaves time to travel" if fixed.location else ""
                add_move(b, min_start=fixed.end + buf, why_extra=f"; {fixed.title} stays fixed{gap}, so {who} can go")
        for p in _free_adults(fixed, appts, people):
            hypo = _swap(appts, replace(fixed, attendees=fixed.attendees + (p.id,)))
            after = _ids(detect(hypo, people, rules, tz))
            if conflict.id not in after and not (after - baseline):
                raw.append(Option(0, "add_attendee", f"Ask {p.name} to attend {fixed.title}",
                                  f"{p.name} is free then, so nothing else has to move.",
                                  fixed.id, add_member=p.id, people_affected=1))
        if fixed.movable:
            add_move(fixed)

    elif conflict.type == "RULE_VIOLATION":
        a = by_ev.get(conflict.event_ids[0])
        if a is None:
            return []
        rule_id = int(conflict.id.rsplit("-", 1)[1])
        rule = next((r for r in rules if r.id == rule_id), None)
        if rule is not None:
            bad = rule.member_id
            candidates = sorted(_free_adults(a, appts, people), key=lambda p: (p.role != "parent", p.name))
            for p in candidates:
                if p.id == bad:
                    continue
                hypo = _swap(appts, replace(a, attendees=tuple(x for x in a.attendees if x != bad) + (p.id,)))
                after = _ids(detect(hypo, people, rules, tz))
                if conflict.id not in after and not (after - baseline):
                    raw.append(Option(0, "reassign", f"Ask {p.name} to do it instead of {by_p[bad].name}",
                                      f"{p.name} is free then and no saved rule stops them.",
                                      a.id, add_member=p.id, remove_member=bad, people_affected=1))
            if a.movable:
                add_move(a)

    raw.sort(key=lambda o: (o.people_affected, {"move": 0, "reassign": 1, "add_attendee": 1}.get(o.kind, 2), o.shift_min))
    actionable = raw[: max(0, max_options - 1)]
    ranked = [replace(o, rank=i + 1) for i, o in enumerate(actionable)]
    ranked.append(Option(len(ranked) + 1, "keep", "Keep as is",
                         "Leave the plans alone; the clash stays flagged."))
    return ranked


def apply_option(option: Option, appts: list[Appt]) -> list[Appt]:
    """Return a new appt list with the option applied (used for verification and previews)."""
    out = []
    for a in appts:
        if option.event_id == a.id and option.kind != "keep":
            att = list(a.attendees)
            if option.remove_member in att:
                att.remove(option.remove_member)
            if option.add_member is not None and option.add_member not in att:
                att.append(option.add_member)
            out.append(replace(
                a,
                start=option.new_start or a.start,
                end=option.new_end or a.end,
                attendees=tuple(att),
            ))
        else:
            out.append(a)
    return out


# --------------------------------------------------------------- free slots

def free_slots(
    appts: list[Appt],
    people: list[Person],
    attendee_ids: list[int],
    duration_min: int,
    earliest: datetime,
    latest: datetime,
    tz: tzinfo,
    needs_adult: bool = False,
    rules: list[Rule] | None = None,
    count: int = 3,
) -> list[tuple[datetime, datetime]]:
    """Up to `count` start/end pairs where every attendee is free, inside waking hours."""
    rules = rules or []
    dur = timedelta(minutes=duration_min)
    step = timedelta(minutes=STEP_MIN)
    t = earliest.astimezone(tz)
    rem = (t.minute % STEP_MIN, t.second, t.microsecond)
    if any(rem):
        t = t.replace(minute=t.minute - t.minute % STEP_MIN, second=0, microsecond=0) + step
    out: list[tuple[datetime, datetime]] = []
    probe_id = -1
    limit = latest.astimezone(tz)
    while t + dur <= limit and len(out) < count:
        end = t + dur
        if _within_waking(t, end, tz):
            probe = Appt(probe_id, "probe", t, end, tuple(attendee_ids), needs_adult=needs_adult)
            hypo = appts + [probe]
            bad = [c for c in detect(hypo, people, rules, tz) if probe_id in c.event_ids]
            if not bad:
                out.append((t, end))
        t += step
    return out
