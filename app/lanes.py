"""Per-person lane timeline (pure HTML, no Streamlit): one row per family member, events as bars.

A clash is two bars overlapping in a lane (stacked in sub-rows so both stay readable); an event that needs an
adult with nobody free is striped red. Colour is never the only cue: clash bars also carry a "!" and the text.
"""
from __future__ import annotations

import html
from datetime import date, datetime, time, timedelta, tzinfo

ROW_H = 30


def _dt(iso: str, tz: tzinfo) -> datetime:
    return datetime.fromisoformat(iso).astimezone(tz)


def _pct(value: float, total: float) -> float:
    return max(0.0, min(100.0, 100.0 * value / total))


def _fmt(d: datetime) -> str:
    h = d.hour % 12 or 12
    return f"{h}{'' if d.minute == 0 else f':{d.minute:02d}'} {'am' if d.hour < 12 else 'pm'}"


def day_window(day: date, tz: tzinfo, start_h: int = 7, end_h: int = 22) -> tuple[datetime, datetime]:
    base = datetime.combine(day, time(0), tzinfo=tz)
    return base + timedelta(hours=start_h), base + timedelta(hours=end_h)


def auto_day_window(events: list[dict], day: date, tz: tzinfo, min_hours: int = 8) -> tuple[datetime, datetime]:
    """A day window that fits the day's events (so bars are readable): padded an hour, at least `min_hours` wide,
    clamped to 06:00-23:00. With no events, a calm 08:00-20:00."""
    base = datetime.combine(day, time(0), tzinfo=tz)
    mine = [e for e in events if e.get("status") != "cancelled"]
    if not mine:
        return base + timedelta(hours=8), base + timedelta(hours=20)
    lo = min(_dt(e["start"], tz) for e in mine) - timedelta(hours=1)
    hi = max(_dt(e["end"], tz) for e in mine) + timedelta(hours=1)
    lo_h = max(6, lo.hour if lo.date() == day else 6)
    hi_h = 23 if hi.date() != day else min(23, hi.hour + (1 if hi.minute else 0))
    if hi_h - lo_h < min_hours:
        mid = (lo_h + hi_h) / 2
        lo_h = max(6, int(mid - min_hours / 2))
        hi_h = min(23, lo_h + min_hours)
        lo_h = max(6, hi_h - min_hours)
    return base + timedelta(hours=lo_h), base + timedelta(hours=hi_h)


def focus_window(events: list[dict], tz: tzinfo, pad_min: int = 30) -> tuple[datetime, datetime]:
    """A window hugging the given events, snapped to whole hours and at least three hours wide."""
    lo = min(_dt(e["start"], tz) for e in events) - timedelta(minutes=pad_min)
    hi = max(_dt(e["end"], tz) for e in events) + timedelta(minutes=pad_min)
    lo = lo.replace(minute=0, second=0, microsecond=0)
    if hi.minute or hi.second:
        hi = hi.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    if hi - lo < timedelta(hours=3):
        hi = lo + timedelta(hours=3)
    return lo, hi


def _pack(items: list[dict]) -> list[list[dict]]:
    """Greedy sub-rows so overlapping events in one lane never hide each other."""
    rows: list[list[dict]] = []
    for it in sorted(items, key=lambda x: (x["s"], x["e"])):
        for row in rows:
            if row[-1]["e"] <= it["s"]:
                row.append(it)
                break
        else:
            rows.append([it])
    return rows


def lanes_html(
    events: list[dict],
    members: list[dict],
    conflicts: list[dict],
    tz: tzinfo,
    window: tuple[datetime, datetime],
    now_dt: datetime | None = None,
    compact: bool = False,
    aria_label: str = "Timeline by person",
) -> str:
    lo, hi = window
    total = (hi - lo).total_seconds() / 60
    clash_ids = {i for c in conflicts for i in c["event_ids"]}
    stripe_ids = {c["event_ids"][0] for c in conflicts if c["type"] == "COVERAGE_CLASH" and c["event_ids"]}

    shown = []
    for e in events:
        if e.get("status") == "cancelled":
            continue
        s, en = _dt(e["start"], tz), _dt(e["end"], tz)
        if en <= lo or s >= hi:
            continue
        shown.append({**e, "s": s, "e": en})

    names_in_use = {n for e in shown for n in e["attendees"]}
    lanes = [m for m in members if (m["name"] in names_in_use or not compact)]

    out = [f'<div class="lanes{" compact" if compact else ""}" role="img" aria-label="{html.escape(aria_label)}">',
           f'<div class="lanes-scroll"><div class="lanes-inner" style="--nw:{72 if compact else 96}px">']
    # hour header + grid
    hours = []
    t = lo.replace(minute=0, second=0, microsecond=0)
    if t < lo:
        t += timedelta(hours=1)
    step = 1 if total <= 8 * 60 else 2 if compact else 1
    while t <= hi:
        pos = _pct((t - lo).total_seconds() / 60, total)
        hours.append((pos, _fmt(t)))
        t += timedelta(hours=step)
    out.append('<div class="lane-head"><div class="lane-name"></div><div class="lane-track hdr">'
               + "".join(f'<span class="hr" style="left:{pos:.2f}%">{label}</span>' for pos, label in hours) + "</div></div>")

    for m in lanes:
        mine = [e for e in shown if m["name"] in e["attendees"]]
        rows = _pack(mine) or [[]]
        height = ROW_H * len(rows) + 8
        out.append(
            f'<div class="lane"><div class="lane-name"><span class="chip" style="background:{m["color"]}">'
            f'{html.escape(m.get("initials") or m["name"][:1])}</span>{html.escape(m["name"])}</div>'
            f'<div class="lane-track" style="height:{height}px">')
        out.append("".join(f'<i class="grid" style="left:{pos:.2f}%"></i>' for pos, _ in hours))
        for ri, row in enumerate(rows):
            for e in row:
                s, en = max(e["s"], lo), min(e["e"], hi)
                left = _pct((s - lo).total_seconds() / 60, total)
                width = max(1.5, _pct((en - s).total_seconds() / 60, total))
                cls = ["lbar"]
                if e["id"] in clash_ids:
                    cls.append("clash")
                if e["id"] in stripe_ids:
                    cls.append("stripe")
                if e.get("status") == "pending_approval":
                    cls.append("pending")
                mark = "! " if e["id"] in clash_ids else ""
                tip = f'{e["title"]}, {_fmt(e["s"])} to {_fmt(e["e"])}'
                if e.get("needs_adult"):
                    tip += " (needs an adult)"
                color = "" if "clash" in cls else f"background:{m['color']};"
                out.append(
                    f'<div class="{" ".join(cls)}" title="{html.escape(tip)}" '
                    f'style="left:{left:.2f}%;width:{width:.2f}%;top:{4 + ri * ROW_H}px;height:{ROW_H - 4}px;{color}">'
                    f'{mark}{html.escape(e["title"])}</div>')
        out.append("</div></div>")

    if now_dt is not None and lo <= now_dt <= hi:
        left = _pct((now_dt - lo).total_seconds() / 60, total)
        out.append(f'<div class="now-line" style="left:calc(var(--nw) + (100% - var(--nw)) * {left / 100:.4f})" '
                   f'title="Now"></div>')
    out.append("</div></div></div>")
    return "".join(out)
