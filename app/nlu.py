"""Small rule-based language helpers for MOCK mode (no AWS needed) and the circular importer.

The live agent (Bedrock) does this with the model; mock mode exists so the whole app can be built,
tested and demoed offline. It covers the demo script and the eval sentences, not free-form English.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

WEEKDAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
            "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
            "sunday": 6, "sun": 6}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"

TIME_RANGE = re.compile(
    r"(?:from\s+)?\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:to|-|until|till)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.IGNORECASE)
TIME_MER = re.compile(r"(?:\bat\s+)?\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.IGNORECASE)
TIME_COLON = re.compile(r"\b(\d{1,2}):(\d{2})\b")
TIME_AT = re.compile(r"\bat\s+(\d{1,2})(?::(\d{2}))?\b(?!\s*(?:st|nd|rd|th))", re.IGNORECASE)

MEAL_DEFAULTS = {"breakfast": (9, 0), "lunch": (13, 0), "dinner": (19, 0), "party": (17, 0), "birthday": (18, 0)}
ALL_FAMILY_WORDS = ("birthday", "dinner", "lunch", "family", "festival", "diwali", "wedding", "puja")


def _h24(h: int, mer: str | None, morning: bool) -> int:
    if mer:
        mer = mer.lower()
        return (h % 12) + (12 if mer == "pm" else 0)
    if h > 12:
        return h
    if h == 12:
        return 12
    return h if morning else h + 12  # family plans without am/pm are read as evening


def extract_time(text: str) -> tuple[tuple[int, int] | None, tuple[int, int] | None, str]:
    morning = bool(re.search(r"\bmorning\b", text, re.IGNORECASE))
    m = TIME_RANGE.search(text)
    if m:
        h1, m1, mer1, h2, m2, mer2 = int(m.group(1)), int(m.group(2) or 0), m.group(3), int(m.group(4)), \
            int(m.group(5) or 0), m.group(6)
        mer1 = mer1 or mer2
        if (h1 > 12 and not mer1) or h2 <= 12:  # looks like a time range, not "3 to 4 kids"
            s24 = _h24(h1, mer1, morning)
            e24 = _h24(h2, mer2 or mer1, morning)
            if e24 <= s24 and not (mer2 or mer1):
                e24 += 12
            return (s24, m1), (e24, m2), (text[:m.start()] + " " + text[m.end():])
    m = TIME_MER.search(text)
    if m:
        return (_h24(int(m.group(1)), m.group(3), morning), int(m.group(2) or 0)), None, \
            (text[:m.start()] + " " + text[m.end():])
    m = TIME_AT.search(text)
    if m and int(m.group(1)) <= 24:
        return (_h24(int(m.group(1)), None, morning), int(m.group(2) or 0)), None, \
            (text[:m.start()] + " " + text[m.end():])
    m = TIME_COLON.search(text)
    if m and int(m.group(1)) <= 24:
        return (_h24(int(m.group(1)), None, morning), int(m.group(2))), None, \
            (text[:m.start()] + " " + text[m.end():])
    return None, None, text


def bare_hour(text: str) -> tuple[int, int] | None:
    """'6' or '6 pm' alone, as in 'move the call to 6'."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*(am|pm)?\s*", text, re.IGNORECASE)
    if m and 1 <= int(m.group(1)) <= 24:
        return _h24(int(m.group(1)), m.group(2), False), 0
    return None


def extract_day(text: str, today: date) -> tuple[date | None, str]:
    low = text.lower()
    m = re.search(r"\bday after tomorrow\b", low)
    if m:
        return today + timedelta(days=2), text[:m.start()] + " " + text[m.end():]
    for word, delta in (("today", 0), ("tonight", 0), ("tomorrow", 1)):
        m = re.search(rf"\b{word}\b", low)
        if m:
            return today + timedelta(days=delta), text[:m.start()] + " " + text[m.end():]
    m = re.search(rf"\b(?:(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{MONTH_RE}|{MONTH_RE}\s+(\d{{1,2}})(?:st|nd|rd|th)?)\b", low)
    if m:
        if m.group(1):
            day, mon = int(m.group(1)), MONTHS[m.group(2)[:3]]
        else:
            mon, day = MONTHS[m.group(3)[:3]], int(m.group(4))
        try:
            d = date(today.year, mon, day)
        except ValueError:
            d = None
        if d:
            if d < today:
                d = date(today.year + 1, mon, day)
            return d, re.sub(r"\bon\s*$", "", text[:m.start()]) + " " + text[m.end():]
    m = re.search(r"\b(?:(next|this)\s+)?(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")\b", low)
    if m:
        target = WEEKDAYS[m.group(2)]
        d = today
        if m.group(1) == "next" or d.weekday() != target:
            d += timedelta(days=1)
            while d.weekday() != target:
                d += timedelta(days=1)
        return d, text[:m.start()] + " " + text[m.end():]
    return None, text


