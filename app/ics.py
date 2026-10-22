"""Minimal .ics (RFC 5545) export and import, no extra dependencies.

Export: one VEVENT per Hearth event, floating-free UTC times. Import: reads SUMMARY, DTSTART, DTEND (or DURATION),
LOCATION; handles line folding, UTC ("Z"), floating and all-day values. Recurrence rules are not expanded
(RRULE is reported as skipped) so nothing is silently invented.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone, tzinfo


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _unesc(s: str) -> str:
    return re.sub(r"\\([\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), s)


def _utc(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fold(line: str) -> str:
    out, b = [], line.encode()
    while len(b) > 75:
        cut = 75
        while cut > 0 and (b[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(b[:cut].decode())
        b = b[cut:]
        b = b" " + b
    out.append(b.decode())
    return "\r\n".join(out)


def export_ics(events: list[dict], name: str = "Hearth family calendar") -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Hearth//Family coordinator//EN", f"X-WR-CALNAME:{_esc(name)}"]
    for e in events:
        if e.get("status") == "cancelled":
            continue
        desc = "Who: " + ", ".join(e.get("attendees", []))
        if e.get("needs_adult"):
            desc += " (needs an adult)"
        lines += ["BEGIN:VEVENT", f"UID:hearth-{e['id']}@hearth.local", f"DTSTAMP:{_utc(e['start'])}",
                  f"DTSTART:{_utc(e['start'])}", f"DTEND:{_utc(e['end'])}", f"SUMMARY:{_esc(e['title'])}",
                  f"DESCRIPTION:{_esc(desc)}"]
        if e.get("location"):
            lines.append(f"LOCATION:{_esc(e['location'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


def _parse_dt(value: str, params: str, tz: tzinfo) -> tuple[datetime, bool]:
    """Returns (aware datetime, all_day)."""
    v = value.strip()
    if "VALUE=DATE" in params.upper() and "T" not in v:
        d = datetime.strptime(v, "%Y%m%d").date()
        return datetime.combine(d, time(0), tzinfo=tz), True
    if v.endswith("Z"):
        return datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(tz), False
    return datetime.strptime(v, "%Y%m%dT%H%M%S").replace(tzinfo=tz), False


def _duration(v: str) -> timedelta:
    m = re.fullmatch(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m:
        return timedelta(hours=1)
    w, d, h, mi, s = (int(x or 0) for x in m.groups())
    return timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def import_ics(text: str, tz: tzinfo) -> dict:
    """Returns {"events": [{title, start, end, location}], "skipped": [{title, reason}]}."""
    unfolded = re.sub(r"\r?\n[ \t]", "", text)
    events, skipped = [], []
    cur: dict | None = None
    for raw in unfolded.splitlines():
        line = raw.strip()
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            title = _unesc(cur.get("SUMMARY", ("", ""))[1]) or "(untitled)"
            try:
                if "RRULE" in cur:
                    skipped.append({"title": title, "reason": "repeating event (not expanded)"})
                elif "DTSTART" not in cur:
                    skipped.append({"title": title, "reason": "no start time"})
                else:
                    s, all_day = _parse_dt(cur["DTSTART"][1], cur["DTSTART"][0], tz)
                    if "DTEND" in cur:
                        e, _ = _parse_dt(cur["DTEND"][1], cur["DTEND"][0], tz)
                    elif "DURATION" in cur:
                        e = s + _duration(cur["DURATION"][1])
                    else:
                        e = s + (timedelta(days=1) if all_day else timedelta(hours=1))
                    if e <= s:
                        e = s + timedelta(hours=1)
                    events.append({"title": title, "start": s.isoformat(), "end": e.isoformat(),
                                   "location": _unesc(cur.get("LOCATION", ("", ""))[1]) or None, "all_day": all_day})
            except ValueError:
                skipped.append({"title": title, "reason": "unreadable date"})
            cur = None
        elif cur is not None and ":" in line:
            head, _, val = line.partition(":")
            name, _, params = head.partition(";")
            cur.setdefault(name.upper(), (params, val))
    return {"events": events, "skipped": skipped}