def at_time(d: date, hm: tuple[int, int]) -> str:
    return datetime(d.year, d.month, d.day, hm[0], hm[1]).isoformat()


FILLER_HEAD = re.compile(
    r"^\s*(?:i have|i've got|i got|we have|we've got|there is|there's|add|put|schedule|book|note that|remind me of|"
    r"can you add|please add|please)\s+(?:an?\s+|the\s+)?", re.IGNORECASE)
LOCATION = re.compile(r"\bat\s+(?:the\s+)?(school|home|hospital|clinic|office|ground|temple|mall|college|club|park|gym)\b", re.IGNORECASE)


def tidy_title(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip(" ,.;:-")
    t = FILLER_HEAD.sub("", t)
    t = re.sub(r"\b(is|are|will be|on|at|from)\s*$", "", t, flags=re.IGNORECASE).strip(" ,.;:-")
    t = re.sub(r"^(on|at)\s+", "", t, flags=re.IGNORECASE)
    return t[:1].upper() + t[1:] if t else t


NAME_WORDS = {"mom": "Mom", "mummy": "Mom", "mama": "Mom", "dad": "Dad", "papa": "Dad", "daddy": "Dad",
              "dadi": "Dadi", "grandma": "Dadi", "rohan": "Rohan"}


def mentioned_members(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[A-Za-z]+", text):
        n = NAME_WORDS.get(w.lower())
        if n and n not in out:
            out.append(n)
    return out


def parse_event(segment: str, speaker: str, today: date, default_day: date | None = None,
                default_hm: tuple[int, int] = (18, 0)) -> dict | None:
    """Turn 'Rohan's PTM is Thursday at 5 at school' into add_event arguments (or None)."""
    day, rest = extract_day(segment, today)
    day = day or default_day
    if day is None:
        return None
    start, end, rest = extract_time(rest)
    low = rest.lower()
    if start is None:
        for key, hm in MEAL_DEFAULTS.items():
            if key in low:
                start = hm
                break
        else:
            start = default_hm
    loc = None
    lm = LOCATION.search(rest)
    if lm:
        loc = lm.group(1).lower()
        rest = rest[:lm.start()] + " " + rest[lm.end():]
    title = tidy_title(rest)
    subject = None
    hm = re.match(r"^(\w+)\s+(?:has|have|is having|will have|got|has got)\s+(?:an?\s+|the\s+)?(.+)$", title, re.IGNORECASE)
    wm = re.match(r"^(\w+)\s+(?:will|to|should|can)\s+(?!have\b)(.+)$", title, re.IGNORECASE)
    if hm and hm.group(1).lower() in NAME_WORDS:
        subject = NAME_WORDS[hm.group(1).lower()]
        title = hm.group(2)[:1].upper() + hm.group(2)[1:]
    elif wm and wm.group(1).lower() in NAME_WORDS:
        subject = NAME_WORDS[wm.group(1).lower()]
        title = wm.group(2)[:1].upper() + wm.group(2)[1:]
    if not title:
        return None
    members = mentioned_members(title)
    whole_family = any(w in title.lower() for w in ALL_FAMILY_WORDS)
    possessive = re.match(r"^(\w+)['’]s\b", title)
    first_person = bool(re.search(r"\bi\b|\bmy\b|\bi've\b", segment, re.IGNORECASE))
    if whole_family and not possessive:
        attendees = ["Mom", "Dad", "Rohan", "Dadi"]
    elif possessive and NAME_WORDS.get(possessive.group(1).lower()):
        attendees = [NAME_WORDS[possessive.group(1).lower()]]
    elif subject:
        attendees = [subject] + [m for m in mentioned_members(title) if m != subject]
    elif members and not first_person:
        attendees = members
    else:
        attendees = [speaker]
    needs_adult = bool(re.search(r"\bptm\b|parent[- ]teacher|school|doctor|dentist|vaccin", segment, re.IGNORECASE)) \
        and "Rohan" in attendees
    fixed = bool(re.search(r"\bptm\b|parent[- ]teacher|exam|doctor|dentist|appointment|flight|train", segment, re.IGNORECASE))
    args = {
        "title": title, "start": at_time(day, start), "attendees": attendees,
        "needs_adult": needs_adult, "movable": not fixed, "created_by": speaker,
    }
    if end:
        args["end"] = at_time(day, end)
    if loc:
        args["location"] = loc
    return args


def split_segments(text: str) -> list[str]:
    parts = re.split(r",|;|\band then\b|\bthen\b|\band\b(?=\s+(?:on\s+)?(?:" + "|".join(WEEKDAYS) + r"|today|tomorrow))", text, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p and p.strip()]


def parse_bulk(text: str, speaker: str, today: date) -> list[dict]:
    out, last_day = [], None
    for seg in split_segments(text):
        day, _ = extract_day(seg, today)
        ev = parse_event(seg, speaker, today, default_day=last_day)
        if ev:
            out.append(ev)
            last_day = day or last_day
    return out


def count_dated_segments(text: str, today: date) -> int:
    return sum(1 for seg in split_segments(text) if extract_day(seg, today)[0])


# --------------------------------------------------------------- rule speech

def parse_rule(text: str) -> dict | None:
    """'Dadi can't do evening pickups' -> add_rule arguments."""
    m = re.search(r"\b(\w+)\s+(?:can'?t|cannot|can not|won'?t|doesn'?t|does not|isn'?t able to|is not able to)\s+"
                  r"(?:do|take|handle|manage|go for|be)?\s*(.+)$", text.strip().rstrip(".!"), re.IGNORECASE)
    if not m or m.group(1).lower() not in NAME_WORDS:
        return None
    member, what = NAME_WORDS[m.group(1).lower()], m.group(2).lower()
    time, kind = None, "no_task"
    if re.search(r"\b(evening|night)s?\b", what):
        kind, time = "no_after", "20:00" if "night" in what else "17:00"
    elif re.search(r"\bmornings?\b", what):
        kind, time = "no_before", "12:00"
    am = re.search(r"\bafter\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", what)
    bm = re.search(r"\bbefore\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", what)
    if am:
        kind, time = "no_after", f"{_h24(int(am.group(1)), am.group(3), False):02d}:{int(am.group(2) or 0):02d}"
    elif bm:
        kind, time = "no_before", f"{_h24(int(bm.group(1)), bm.group(3), True):02d}:{int(bm.group(2) or 0):02d}"
    task = re.sub(r"\b(evenings?|mornings?|nights?|late|early|the|any|anymore|after|before|at)\b|\d{1,2}(:\d{2})?\s*(am|pm)?", " ", what)
    task = re.sub(r"[^a-z ]", " ", task)
    task = re.sub(r"\bpick[- ]?ups?\b", "pickup", task)
    task = re.sub(r"\bdrop[- ]?offs?\b", "dropoff", task)
    task = re.sub(r"\b(\w+?)s\b", r"\1", task) if not re.search(r"\b(bus|class|dress)\b", task) else task
    task = re.sub(r"\s+", " ", task).strip()
    if kind == "no_task" and not task:
        return None
    return {"member": member, "kind": kind, "time": time, "task": task or None, "source_text": text.strip().rstrip(".!")}


# ------------------------------------------------------------------ circular

def extract_circular(text: str, today: date, speaker: str) -> list[dict]:
    """Pull dated items out of pasted school-circular text (mock mode; live mode uses the model)."""
    out = []
    for line in re.split(r"[\n.;]+", text):
        line = line.strip(" -•*\t")
        if not line or not re.search(MONTH_RE, line, re.IGNORECASE):
            continue
        line = re.sub(r"^\s*(?:school\s+)?circular\s*:?\s*", "", line, flags=re.IGNORECASE)
        ev = parse_event(line, speaker, today, default_hm=(9, 0))
        if not ev:
            continue
        title = re.sub(r"\b(?:on|dated?)\s*$", "", ev["title"], flags=re.IGNORECASE).strip()
        ev["title"] = title
        ev["attendees"] = ["Rohan"]
        ev["needs_adult"] = bool(re.search(r"\bptm\b|parent|meeting|collect|report card", line, re.IGNORECASE))
        ev["movable"] = False
        out.append(ev)
    return out
